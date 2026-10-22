# Monitoring CRDs

The Prometheus Operator CRDs, vendored from the kube-prometheus-stack chart
pinned in `deployments/homelab/cluster/infrastructure/observability`. The
`controllers` stage applies them so every later stage can declare
ServiceMonitors and PrometheusRules before observability itself is running
(and while it is held during recovery). The chart's own CRD installation is
disabled so these files are the only owner.

Re-vendor them from the chart whenever the chart's operator version changes.
Pruning is disabled so removing a CRD here never deletes custom resources.
