# Service DNS

This OpenTofu root owns the deliberately small public Cloudflare record set for
the self-hosted services. The application A records resolve to 10.21.40.122,
which is routed provider-LAN space and is intentionally unreachable from the
public Internet. The mail records resolve to the stable Hetzner primary IPv4.

The Cloudflare provider reads its token from CLOUDFLARE_API_TOKEN in the
ephemeral controller pod. The token is sourced directly from the existing
cert-manager cloudflare-dns01 Secret and never becomes a variable, output, plan
value, or OpenTofu state attribute. The zone ID is treated as sensitive even
though it is not authentication material.

Resend domain-verification records are not guessed here. A later pinned API
reconciler must read Resend's exact required records and manage those values
without placing the Resend administration key in OpenTofu state.

Activation order:

1. Confirm 10.21.40.122 is reserved by the services Envoy LoadBalancer.
2. Provision and qualify the mail edge, then copy its stable IPv4 into wave85.
3. Replace the zone-ID sentinel and inspect the complete OpenTofu plan.
4. Resume the Terraform object, then the outer Flux wave.
5. Verify LAN-only application resolution, public mail resolution, MX, and
   reverse DNS before accepting mail.
