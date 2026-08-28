# Service and API ingress

The active Flux configuration installs cert-manager, Envoy Gateway, and
MetalLB, then creates two private Envoy gateways. It does not publish public DNS
records.

| Address | Service | L2 announcer |
| --- | --- | --- |
| `10.21.20.129` | private `cloud.fahrican.com` DNS | Cilium |
| `10.21.20.130` | OpenStack APIs | MetalLB |
| `10.21.20.131` | dashboard, Grafana, and ZITADEL | MetalLB |

MetalLB advertises the gateway addresses on `bond0.20` from control-plane
nodes. Its pools and the Cilium DNS pool select different Services, preventing
both controllers from announcing the same address. All three load-balanced
Services use `externalTrafficPolicy: Cluster`, so the announcing node can
forward traffic to a healthy backend elsewhere in the cluster.

The private and management gateways each run two Envoy replicas with a
one-replica disruption budget. HTTP redirects to HTTPS. Routes may attach only
from namespaces labelled `gateway.fahrican.com/private: allowed` or
`gateway.fahrican.com/management: allowed` for the corresponding gateway.

cert-manager obtains Let's Encrypt certificates through Cloudflare DNS-01. It
uses Cloudflare's public recursive resolvers for self-checks so the private
split-horizon zone cannot hide temporary ACME records. The SOPS-encrypted token
is used only for DNS-01 records and does not publish service endpoints. A
short-lived self-signed certificate exercises certificate issuance before the
ACME issuer and gateways are reconciled.

The reconciled paths and readiness checks are defined in
[`../20-gitops/waves.yaml`](../20-gitops/waves.yaml). Controller images and
charts are pinned in the manifests that deploy them.

## Internal DNS failover

MetalLB is installed for the gateway addresses, while its optional
`10.21.20.129` pool remains inactive. Move private DNS from Cilium to MetalLB in
separate commits so there is a period with no announcer and never a period with
two.

1. Change the `wave37-service-network` path to
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/withdraw-service-network`.
   Wait for the Cilium L2 lease to disappear and confirm that repeated ARP
   probes receive no reply.
2. Change the same path to
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/metallb-service-network`.
   This replaces the Cilium-class Service with a separately named
   MetalLB-class Service because `loadBalancerClass` is immutable. Confirm that
   all three CoreDNS endpoints are ready and that `.129` still has no announcer.
3. Change `wave38-metallb-fallback-controller` from
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/inactive`
   to
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/active-internal-dns`.
   Confirm one MetalLB `ServiceL2Status`, one ARP MAC, no Cilium lease, and
   successful direct and RouterOS-forwarded UDP and TCP DNS queries.

Stop if Cilium and MetalLB overlap, more than one MAC answers ARP, MetalLB
reports multiple or stale statuses, CoreDNS lacks ready endpoints, or either
DNS transport fails.

To restore Cilium, reverse the transition in separate commits:

1. Return `wave38-metallb-fallback-controller` to
   `metallb-fallback/inactive` and wait until `.129` has no announcer.
2. Return `wave37-service-network` to
   `metallb-fallback/withdraw-service-network`; wait until the MetalLB Service
   is pruned and the Cilium Service exists without an L2 lease.
3. Return `wave37-service-network` to
   `./deployments/homelab/cloud/undercloud/37-service-network`. Confirm one
   Cilium lease, one ARP MAC, no MetalLB status, and successful UDP and TCP DNS
   queries.

## Gateway announcer changes

There is no ready-to-apply Cilium transition for `.130` or `.131`. The current
Cilium `/31` pool is disabled, while one MetalLB pool and advertisement cover
both gateway addresses. Do not change a generated Envoy Service directly.

Model any announcer change as separate Git paths that withdraw MetalLB before
enabling Cilium and preserve the gateway that is not being moved.
`loadBalancerClass` is immutable, so the affected Envoy Service must be
recreated. Stop if both controllers answer for an address or if more than one
MAC answers ARP.
