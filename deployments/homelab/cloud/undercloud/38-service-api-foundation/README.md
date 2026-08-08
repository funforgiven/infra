# Service and API foundation

This wave installs the private service-entry layer used by OpenStack and later
platform services. It owns cert-manager, Envoy Gateway, the OpenStack API
Gateway at `10.21.20.130`, the management UI Gateway at `10.21.20.131`, and
MetalLB. It does not publish public DNS records.

## L2 ownership

Cilium remains the Kubernetes CNI and owns the internal CoreDNS VIP at
`10.21.20.129`. MetalLB owns the two Envoy Gateway VIPs at `10.21.20.130` and
`10.21.20.131`. The address pools and Service selectors are disjoint, so an
address can never have both announcers. The Services use
`externalTrafficPolicy: Cluster` so an L2 holder can forward to a healthy
backend on any node.

cert-manager is ready only after its permanent short-lived certificate canary
has issued a certificate. The Cloudflare token is scoped to DNS-01 validation;
it does not create endpoint records. Envoy Gateway is ready only when each
`GatewayClass` is accepted and each `Gateway` is accepted and programmed at its
declared VIP. MetalLB uses the `private-gateway` pool and advertises only on
`bond0.20` from control-plane nodes.

DNS-01 self-checks use Cloudflare's public recursive resolvers so the private
split-horizon zone cannot hide temporary ACME TXT records from cert-manager.

Public Cloudflare DNS remains an allow-list. No private Service or Gateway is
eligible for automatic public publication. DNS-01 authorization grants access
only for ACME challenge records and does not change that publication boundary.

## Changing L2 ownership

MetalLB is the qualified rollback implementation, not a second owner for the
same VIP. Every ownership transition uses separate commits and stops at a
no-owner boundary; never combine the stages into one change.

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

To return `10.21.20.130` to Cilium, keep the `Gateway`, `GatewayClass`, and
HTTPRoutes unchanged. First remove the MetalLB advertisement and verify that
its `ServiceL2Status` and ARP owner are gone. Then enable the Cilium pool,
restore the Cilium annotation and L2 selector in the EnvoyProxy Service
template, and recreate the generated Envoy Service because
`loadBalancerClass` is immutable. Accept the change only after every node can
reach the VIP and exactly one Cilium lease and ARP MAC exist.
