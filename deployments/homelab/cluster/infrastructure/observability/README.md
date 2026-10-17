# Homelab observability

One stack monitors the three NixOS/K3s hosts, direct Rook-Ceph and every
application. The `observability` Flux stage follows storage; database controllers
follow observability so their PodMonitor/PrometheusRule APIs exist. The graph is
declared in [waves/stages.yaml](../../waves/stages.yaml).

| Component | Configuration |
| --- | --- |
| Prometheus | One replica, 15 days or 18 GiB retention, 20 GiB `ceph-block` claim |
| Alertmanager | One replica, 2 GiB `ceph-block` claim; Telegram and encrypted Matrix delivery |
| Grafana | Enabled, 10 GiB `ceph-block` claim, ZITADEL OIDC and management HTTPS route |
| Loki | One monolithic replica, filesystem-backed index/chunks on a 50 GiB `ceph-block` claim |
| Fluent Bit | Host/pod log collection into Loki |
| Blackbox Exporter | Private/public application HTTP/TCP probes |
| Node Exporter | Host metrics plus NixOS etcd-backup success textfiles |

Prometheus discovers monitors, rules and probes in every namespace. Native
K3s controller-manager/scheduler/etcd bundled endpoints are not assumed to be
separate scrape targets. NixOS owns image garbage collection and bounded
journald/container logs.

The chart retries transient admission-webhook startup failures. cert-manager
owns its webhook certificate/CA; patch Jobs are disabled. Kubelet discovery
uses the pinned operator's Endpoints workaround as a coordinated setting:
`kubeletEndpointsEnabled=true`, `kubeletEndpointSliceEnabled=false` and
`serviceDiscoveryRole=Endpoints`; manually managed metric targets keep matching
Endpoints objects. Keep these settings until an operator upgrade is tested.

Alertmanager groups application/backup failures and clears a failed CronJob
incident when a newer execution succeeds. Forge's OnDelete rollout
and long isolated restore verifier use their service-specific rules. UniFi AP
telemetry distinguishes missing metrics/scrape failure from ordinary node
targets. Runtime Telegram/Grafana/Matrix credentials stay SOPS-encrypted.

Restore observability first, verify its CRDs/readiness, then release database
controllers and dependent apps. Single replicas mean Grafana/logs/recent metrics
can be unavailable while a host or RWO volume relocates. Replica-3 Ceph protects
against a host failure; it does not replace an off-cluster history backup.
The `observability-history` schedule exports all four volumes to Backblaze; see
the [backup runbook](../backups/README.md#schedules). Git holds rules,
dashboards, routes and encrypted runtime inputs.

Check:

```sh
nix run .#matrix-access -- cluster -- kubectl -n flux-system get kustomization observability
nix run .#matrix-access -- cluster -- kubectl -n services-observability get helmreleases,pods,pvc
nix run .#matrix-access -- cluster -- kubectl get prometheusrules,servicemonitors,podmonitors,probes -A
```

Require the HelmReleases and Flux stage Ready, PVCs Bound, host/storage targets
present, Grafana OIDC access, searchable logs and a delivered test alert.
NixOS's off-server etcd backups export token/keys with the snapshot and report
`homelab_etcd_backup_last_success_timestamp_seconds`; their schedule and restore
checks are separate from app/history storage recovery.
