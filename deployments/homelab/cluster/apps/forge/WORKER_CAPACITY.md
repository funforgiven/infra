# Linux Actions capacity on the physical cluster

Three NixOS/K3s servers share application and Ceph work. There are no guest
worker flavors, Magnum node groups or Nova host memory reservations. NixOS
labels each physical node `homelab.fahrican.com/ci-node=true`; the retained
Atollion launcher requires that label and prefers pecorino/asiago. Taleggio
remains eligible. Required pod anti-affinity on `kubernetes.io/hostname`
keeps the two Atollion jobs on distinct physical hosts.

Atollion has two bounded Linux slots. Each requests 4 CPUs and 4 GiB memory,
with limits of 6 CPUs and 6 GiB, and a fresh 96 GiB disposable workspace claim.
The `forge-ci` namespace quota includes both slots and the generic qualification
runner: 9 requested CPUs/9 GiB and 16 CPU/16 GiB limits. Check actual application,
Ceph and node memory usage before increasing concurrency; limits do not reserve
memory. CPU requests and the project's `CARGO_BUILD_JOBS` are separate controls.

Drain one physical node at a time only after checking etcd/Ceph quorum, volume
health and available capacity on the other two. Finish or explicitly cancel
active builds, hold launchers, then use normal Kubernetes eviction. Never delete
production data/cache PVCs to clear a drain. Confirm both job slots, artifact
exchange, cache restoration and cleanup after maintenance, then resume launchers.

Windows/macOS native jobs are outside this target. Before restarting an
application workflow, update its required native jobs/status checks through
the application's reviewed change. Linux cross-compilation can remain.

Historical VM capacity and measurements belong to source revision `8d5f130`,
at `deployments/homelab/cloud/services/46-forge/WORKER_CAPACITY.md`. Those
measurements are evidence about the old cloud and do not qualify target node
placement, build duration or resource headroom. Run a fresh Linux workflow and
record actual metrics after migration.
