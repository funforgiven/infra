# Services OpenStack foundation

This OpenTofu root owns only resources whose provider state does not contain
runtime credentials: the `services` Keystone project and administrator role
assignment, its private network and router, private Magnum flavors, and the
compute, network, block-storage, and load-balancer quotas supported by the
pinned provider. The adjacent single-purpose
`services-share-quota-reconcile-v1` CronJob owns the Manila quota because the
provider exposes share resources but no share-quota resource. It reapplies the
Git-declared limits every six hours and uses the same root-only OpenStack
credential boundary as this controller. The runner receives OpenStack
credentials from a Kubernetes Secret as environment variables; they are
neither Terraform variables nor outputs.

The Magnum cluster is deliberately excluded. The upstream OpenStack provider's
`openstack_containerinfra_cluster_v1` resource stores the generated kubeconfig,
client certificate, and private key in raw state. The adjacent Git-owned API
reconciler therefore creates and inspects the cluster with an ephemeral
kubeconfig on a memory-backed Kubernetes volume.

Control-plane flavors are versioned because Magnum does not permit changing
`master_flavor_id` on an existing cluster. `services.master` remains declared
for the current cluster's recorded Magnum state, while new clusters use the
8 GiB `services.master.v2` flavor. The existing `services-v1` control plane is
rolled onto `services.master.v2` by changing its immutable Cluster API
OpenStackMachineTemplate reference; this must remain a one-time operational
migration rather than a Magnum cluster update.

Run static validation without cloud credentials:

```console
tofu init -backend=false
tofu validate
```
