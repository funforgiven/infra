# One homelab Kubernetes cluster

The three NixOS hosts run K3s with embedded etcd, Cilium with kube-proxy replacement,
MetalLB, Multus and direct Rook-Ceph CSI. Flux owns the semantic dependency
graph in [`waves/stages.yaml`](waves/stages.yaml); folder numbering is unnecessary.
Shared settings for every stage are set once in
[`waves/kustomization.yaml`](waves/kustomization.yaml). Identity, DNS, AWS mail
and NetBird providers run from the workstation, outside the cluster bootstrap
dependency graph.

Application state restores into newly provisioned direct-CSI claims before
releasing reconciliation. To rebuild from backup, bootstrap `../recovery`, which
holds Ceph, observability and stateful apps until their data is restored. Restore
observability first so its monitoring CRDs can satisfy database controller
dependencies, then native databases, then dependent applications.

See [architecture](../../../docs/ARCHITECTURE.md).
