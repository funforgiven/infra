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

Helm retries failed installs and upgrades to tolerate the admission-webhook
startup race. cert-manager owns the webhook certificate and CA injection; the
chart's patch Jobs remain disabled.
