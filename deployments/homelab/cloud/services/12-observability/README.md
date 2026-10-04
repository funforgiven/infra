# Services observability

This stack monitors the `services-v1` Kubernetes cluster. It is separate from
undercloud monitoring so a workload-cluster failure cannot change or overload
OpenStack monitoring.

Flux applies this directory after the platform controllers. The backup
controller depends on it so backup alerts have a receiver as soon as Velero is
available. The dependency order is declared in [`../waves.yaml`](../waves.yaml).

## Components

| Component | Configuration |
| --- | --- |
| Prometheus | One replica, 15-day or 18 GiB retention, and a retained 20 GiB `rbd1` PVC |
| Alertmanager | One replica and a retained 2 GiB `rbd1` PVC |
| Blackbox Exporter | HTTP and TCP probes for the synthetic-monitoring resources |
| Grafana | Disabled; this stack does not provide a dashboard UI |

Prometheus discovers PodMonitors, Probes, PrometheusRules, and ServiceMonitors
in every namespace. The blackbox probe targets are declared in
[`../50-synthetic-monitoring`](../50-synthetic-monitoring/).

Alertmanager sends firing and resolved alerts to the private infrastructure
Telegram bot. It groups by alert name, namespace, and severity, waits 30
seconds before the first notification, and repeats unresolved alerts every six
hours. `Watchdog` and `InfoInhibitor` are discarded. The services reconciler
builds the Alertmanager values and token Secret from SOPS-encrypted inputs; do
not put either value in this directory or reuse the bot token for another
service.

Failed CronJobs alert once per schedule and resolve when a newer run succeeds;
retained failed Jobs are still available for diagnosis. Dedicated restore and
Forgejo controller alerts replace the generic Job notification for those same
incidents. UniFi's AP rule covers both scrape failure and missing AP telemetry,
so its AP target is excluded from the generic `TargetDown` rule. Node metrics
remain covered. Forgejo deliberately uses `OnDelete` updates and is excluded
from the automatic StatefulSet rollout alert; availability alerts remain active.
The isolated `forge-restore/forgejo-0` verifier is excluded from the generic
15-minute readiness alert because its normal offsite transfer takes about an
hour; its qualification deadline and failure/staleness alerts remain active.

The retired `services-hosts`/`services_restic_last_success_unixtime` alert pair
is removed. UniFi's offsite backup and native runner recovery sources are
monitored by their service-specific rules.

## Check the stack

Run these commands with the services-cluster kubeconfig:

```console
kubectl -n flux-system get kustomization services-observability
kubectl -n services-observability get helmrelease kube-prometheus-stack
kubectl -n services-observability get pods,pvc
kubectl get prometheusrules,servicemonitors,podmonitors,probes -A
```

The Flux Kustomization and HelmRelease must be Ready. Prometheus and
Alertmanager PVCs should remain Bound across pod replacement.

## Recovery and limits

Flux recreates the deployments and monitoring configuration from Git. The
services reconciler recreates the Telegram and generated Alertmanager Secrets
from their encrypted sources. Follow [`../ACTIVATION.md`](../ACTIVATION.md) if
those runtime inputs need to be restored or rotated.

Prometheus and Alertmanager run as single replicas. Their PVCs are retained by
Helm, but the `services-daily` Velero schedule does not include the
`services-observability` namespace. Loss of those volumes therefore loses
recent metrics, alert history, and silences; the declared rules and routing are
recreated by Flux.

Kubelet discovery deliberately uses the legacy `Endpoints` API. With the
pinned Prometheus Operator, EndpointSlice-only discovery can retain a removed
node and omit its replacement (prometheus-operator issue 7678), producing
permanent false `TargetDown` alerts. Keep these three settings together until
an upgraded operator has been tested through node replacement:

```yaml
kubeletEndpointsEnabled: true
kubeletEndpointSliceEnabled: false
serviceDiscoveryRole: Endpoints
```

The discovery role applies to every `ServiceMonitor`, so its manually managed
targets must also use `v1/Endpoints` while this workaround remains enabled.

Helm retries failed installs and upgrades to tolerate the admission-webhook
startup race. cert-manager owns the webhook certificate and CA injection; the
chart's patch Jobs remain disabled.

## Worker disk retention

The `services-node-policy` DaemonSet installs a bounded disk policy on Linux
workers, with control-plane nodes excluded. Kubelet image cleanup starts at
70% filesystem usage and aims for 60%, leaving headroom before the existing
85% image-filesystem eviction threshold. Kubelet owns cleanup of unused images;
the policy does not delete containerd files or active images. More conservative
existing thresholds are retained. See
[Kubernetes image garbage collection](https://kubernetes.io/docs/concepts/architecture/garbage-collection/#container-image-lifecycle).

Journald retains at most 512 MiB and seven days, with a 6 GiB free-space target.
The existing rsyslog file list and reopen hook are preserved; logs rotate daily
or above 64 MiB, checked by an hourly system timer, with four compressed
archives. The initial activation rotates/compresses oversized logs and vacuums
archived journals. This retention policy trades older local logs for space
needed by running workloads.

The existing weekly `fstrim.timer` includes all mounted filesystems that support
discard. Ubuntu's default `--listed-in /etc/fstab:/proc/self/mountinfo` stops at
the nonempty fstab and misses dynamically mounted Cinder volumes. The worker
policy overrides only the service command with `fstrim --all --verbose
--quiet-unsupported`; the weekly schedule stays in place. Trim returns unused
filesystem blocks to thin storage without deleting live files. A trim-only
policy change reloads systemd without restarting kubelet or workload pods.

Initial activation is performed one worker at a time with the reviewed
`components/cloud/services/nodes/apply_policy.py`, using the existing Multus
host access to launch a temporary host systemd service. Direct interactive exec
is cancelled when kubelet restarts and must not be used for this activation.
Verify successful service completion, Ready, DiskPressure=False and the live kubelet thresholds
before proceeding to the next worker. Only then publish the DaemonSet, whose
initial containers see the already installed configuration and make no changes.
The DaemonSet applies the same settings on replacement workers. A configuration
change restarts kubelet; worker containers and their persistent volumes stay in
place. No worker is drained or rebooted during this operation.

The installer retains original configuration under
`/var/lib/services-node-policy` with mode 0700 and restores previous settings if
an activation command fails. It reads the host filesystem through a read-only
mount, with writes limited to the two existing configuration files, journal and
timer and trim-service drop-in directories, local logs and policy/rotation state. Its init
container has explicit chroot/file capabilities; the retained container runs
without root, capabilities or host mounts. API token mounting is disabled and
all pod networking is denied. The script rejects control planes and unexpected
configuration before writing. Removal of the DaemonSet does not undo installed
host configuration; restore the saved files and remove its three retention drop-ins before
reloading systemd and restarting the affected services if rolling back.

On 2026-10-04, all three workers passed serial activation with live 70%/60%
cleanup thresholds and DiskPressure=False. All three IoT networking pods
recovered and both the IoT rollout and NetBird relay alerts resolved. The
observation stack checks the node-policy DaemonSet's readiness through Flux.
The CPU workers still had only about 7–8 GiB free on their 40 GiB root disks.
Their active images cannot be garbage-collected, so bounded logs restore
headroom without guaranteeing room for additional large workloads. These root
disks are Nova image disks, with no attached Cinder boot volume to extend online.
Larger roots require a managed worker resize or replacement; follow the
[worker replacement procedure](../46-forge/WORKER_CAPACITY.md#replacing-the-original-workers)
and preserve the existing CPU/RAM allocation and workload volumes.
