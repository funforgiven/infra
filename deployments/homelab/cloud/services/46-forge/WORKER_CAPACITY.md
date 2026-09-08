# Actions worker capacity

The services cluster retains three worker VMs: one `services.worker` VM
(4 vCPU, 12 GiB RAM) in `default-worker` and two `services.worker.v2` VMs
(8 vCPU, 12 GiB RAM each) in `cpu-workers`. The worker RAM allocation stays
at 36 GiB. The three control-plane VMs and native runner VM sizes are separate.

Atollion has two Linux job slots. Each requests 4 CPUs and 4 GiB RAM, with
limits of 6 CPUs and 6 GiB RAM. Required node affinity selects `cpu-workers`
and the v2 flavor; pod anti-affinity keeps the slots on different VMs. The
`services-ci-workers` Nova server group additionally enforces hard physical
host anti-affinity. Different Kubernetes node names alone do not prove that
jobs run on different physical machines.

The `forge-ci` quota admits both slots and the generic qualification runner:
9 requested CPUs and 16 CPU limits, with the existing 9 GiB request and 16 GiB
limit memory budgets. A cross-manifest test checks this budget against the
launcher concurrency and actual pod resources. Check node memory requests too;
Kubernetes does not automatically rebalance existing services onto a new node.

The cloud reconciler labels these nodes with the verified Nova hypervisor
under the NodeRestriction-protected
`fahrican.com.node-restriction.kubernetes.io/hypervisor` prefix. Scheduling
prefers `pecorino` (i9-14900K) and `asiago` (Ryzen 9 9900X); `taleggio`
(i5-13600K) remains eligible. These labels express preference, not isolation;
the Nova group enforces separation even before an optional label is applied.

On 2026-09-09, the 14900K host had less than 12 GiB of schedulable RAM. Keep
the 32 GiB per-host Nova reservation and RAM allocation ratio of 1.0. Do not
trade away host memory headroom to satisfy a CPU preference. Revisit placement
when other VM allocations change, checking both Nova allocations and observed
host memory/CPU peaks. Windows 11 shares `asiago`; the macOS outer VM shares
`taleggio`. Account for them when increasing concurrent jobs or CPU limits.

CPU capacity and Cargo concurrency are separate controls. The application
workflow owns `CARGO_BUILD_JOBS`; changing that setting requires its normal
protected PR review and validation. Cached compilation is only part of job
duration: serialized tests, native VM startup, archive transfer and validation
also contribute. Measure an actual warm run before promising a duration.

## Replacing the original workers

The pinned Magnum node-group API cannot update `flavor_id`, and Nova flavors
are immutable. Use replacement workers, preserving the original flavor. The
pinned `openstack-cluster` chart 0.27.0 rejects a node group with zero machines,
so retain one original worker. Do not bypass Magnum by modifying its database
or a rendered machine template's flavor.

1. Apply the additive OpenTofu flavor and Nova server group. Verify project
   ownership, 8 vCPU/12 GiB and hard anti-affinity. Roll out the hash-guarded
   Magnum driver transform and verify all API/conductor replicas before using
   the `server_group_id` node-group label.
2. Temporarily suspend `wave82-services-cluster` reconciliation and its
   `openstack/services-cluster-reconcile-v1` CronJob. During the service move,
   suspend `services-forge` and its Linux/native launchers. Record prior
   suspension states. Existing jobs must finish or be explicitly cancelled;
   do not drain active builders, backups or native VM brokers.
3. Record node/provider identities, retained Forgejo/cache PVC and PV IDs,
   disruption budgets and service readiness. Select the old `asiago` worker
   first so the new worker reuses its RAM without consuming the memory needed
   for a Windows job. Drain normally, respecting disruption budgets and
   waiting for volumes to detach. Never force a drain or remove a cache PVC.
   A completed standalone restore-verification pod can block normal eviction.
   Verify its persisted `.database-verified` and `.qualified` checksums match,
   save its specification and proof, then evict that exact completed pod with
   a UID precondition. Retain both restore PVCs; the monthly qualification
   creates its next isolated test pod from a fresh restore. Check active
   builders, backups and jobs on the selected node; an unrelated short
   monitoring job elsewhere need not block the drain.
4. Annotate its CAPI Machine with `cluster.x-k8s.io/delete-machine=yes`, then
   use `openstack coe cluster resize services-v1 2 --nodegroup default-worker`.
   Confirm that the selected VM was removed. Magnum's pinned driver ignores
   `nodes_to_remove`; use the documented CAPI deletion priority, not that CLI
   option. Verify the other workers remain healthy.
5. Create `cpu-workers` with `services.worker.v2`, one node, and
   `--labels server_group_id=<services-ci-workers UUID>`. Wait for a Ready
   node; verify its Nova flavor, server-group membership and physical host.
6. Drain one old `taleggio` worker, preferring to retain the worker now hosting
   Forgejo. Annotate its Machine and resize `default-worker` from two to one.
   After its VM is removed, resize `cpu-workers` from one to two. Require two
   Ready v2 nodes on distinct physical hosts before enabling the larger jobs.
7. Deploy the reconciler's final one-plus-two topology and the runner resource
   settings. Verify retained volume identities, Forgejo/OIDC routes, cache
   health, node readiness and physical host headroom. Resume the recorded
   Flux/CronJob states; temporary suspension is not desired configuration.
   Forgejo's backup sidecar takes a quiesced archive shortly after startup,
   temporarily withdrawing its HTTP endpoint. Let that backup complete and
   verify authenticated API/Git access before publishing application changes.
8. Verify a real job uses the new resources and restores its compatible cache.
   Preserve timing and placement evidence. Do not invalidate caches simply
   because CPU allocation changed.

The September replacement needed Prometheus and the AudioMuse frontend moved
off the first new worker to leave room for its 4 GiB CI request. Both controller
replacements became Ready and the temporarily cordoned worker was restored to
scheduling. AudioMuse exposed a pre-existing malformed internal configuration
override on restart; see the [targeted recovery](../40-media/README.md#audiomuse-startup-recovery).

If a replacement fails, retain the remaining healthy workers and suspension
records, diagnose through Magnum/CAPI/Nova, and recover via those controllers.
Restore the original node count only when capacity and physical placement
allow it. Never leave a silent permanent reconciliation suspension.

The [CAPI annotation reference](https://cluster-api.sigs.k8s.io/reference/api/labels-and-annotations)
documents deletion priority. The local driver transform asserts its pinned
input hash and forwards the optional server-group label to the chart's
`nodeGroups[].serverGroupId` field; absent/null labels preserve prior behavior.
