# One homelab Kubernetes cluster

The three NixOS hosts run K3s with embedded etcd, Cilium with kube-proxy replacement,
MetalLB, Multus and direct Rook-Ceph CSI. Flux owns the semantic dependency
graph in `waves.yaml`; folder numbering is unnecessary. Independent identity,
DNS, AWS mail and NetBird providers run from the workstation with preserved
state, outside the cluster bootstrap dependency graph.

Application state restores into newly provisioned direct-CSI claims before
releasing reconciliation. Bootstrap `../recovery` rather than this normal root
during migration; it holds Ceph until NVMe reuse is approved, and observability/stateful apps until their data is
ready. Restore observability first so its monitoring CRDs can satisfy database
controller dependencies, then native databases, then dependent applications.

See [architecture](../../../docs/migration/ARCHITECTURE.md),
[inventory](../../../docs/migration/INVENTORY.md),
[data recovery](../../../docs/migration/DATA-MIGRATION.md),
[execution runbook](../../../docs/migration/RUNBOOK.md),
[validation](../../../docs/migration/VALIDATION.md) and
[current preparation status](../../../docs/migration/PROGRESS.md).
No live deployment has been performed by the preparation work.
