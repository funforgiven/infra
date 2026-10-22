# AWS Stalwart mail

Mail runs in `eu-central-1` on one Graviton EC2 instance (NixOS
`mail-aws`), single-AZ RDS PostgreSQL (registry and metadata) and a versioned
S3 bucket (blobs). OpenTofu (`components/homelab/providers/mail-aws`) owns the
AWS resources; NixOS owns the host. Clients use JMAP over HTTPS only.

## Design decisions

- One node and single-AZ RDS: a maintenance window is accepted instead of
  Multi-AZ cost. Enable Multi-AZ before adding a second Stalwart node.
- The instance is never replaced. Host changes deploy in place with NixOS;
  user data only bootstraps a deliberately recreated instance (from
  `bootstrap_revision`). RDS, S3, the EIP and the secrets have `prevent_destroy`.
- Session Manager is the administration path; there is no SSH ingress.
- The panel certificate is issued with Cloudflare DNS-01 on the host; a new
  root volume simply reissues it.

## Credentials

RDS generates its password. The instance generates the administrator,
mailbox and canary passwords and writes them to Secrets Manager. The Resend
sending key, the B2 backup key with its Restic password, and the WireGuard
server keys plus Cloudflare DNS token are canonical in SOPS; `secrets.tf`
publishes them as write-only values (never in state) whenever their SOPS files
change. Apply `mail-aws` after rotating any of them.

The `fahrican-mail-gitops` user (`providers/aws-iam`) runs this root. It is
limited to Frankfurt and this service, but it is not a secret boundary: it can
read and write the resend, backup and vpn secrets, and `ssm:SendCommand` on the
mail instance gives root there, which reads every runtime secret. It can only
edit the instance and Matrix-probe roles while their permission boundaries are
attached, and cannot change its own policy or those boundaries.

## Checks and backups

`mail-health` (every 5 min), `mail-canary` (twice hourly, external Resend
delivery to the public MX), `mail-backup` (daily) and `mail-restore-check`
(weekly) run on the host; CloudWatch alarms on missing success samples and
publish to SNS. Backups are a portable Vandelay archive of
`fahrican@fahrican.com` plus a `pg_dump`, in Restic under
`services/hosts/mail-aws/` in Backblaze. The B2 key can delete in that prefix,
so this is off-provider, not immutable. Losing the Restic password (SOPS)
makes the repository unrecoverable. Add any new real mailbox to `operations.py`.

Initialize a new repository once from the workstation:
`restic -r s3:https://s3.us-west-004.backblazeb2.com/fahrican-cloud-recovery/services/hosts/mail-aws init`
with the backup key and password in the environment.

## Recovery

RDS and S3 must be restored to a compatible point in time:

1. Restore RDS (14-day PITR) to the chosen timestamp.
2. Restore or remove later S3 delete markers the database still references
   (noncurrent versions are kept 90 days).
3. Attach an isolated replacement instance to the restored stores and compare
   schema, mailbox counts, representative messages and blobs.
4. Only then plan the production recovery. Never test against the production
   MX or mutate the production bucket.

From Backblaze alone, restore the portable archive into a fresh Stalwart (up to
24 h of loss). The `pg_dump` needs the matching S3 versions.

For a logical database drill set `enable_restore_qualification`, stream a
`pg_dump` into the disposable RDS target, compare, then unset it and require a
no-change plan.

## Isolated mailbox restore drill

Restore a Restic snapshot into a root-only directory, then on the mail host:

```sh
drill="$(nix build --no-link --print-out-paths .#mail-restore-drill)"
stalwart_binary="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' /etc/systemd/system/stalwart.service)"
sudo systemd-run --wait --pipe --collect \
  --property=PrivateNetwork=yes --property=RuntimeMaxSec=1h \
  "$drill/bin/mail-restore-drill" /path/to/restored/fahrican.sqlite "$stalwart_binary"
```

It refuses the host network, restores into a disposable server, re-exports and
compares every blob, date, keyword and folder. It needs three times the archive
size plus 5 GiB free. Repeat it after large imports.

## Private administration

Public `/admin`, `/account` and management `/api` return 404, and built-in
administrator credentials are restricted to loopback. Panels are reachable at
`mail-admin.fahrican.com` (trusted LAN or router VPN, through the homelab
Gateway and the `wg-mail` tunnel) and at `mail-admin-aws.fahrican.com:8443`
through the independent AWS WireGuard VPN, which does not depend on the homelab.
Its client profile is `secrets/mail-vpn-client.yaml`
(`sops decrypt --extract '["config"]' ...`); give each device its own peer.
After creating an administrator or credential run `systemctl start
mail-reconcile` so it receives the loopback restriction. Prepare app
credentials before enabling MFA on the administrator or mailbox logins used by
the reconcilers and the backup export.
