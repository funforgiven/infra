# Service DNS

This OpenTofu root manages the public Cloudflare records for self-hosted
services and mail.

Application records resolve to the routed-LAN services Gateway at
`10.21.40.122`; that address is not reachable from the public Internet. Mail
records resolve to the EIP output of the AWS mail root and
include the Stalwart TLS, autoconfiguration, MX, SPF, DKIM, and DMARC records.

Set `mail_enabled = false` when pausing AWS mail. The root removes its public
mail A records, publishes Null MX (`0 .`), removes MTA-STS/TLS-reporting records
and changes the apex SPF to `v=spf1 -all`. Private services, Matrix, NetBird,
DKIM and Resend verification records remain. Apply this before releasing the
AWS EIP; incoming mail will be rejected while paused. `mail_ipv4_address` may
be omitted while paused. On resume, enable mail with the new EIP only after the
restored host is verified. See the
[mail pause procedure](../../services/mail-aws/README.md#pause-and-resume).

The Cloudflare provider discovers the `fahrican.com` zone by name. Its token is
read from `CLOUDFLARE_API_TOKEN` in the private workstation provider environment and is not an
OpenTofu variable, output, or state attribute.

Resend verification records are supplied as `resend_records_json` from the
reviewed enrollment inputs. OpenTofu validates and creates the returned CNAME, MX, and
TXT records; the Resend administration key never enters provider state.

Before accepting a DNS change, review the complete plan and verify:

- the services Gateway still owns `10.21.40.122`;
- private application names resolve to the routed-LAN address;
- mail A, MX, SPF, DKIM, DMARC, and autoconfiguration records match the active
  AWS mail origin; and
- forward and reverse mail DNS agree before enabling or changing the PTR.

Credential rotation and provider reconciliation are documented in the
[service operations guide](../../../../deployments/homelab/credentials/README.md).
