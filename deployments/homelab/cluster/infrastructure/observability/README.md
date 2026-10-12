# Homelab observability

One stack monitors the three NixOS/K3s hosts, direct Rook-Ceph and every retained
application. The `observability` Flux stage follows storage; database controllers
follow observability so their PodMonitor/PrometheusRule APIs exist. The graph is
declared in [waves.yaml](../../waves.yaml).

| Component | Target state |
| --- | --- |
| Prometheus | One replica, 15 days or 18 GiB retention, retained 20 GiB `ceph-block` claim |
| Alertmanager | One replica, retained 2 GiB `ceph-block` claim; Telegram and encrypted Matrix delivery |
| Grafana | Enabled, retained 10 GiB `ceph-block` claim, existing OIDC identity and management HTTPS route |
| Loki | One monolithic replica, filesystem-backed index/chunks on a 50 GiB `ceph-block` claim |
| Fluent Bit | Host/pod log collection into Loki |
| Blackbox Exporter | Private/public application HTTP/TCP probes |
| Node Exporter | Host metrics plus NixOS etcd-backup success textfiles |

Prometheus discovers monitors, rules and probes in every namespace. Native
K3s controller-manager/scheduler/etcd bundled endpoints are not assumed to be
separate scrape targets. NixOS owns image garbage collection and bounded
journald/container logs; no Ubuntu worker-policy DaemonSet remains.

The chart retries transient admission-webhook startup failures. cert-manager
owns its webhook certificate/CA; patch Jobs remain disabled. Kubelet discovery
uses the pinned operator's tested Endpoints workaround as a coordinated setting:
`kubeletEndpointsEnabled=true`, `kubeletEndpointSliceEnabled=false` and
`serviceDiscoveryRole=Endpoints`. Manually managed metric targets retain their
matching Endpoints objects until an operator upgrade passes node replacement
qualification.

Alertmanager groups application/backup failures and clears a failed CronJob
incident when a newer execution succeeds. Forge's deliberate OnDelete rollout
and long isolated restore verifier use their service-specific rules. UniFi AP
telemetry distinguishes missing metrics/scrape failure from ordinary node
targets. Runtime Telegram/Grafana/Matrix credentials stay SOPS-encrypted.

During migration, keep this stage held until its four active data sources have
restored. Continue the old workload Prometheus/Alertmanager data and restore
physical Grafana/Loki data into `services-observability`. Preserve both old
physical Prometheus replica histories as independent archives; do not merge
them into the active 20 GiB TSDB. Preserve all old Alertmanager files and import
still-active missing silences through its API. The complete procedure and
ownership/size changes are in
[DATA-MIGRATION.md](../../../../../docs/migration/DATA-MIGRATION.md).

Restore observability first, verify its CRDs/readiness, then release database
controllers and dependent apps. Single replicas mean Grafana/logs/recent metrics
can be unavailable while a host or RWO volume relocates. Replica-3 Ceph protects
against a host failure; it does not replace an independent history backup.
The application Velero schedules currently exclude `services-observability`.
The migration cold exports preserve current history, and Git recreates rules,
dashboards, routes and encrypted runtime inputs. Ongoing automatic backup of
metrics, Loki history, Grafana runtime changes and silences is not claimed.

With the explicit target cluster access:

```sh
nix run .#matrix-access -- cluster -- kubectl -n flux-system get kustomization observability
nix run .#matrix-access -- cluster -- kubectl -n services-observability get helmreleases,pods,pvc
nix run .#matrix-access -- cluster -- kubectl get prometheusrules,servicemonitors,podmonitors,probes -A
```

Require the HelmReleases and Flux stage Ready, PVCs Bound, host/storage targets
present, Grafana OIDC access, searchable restored logs and a delivered test alert.
NixOS's off-server etcd backups export token/keys with the snapshot and report
`homelab_etcd_backup_last_success_timestamp_seconds`; their schedule and restore
qualification are separate from app/history storage recovery.
