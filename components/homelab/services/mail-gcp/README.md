# Stalwart on Google Cloud

The Mail project (`fahrican-mail`) serves `fahrican.com` from Belgium. A disposable Debian 13 `e2-micro` accepts SMTP on port 25 and JMAP over HTTPS on port 443. The restored Stalwart registry routes outbound mail through Resend on TLS port 465. Keep the Stalwart version compatible with the registry when replacing a host.

PostgreSQL 17 runs on a zonal Cloud SQL Enterprise `db-f1-micro` with private IP. The host connects through the loopback Cloud SQL Auth Proxy with automatic IAM authentication. The VM identity owns the mail tables. Message bodies use the GCS XML endpoint and the existing `blobs/` key prefix. A separate service account has object access only on the mail bucket. The VM reads its HMAC key and mail credentials from Secret Manager on boot. Restart `mail-secrets.service` and `stalwart.service` after credential rotation.

## Infrastructure and budget

The [OpenTofu root](../../providers/mail-gcp/) uses the private, versioned `gs://fahrican-mail-infra-state` backend. The [deployment inputs](../../../../deployments/homelab/credentials/mail-gcp/deployment.json) hold the project, external alert address, budget and activation flags. Run these commands from the repository root.

```sh
root=components/homelab/providers/mail-gcp
inputs=../../../../deployments/homelab/credentials/mail-gcp/deployment.json
tofu -chdir="$root" init -backend-config=bucket=fahrican-mail-infra-state
tofu -chdir="$root" plan -var-file="$inputs" -out=/private/path/mail.plan
tofu -chdir="$root" apply /private/path/mail.plan
```

At 730 hours/month, the Belgium E2 micro is about $6.73, Cloud SQL micro $7.67, and the in-use IPv4 address $3.65. Allow roughly $20–25/month in total for light use, including 20 GiB standard VM disk, 10 GiB SQL HDD, backups, object storage and operations. Traffic, data growth, taxes, and off-provider services affect actual charges. The shared-core database has no Cloud SQL SLA. Automatic SQL disk growth stops at 30 GiB. [VM pricing](https://cloud.google.com/compute/vm-instance-pricing), [Cloud SQL pricing](https://cloud.google.com/sql/pricing), [network pricing](https://cloud.google.com/vpc/network-pricing).

Cloud Billing alerts at 50%, 80% and 100% of a project-specific monthly budget before credits. The budget is denominated in TRY. At setup, Google's billing catalog rate was ₺49.837 per USD, so ₺1,993 represented $40. Review it when the rate changes. Thresholds send notifications and allow service to continue running. The Ultra 5x credit belongs to the billing account and follows the benefit's monthly anniversary. [Credit terms](https://developers.google.com/profile/help/benefits).

## Access and monitoring

Use OS Login through IAP for shell or CLI administration.

```sh
gcloud compute ssh stalwart --project=fahrican-mail --zone=europe-west1-b --tunnel-through-iap
sudo systemctl status stalwart mail-sql
sudo systemctl start mail-operations@health.service
```

The management listener binds to `127.0.0.1:8081`. Administrative credentials are restricted to loopback. The public management and account panels are disabled. IAP replaces the AWS WireGuard administration path.

Once `monitor_delivery` is enabled, Google Monitoring checks the public HTTPS endpoint independently and alerts the external operator mailbox when health telemetry stops. The host checks authenticated JMAP, SMTP STARTTLS, TLS expiry, queue age and recovery freshness. The half-hourly canary sends via Resend to the public MX, downloads the attachment through JMAP, verifies it, then deletes the probe message.

## Migration record

On November 23, 2026 the public MX moved to `mail.fahrican.com` at `34.38.74.236`.
The source was the November 17 AWS snapshot `stalwart-mail-paused-20261117`.
All 27 PostgreSQL table counts matched after restore, and all 152 current S3
blobs matched their GCS copies byte for byte. The replacement VM passed the
public Resend-to-JMAP delivery test and restored its first encrypted offsite
backup. The EU Cloud SQL baseline backup ID is `1795463887233`.

The AWS snapshot, original versioned bucket and recovery secrets remain
available. Their retention incurs separate AWS charges. The temporary migration
database and SSM tunnel VM were removed.

## Recovery

Cloud SQL retains 14 daily backups and seven days of transaction logs. The regional bucket keeps noncurrent object generations for 90 days. Pair a restored database with the blob generations visible at its restore timestamp, including objects that were subsequently deleted. Rehearse in a separate bucket and database before changing production. Preserve the IAM user's database grants when restoring to a different instance.

The nightly offsite Restic backup contains a Vandelay archive of the primary mailbox and a full PostgreSQL dump. It uses the existing restricted Backblaze repository with the host and tag `mail-gcp`. The weekly restore check downloads a snapshot, verifies file hashes and SQLite integrity, then checks the PostgreSQL archive. Backups retain 14 daily, eight weekly and 12 monthly snapshots. The standalone mailbox archive contains its own message bodies. A whole-server restore from the dump also needs matching GCS objects.

```sh
sudo systemctl start mail-operations@backup.service
sudo systemctl start mail-operations@restore-check.service
sudo systemctl list-timers 'mail-*'
```

## Migration and cutover

1. Provision with `enable_runtime=false` and `monitor_delivery=false`. Use IAP to reach the loopback SQL proxy. Run `enroll.py --project fahrican-mail` from an authenticated AWS and Google operator workstation to seed the five existing credentials and the bucket HMAC key. Existing enabled secret versions are reused.
2. Restore the paused RDS snapshot to a temporary private instance. Take a PostgreSQL custom-format dump through an SSM tunnel with certificate verification, and record per-table counts. Copy only current `blobs/` from S3 into the matching GCS prefix and run `rclone check --download` against both prefixes. Retain the source snapshot and versioned bucket.
3. Grant the IAM SQL user `USAGE, CREATE` on the target database's public schema. Restore to the empty target as that user with `pg_restore --single-transaction --exit-on-error --no-acl --no-owner`. Compare all table counts. Retire the temporary AWS instance and tunnel.
4. Stage the Cloudflare mail host A records with `stage_mail_hosts=true`, the reserved IPv4 and `mail_enabled=false`. Keep the existing DNS state and scope changes to mail records in the shared zone. Enable the runtime. A replacement VM reconstructs the data-store connection and repoints the restored registry's blob store from recovery mode. Check the public certificate, authenticated mailbox and attachments, SMTP STARTTLS, relay and first offsite backup.
5. Publish the live MX with `mail_enabled=true`, remove the staging flag and enable delivery monitoring. Verify a real canary and restore check. To suspend inbound mail, publish Null MX first. Once the new server has accepted mail, preserve that data before any rollback to the pre-migration AWS snapshot.
