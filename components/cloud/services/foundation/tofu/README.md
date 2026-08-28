# Services foundation

This OpenTofu root creates the OpenStack resources shared by the services
cluster and the persistent service hosts.

The [deployment controller](../../../../../deployments/homelab/cloud/undercloud/81-services-foundation/tofu.yaml)
reads the signed `main` branch every 10 minutes, applies plans automatically,
and writes the three outputs below to the `services-foundation-outputs`
Kubernetes Secret. Deleting the controller does not destroy its OpenStack
resources.

OpenStack credentials come from the `magnum-keystone-admin` Kubernetes Secret
as environment variables. They are not module inputs or outputs.

## Resources

The root manages:

- the `services` Keystone project and the `admin` user's role assignment;
- three private flavors available only to that project:
  `services.master` (2 vCPU, 4 GiB RAM, 20 GiB disk),
  `services.master.v2` (2 vCPU, 8 GiB RAM, 20 GiB disk), and
  `services.worker` (4 vCPU, 12 GiB RAM, 40 GiB disk);
- the `services` Neutron network with MTU 1442;
- the `services-v4` subnet, `192.168.80.0/24`, with gateway
  `192.168.80.1`, DHCP range `192.168.80.20`–`192.168.80.239`, and DNS
  server `10.21.40.1`;
- a router from the services network to the external `public` network, with
  SNAT enabled; and
- compute, network, block-storage, and load-balancer quotas for the project.

The declared quotas are:

| Service | Limits |
| --- | --- |
| Compute | 48 cores, 16 instances, 131072 MiB RAM, 20 key pairs, 16 server groups, 32 group members |
| Network | 16 floating IPs, 8 networks, 400 ports, 16 RBAC policies, 8 routers, 64 security groups, 400 rules, 16 subnets, 4 subnet pools |
| Block storage | 100 volumes, 100 snapshots, 3000 GiB total, 1000 GiB per volume, 30 backups, 1000 GiB of backups, 20 groups |
| Load balancer | 16 load balancers, 64 listeners, 256 members, 64 pools, 64 health monitors |

Manila share quotas are not in this OpenTofu state because the pinned
OpenStack provider has no share-quota resource. The adjacent
[`services-share-quota-reconcile-v1` CronJob](../../../../../deployments/homelab/cloud/undercloud/81-services-foundation/share-quota.yaml)
runs every six hours and sets 50 shares, 50 snapshots, 10 share networks,
2048 GiB total share and snapshot capacity, and 2048 GiB per share.

## Inputs and outputs

The root has no input variables.

| Output | Meaning |
| --- | --- |
| `project_id` | Keystone ID of the `services` project |
| `network_id` | Neutron ID of the `services` network |
| `subnet_id` | Neutron ID of `services-v4` |

## What is not managed here

The Magnum cluster is managed by the services-cluster reconciler. It is not an
OpenTofu resource because the OpenStack provider stores the generated
kubeconfig, client certificate, and private key in unencrypted state. The
reconciler instead generates the kubeconfig on a memory-backed volume for each
run.

Flavor IDs are referenced by Magnum cluster templates and machines. Review
flavor removal or replacement carefully; changing CPU, memory, or disk values
can replace a flavor that an existing cluster still references. Network,
subnet, router, and project changes can also replace shared infrastructure.

## Validate

Static validation does not require OpenStack credentials:

```console
tofu init -backend=false
tofu validate
```
