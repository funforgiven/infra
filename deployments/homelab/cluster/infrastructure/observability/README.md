# Observability

kube-prometheus-stack (Prometheus, Alertmanager, Grafana), Loki with Fluent
Bit, and the blackbox exporter. Each runs a single replica: during a node loss
or volume move, dashboards, logs and recent metrics may be briefly
unavailable. Replicated Ceph protects against a host failure, not against
losing the cluster; the volumes are backed up off-site with the rest
([backups](../backups/README.md)). Nothing else in the graph depends on this
stage, so recovery can restore it at any point.

Non-obvious settings:

- Kubelet discovery uses the operator's Endpoints mode
  (`kubeletEndpointsEnabled`, `kubeletEndpointSliceEnabled: false`,
  `serviceDiscoveryRole: Endpoints`) as one coordinated setting; manually
  managed scrape targets keep matching Endpoints objects. Change them together
  and only after testing an operator upgrade.
- The Prometheus Operator CRDs are owned by `components/homelab/monitoring-crds`,
  not by the chart.
- CronJobs with their own failure alerts opt out of the generic job alert with
  the label `monitoring.fahrican.com/dedicated-job-alerts: "true"`; the generic
  rule clears when a newer run succeeds.
- Alerts go to Telegram and, through the Matrix relay, to an encrypted room
  (the Telegram route is being retired, see the Matrix runbook).
- Hosts report etcd backup success through node-exporter textfiles
  (`homelab_etcd_backup_last_success_timestamp_seconds`).

Inspect with `nix run .#cluster-access -- cluster -- kubectl …`.
