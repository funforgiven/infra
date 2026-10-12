# Storage snapshots

The CRDs are vendored without changes from kubernetes-csi/external-snapshotter
v8.4.0, commit `f21cb02763e7cd6a7fc84846f106b83119b5371d`. The upstream Apache-2.0
license is retained. Controller RBAC comes from the same revision, excluding
unused group-snapshot permissions; the controller image is pinned by digest.

This matches the existing Magnum-installed Cinder CSI snapshotter. Adding this
controller does not restart Cinder, Forgejo, or runner pods. Snapshots provide
a temporary consistent source for portable file backups; offsite restores
continue to use Velero/Kopia and do not require the original cloud or snapshots.
