# AWS Stalwart mail platform

Mail runs in `eu-central-1` on one Graviton EC2 instance. OpenTofu manages the
network, instance, database, object storage, monitoring, IAM, and empty secret
containers. NixOS manages the host and Stalwart service.

## Architecture

- A `t4g.micro` EC2 instance runs the signed `mail-aws` NixOS configuration.
  Session Manager is the only administrative path; there is no public SSH
  ingress.
- An encrypted single-AZ PostgreSQL RDS instance stores the Stalwart registry,
  mailbox metadata, and indexes. It has 14-day point-in-time recovery, deletion
  protection, and a final snapshot.
- A private encrypted and versioned S3 bucket stores message bodies and
  attachments. Deleted and overwritten versions are retained for 90 days.
- An Elastic IP provides the stable public address. Reverse DNS is enabled only
  after forward DNS is correct.
- CloudWatch infrastructure and application alarms publish to the independent
  Gmail SNS subscription.
- Daily encrypted Restic backups in Backblaze include a portable Vandelay
  mailbox archive and a PostgreSQL dump. The B2 key is restricted to the mail
  prefix; its values and repository password are enrolled outside OpenTofu.

The EC2 root disk is replaceable. A replacement host reconstructs its local
configuration from the RDS-managed credential and reconnects to the existing
RDS and S3 data. OpenTofu sets `prevent_destroy` on both data stores.

This deployment accepts a maintenance window instead of paying for Multi-AZ
RDS. If the availability requirement changes, enable Multi-AZ RDS before adding
another Stalwart node.

## Credentials

OpenTofu creates Secrets Manager containers but never creates secret versions
or receives database, administrator, mailbox, or Resend values.

- RDS generates and owns its database password.
- The EC2 instance generates the Stalwart administrator and mailbox passwords,
  applies the declared account configuration, and writes those values directly
  to its two secret containers.
- The Resend sending key is enrolled separately. The EC2 role can read it but
  cannot replace it.

Initial AWS enrollment uses two ignored mode-`0600` `AWS_BOOTSTRAP_*` files.
The enrollment tool creates the restricted `fahrican-mail-gitops` identity,
encrypts its new access pair into the mail provisioning SOPS file, verifies the
identity, revokes the temporary key, and then clears the intake files. Neither
pair is passed to OpenTofu or placed in a shell argument.

The provisioning identity is restricted to Frankfurt and the resources tagged
for this mail service. It cannot retrieve secret values or administer KMS keys.
Runtime secret reads and administrator/mailbox writes belong only to the EC2
role.

## Routine checks

After an infrastructure or host change, verify:

- the EC2 bootstrap marker and Stalwart unit;
- RDS connectivity;
- the S3 read/write probe;
- all declared CloudWatch alarms;
- the SNS subscription; and
- public JMAP discovery, authenticated mail/submission methods, MX, and TLS hostname behavior.

For DNS changes, also verify DKIM, SPF, DMARC, autoconfiguration records, and
the EIP forward/reverse mapping.

Rotate the domain-scoped Resend key with:

```sh
nix run .#reconcile-services-resend -- apply
nix run .#publish-aws-mail-resend
```

Wait for `stalwart-resend-reconcile` to converge, then send an independent test
message through the public MX and confirm it over authenticated JMAP, including
a downloaded attachment.

## Recovery

RDS and S3 must be restored to a compatible point in time:

1. Restore RDS to the selected timestamp.
2. Restore or remove later S3 delete markers required by that database state.
3. Attach an isolated replacement EC2 instance to the restored stores.
4. Compare the non-secret schema, mailbox counts, representative messages, and
   object availability.
5. Only after the isolated check succeeds, plan the production recovery.

Never test a restore against the production MX or by mutating the production
bucket.

For a logical database drill, temporarily enable
`enable_restore_qualification` in the deployment root. OpenTofu creates a
private disposable RDS target and permits only the mail instance role to access
its managed credential. Stream a custom-format `pg_dump` into the target and
compare non-secret schema and row counts. Disable the option afterward and
require a no-change plan once OpenTofu removes the temporary database and
security group.

Host replacement waits for Stalwart on the temporary instance address before
moving the retained EIP. A failed bootstrap leaves the old host serving mail.
Public hostname and certificate checks run after cutover.

## Application checks and independent backups

The `mail-operations` command and corresponding systemd services provide:

| Service | Schedule | Success condition |
| --- | --- | --- |
| `mail-health` | Every five minutes | Stalwart active, valid HTTPS certificate, authenticated JMAP inbox and sending identity, SMTP STARTTLS, readable queue |
| `mail-canary` | Twice per hour | External Resend delivery reaches the public MX and the dedicated JMAP inbox with an intact attachment |
| `mail-backup` | Daily, 02:10 UTC | Native mailbox export and database dump validate and upload to encrypted offsite storage |
| `mail-restore-check` | Sunday, 04:10 UTC | Latest offsite snapshot downloads, hashes match, SQLite integrity passes, PostgreSQL archive is readable |

All four checks also run shortly after boot. Missing success records and missing
CloudWatch samples alert; a failed command never advances the success timestamp.
Queue age excludes Stalwart's intentional initial delay for automatic reports
that have never been attempted. An overdue scheduled report is measured from its
earliest recipient delivery time; failed retries and ordinary mail retain their
full age. All queued reports still contribute to the queue-size alarm.
The canary has a separate 100 MiB account and deletes only its verified messages.
It uses 48 messages per day from the Resend allowance. Failed or junk delivery is
an alarm condition. The homelab blackbox probe separately checks JMAP discovery,
advertised mail and submission capabilities, and the HTTPS certificate. The
homelab ISP blocks outbound port 25, so public inbound delivery is tested by the external canary.

Backup retention is 14 daily, eight weekly, and 12 monthly snapshots. Weekly
verification serializes with backups before pruning. B2 lifecycle retention of
hidden object versions is 30 days. This is an independent encrypted backup,
not immutable storage: the runtime B2 key can delete objects in its mail prefix.
Keep the SOPS recovery identity available outside AWS; losing the Restic password
makes the encrypted repository unrecoverable.

Publish an enrolled backup credential without displaying it:

```sh
nix run .#aws-mail-credentials -- backup
```

On the mail host, run a backup or repeat the integrity restore check with:

```sh
sudo systemctl start mail-backup.service
sudo systemctl start mail-restore-check.service
sudo systemctl start mail-health.service
```

The portable archive covers `fahrican@fahrican.com`, including supported JMAP
mail, contacts, calendars, files and scripts. Add other real mailboxes to the
backup implementation before using them; the synthetic account is disposable.
The PostgreSQL dump preserves registry and metadata, but message blobs for that
dump still require the matching S3 versions. The independent portable archive
contains its own blobs. Downloading and validating it does not itself prove a
working mailbox restore: rehearse `vandelay export` into a fresh isolated
Stalwart instance and compare messages and attachments before a full migration.
Never run an unreviewed import or `--prune` against the live account.

## Security and migration boundary

Clients use JMAP over HTTPS for both reading and sending. IMAP and SMTP client
submission listeners are disabled; both firewalls permit only inbound SMTP
(port 25) and HTTPS (port 443). Incoming server-to-server SMTP supports STARTTLS
and does not advertise AUTH. Outbound Resend delivery still uses implicit TLS
on port 465 with certificate validation. The owner mailbox receives `postmaster`, `abuse`, `dmarc`, and `tls-reports` aliases. MTA-STS uses
`enforce` with a seven-day policy lifetime; DNS also advertises SMTP TLS reports.
The server release is pinned to the verified upstream 0.16.24 ARM artifact.

This remains one EC2 node and single-AZ RDS, with daily independent backups.
It accepts maintenance downtime and up to 24 hours of loss in an independent
recovery; AWS PITR and versioned blobs provide a more recent same-provider path.
Keep Gmail available through a staged migration, verify real client behavior,
and enroll administrator MFA before retiring the old mailbox. The current
reconcilers authenticate using the managed administrator credential: prepare and
verify a separate app credential for them before making that login require MFA.
Mailbox MFA likewise needs an app credential for the scheduled JMAP export.
This deployment does not copy Gmail history or alter the Gmail account.

## Isolated mailbox restore rehearsal

`mail-restore-drill` is a separately built operator tool. Download the selected
Restic snapshot into a root-only temporary directory, then build this repository's
tool on the mail host before entering the isolated network namespace:

```sh
drill="$(nix build --no-link --print-out-paths .#mail-restore-drill)"
stalwart_binary="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' /etc/systemd/system/stalwart.service)"
sudo systemd-run --wait --pipe --collect \
  --property=PrivateNetwork=yes --property=RuntimeMaxSec=1h \
  "$drill/bin/mail-restore-drill" /path/to/restored/fahrican.sqlite "$stalwart_binary"
```

The tool refuses the host network namespace. It initializes disposable SQLite
storage, restores into a fresh Stalwart account, exports that account again, and
compares every blob byte, message date, keyword, mailbox membership, and folder
hierarchy. It removes the temporary server and store afterward. The restored
identity may coexist with the target's automatically created default identity;
mail comparison does not depend on identity counts. No production database or
blob store is supplied to the isolated server. The rehearsal requires at least
three times the archive size plus 5 GiB free for its temporary copies and SQLite
journals; size staging storage for the imported mailbox before a large rehearsal.

Qualification on 2026-10-02 restored the current seven-message mailbox into
Stalwart 0.16.24 and verified seven blobs and five folders. The import/export
phase took 36 seconds for this small sample; this is not a recovery-time estimate
for a full Gmail archive. An independent Resend-to-MX inbound test passed, and a
Stalwart-to-Gmail message reached the inbox with an attachment and Gmail reporting
SPF, DKIM, and DMARC passes. Re-run the rehearsal after importing Gmail history.

The JMAP qualification also verified attachment upload, draft import,
`EmailSubmission/set`, and live Email state-change events over the advertised
server-sent event endpoint. The JMAP-submitted message arrived in the owner
Gmail inbox with its attachment.

## Client connection settings

| Setting | Value |
| --- | --- |
| Username | `fahrican@fahrican.com` |
| Server | `https://mail.fahrican.com` |
| JMAP discovery / session | `https://mail.fahrican.com/.well-known/jmap` |
| JMAP API | `https://mail.fahrican.com/jmap/` (use the discovered `apiUrl`) |
| Sending | JMAP `EmailSubmission/set` over HTTPS |
| Account web interface (VPN) | `https://mail-admin.fahrican.com/account` |
| Administration (VPN) | `https://mail-admin.fahrican.com/admin` |

Clients discover upload, download, and push URLs from the authenticated JMAP
session. They need no IMAP or SMTP client settings. Use the mailbox credential
(or a separately enrolled app credential), not the administrator login.

The mailbox and administrator credentials remain in their existing AWS Secrets
Manager containers; do not place them in Git, tickets, or command arguments.


## Private administration

Connect the existing `wg-admin` VPN before opening the administration or account
interface. `mail-admin.fahrican.com` resolves to the existing private services
Gateway, `10.21.40.122`; its Envoy authorization policy permits only
`10.21.91.0/24`. Existing split-tunnel client routes already cover this address.
Even the trusted LAN is denied when it is not using the VPN. Public JMAP and
SMTP continue to use `mail.fahrican.com` without the VPN.

The Gateway terminates HTTPS using its DNS-validated certificate and reaches the
mail instance through WireGuard. The mail backend peer is `10.21.91.3/32` and
accepts only the services router's `10.21.40.154/32` source on port 8080. That
port is bound to the tunnel address and permitted only on the tunnel interface;
AWS still admits only public TCP 25 and 443. Router rules forbid this backend
peer from initiating connections to either the router or other homelab services.
The WAN endpoint, peer public keys, and backend source address are declared in
`deployments/homelab/cloud/mail-admin-vpn.json`; update both deployment and
RouterOS inventory if those network assignments change.

The private proxy reaches Stalwart on loopback port 8081. Only discovery responses
have their public origin rewritten for the private UI; JMAP data responses and
mail content are forwarded unchanged. Public `/admin`, `/account`, and management `/api`
paths return 404. The `/api/auth` and `/api/discover` login helpers remain public
so normal JMAP OAuth clients can sign in. Administration shares JMAP with mail, so path restrictions alone
are insufficient: all credentials on built-in administrator accounts are also
restricted to loopback IPs, including cached Basic and OAuth authentication.
The reconciler updates credential IP restrictions without replacing passwords,
MFA enrollment, or existing app/API keys. Any newly created administrator or
administrator credential must receive the same restriction before use; run
`systemctl start mail-reconcile` locally after such changes. Public mail users
keep their normal JMAP access.

Local maintenance uses `http://127.0.0.1:8081` and remains available if the VPN is
down. AWS Systems Manager is the recovery path for the host. Tunnel private and
preshared keys are stored in `secrets/mail-vpn.yaml` under SOPS and in the dedicated
`fahrican/stalwart/vpn` AWS secret, outside Terraform state. To republish the
credential after restoring its secret container, use the scoped mail provisioning
environment and stream `sops --decrypt --output-type json secrets/mail-vpn.yaml`
into `aws --region eu-central-1 secretsmanager put-secret-value --secret-id
fahrican/stalwart/vpn --secret-string file:///dev/stdin`; discard the returned
version metadata. The router receives only the preshared key through its sops-nix
runtime file. Restart `wg-quick-wg-mail` after an intentional key rotation.

Independent homelab probes check every minute that the public admin and schema
paths return 404 and that the private panel returns 403 without a VPN source.
An access restriction failure raises an alert after five minutes. Replacement
instances must serve public JMAP and MTA-STS and reject the public panel before
the retained mail address can move to them.
