# Service DNS

This OpenTofu root manages the public Cloudflare records for self-hosted
services and mail.

Application records resolve to the routed-LAN services Gateway at
`10.21.40.122`; that address is not reachable from the public Internet. Mail
records resolve to the retained public address produced by the AWS mail root and
include the Stalwart TLS, autoconfiguration, MX, SPF, DKIM, and DMARC records.

The Cloudflare provider discovers the `fahrican.com` zone by name. Its token is
read from `CLOUDFLARE_API_TOKEN` in the ephemeral controller pod and is not an
OpenTofu variable, output, or state attribute.

Resend verification records are supplied as `resend_records_json` by the
provider reconciler. OpenTofu validates and creates the returned CNAME, MX, and
TXT records; the Resend administration key never enters provider state.

Before accepting a DNS change, review the complete plan and verify:

- the services Gateway still owns `10.21.40.122`;
- private application names resolve to the routed-LAN address;
- mail A, MX, SPF, DKIM, DMARC, and autoconfiguration records match the active
  AWS mail origin; and
- forward and reverse mail DNS agree before enabling or changing the PTR.

Credential rotation and provider reconciliation are documented in the
[service operations guide](../../../../../deployments/homelab/cloud/services/ACTIVATION.md).
