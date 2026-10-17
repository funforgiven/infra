# Storage snapshots

The CRDs are vendored without changes from kubernetes-csi/external-snapshotter
v8.4.0, commit `f21cb02763e7cd6a7fc84846f106b83119b5371d`, under the upstream
Apache-2.0 license. Controller RBAC comes from the same revision, excluding
unused group-snapshot permissions; the controller image is pinned by digest.
