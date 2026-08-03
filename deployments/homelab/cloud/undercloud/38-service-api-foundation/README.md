# Service and API foundation

This wave installs the private service-entry layer used by OpenStack and later
platform services. It owns cert-manager, Envoy Gateway, the private Envoy
Gateway at `10.21.20.130`, and a dormant MetalLB controller. It does not publish
public DNS records or create a Cloudflare credential.

## Normal operation

Cilium remains the load-balancer IPAM and L2-announcement implementation.
Internal CoreDNS uses `10.21.20.129`; Envoy Gateway uses `10.21.20.130`. Both
addresses live on VLAN 20 and use `externalTrafficPolicy: Cluster` so an L2
holder can forward to a healthy backend on any node.

cert-manager is ready only after its permanent short-lived certificate canary
has issued a certificate. Envoy Gateway is ready only when its `GatewayClass`
is accepted and the private `Gateway` is both accepted and programmed at
`10.21.20.130`. The MetalLB release is continuously reconciled but has no
address pool or advertisement in normal operation.

Public Cloudflare DNS remains an allow-list. No private Service or Gateway is
eligible for automatic public publication. DNS-01 authorization, when added,
will grant access only to ACME challenge records and will not change that
publication boundary.

## Cilium L2 rollback

MetalLB is a rollback implementation, not a second active announcer. Qualify
the rollback with the internal DNS VIP before relying on it for Envoy. Every
transition uses separate commits and stops at a no-owner boundary; never
combine the stages into one change.

Normal paths in `../20-gitops/waves.yaml` are:

- `wave37-service-network` →
  `./deployments/homelab/cloud/undercloud/37-service-network`;
- `wave38-metallb-fallback-controller` →
  `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/inactive`.

To move `10.21.20.129` to MetalLB:

1. Change only `wave37-service-network` to
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/withdraw-service-network`.
   Wait until the Cilium L2 lease is gone and repeated ARP probes receive no
   reply.
2. Change that path to
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/metallb-service-network`.
   This replaces the classed Cilium Service with a separately named, classed
   MetalLB Service, avoiding an update to the immutable `loadBalancerClass`.
   Require three ready CoreDNS endpoints and no owner for `.129`.
3. Change `wave38-metallb-fallback-controller` from
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/inactive`
   to
   `./deployments/homelab/cloud/undercloud/38-service-api-foundation/metallb-fallback/active-internal-dns`.
   Require one MetalLB `ServiceL2Status`, one ARP MAC, no Cilium lease for
   `.129`, and successful direct and RouterOS-forwarded UDP and TCP queries.

Abort on overlapping Cilium and MetalLB ownership, multiple ARP MACs, more than
one MetalLB status, a stale MetalLB configuration, missing endpoints, or a DNS
failure.

Restore Cilium in reverse order:

1. Return the MetalLB path to `metallb-fallback/inactive` and prove `.129` has
   no owner. Use the complete inactive path shown above.
2. Return the service-network path to
   the complete `withdraw-service-network` path shown above; wait for the
   MetalLB Service to be pruned and the Cilium Service to exist without an L2
   lease.
3. Return the service-network path to the complete normal Wave 37 path shown
   above; require one Cilium lease and ARP MAC, no MetalLB status, and
   successful UDP/TCP queries.

If Cilium must also be withdrawn from `10.21.20.130`, keep the `Gateway`,
`GatewayClass`, and HTTPRoutes unchanged. Only the EnvoyProxy Service template,
the mutually exclusive IP pool, and the L2 advertisement change. Apply the
same withdraw/no-owner/activate sequence and recreate the generated Envoy
Service if its immutable load-balancer class changes. This transition must be
qualified before production traffic uses the MetalLB path.
