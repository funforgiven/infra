# Services OpenStack foundation

This OpenTofu root owns only resources whose provider state does not contain
runtime credentials: the `services` Keystone project and administrator role
assignment, its private network and router, private Magnum flavors, and service
quotas. The runner receives OpenStack credentials from a Kubernetes Secret as
environment variables; they are neither Terraform variables nor outputs.

The Magnum cluster is deliberately excluded. The upstream OpenStack provider's
`openstack_containerinfra_cluster_v1` resource stores the generated kubeconfig,
client certificate, and private key in raw state. The adjacent Git-owned API
reconciler therefore creates and inspects the cluster with an ephemeral
kubeconfig on a memory-backed Kubernetes volume.

Run static validation without cloud credentials:

```console
tofu init -backend=false
tofu validate
```
