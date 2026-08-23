# AWS Stalwart mail platform

This is the production mail platform. It is fixed
to `eu-central-1` and deliberately favors the smallest simple durable design:

- one Graviton `t4g.micro` EC2 instance running the signed NixOS `mail-aws`
  configuration, with a NixOS-owned 2 GiB swapfile created before the first
  rebuild so the 1 GiB appliance remains viable without a larger instance;
- one single-AZ encrypted `db.t4g.micro` RDS PostgreSQL 17.10 instance with
  14-day point-in-time recovery, deletion protection, a final snapshot, and an
  RDS-managed master password. Storage explicitly uses the no-cost AWS-managed
  `alias/aws/rds` key resolved to its canonical key ARN so provider state cannot
  mistake the equivalent alias ARN for a replacement, while the managed
  password intentionally inherits RDS's documented
  `alias/aws/secretsmanager` default. Stalwart retains strict PostgreSQL TLS
  validation through the content-hash-pinned official Frankfurt RDS CA bundle;
- one private encrypted and versioned S3 bucket as Stalwart's live blob store;
- one retained Elastic IP, with reverse DNS gated until forward DNS is live;
- Session Manager administration only, with no public SSH ingress;
- standard CloudWatch EC2/RDS alarms delivered through an independent SNS email
  subscription; and
- three Secrets Manager boundaries: instance-generated administrator and
  mailbox passwords, plus the separately enrolled Resend sending key.

The EC2 root disk is replaceable. Stalwart's registry, mailbox metadata, and
indexes live in RDS; message bodies and attachments live in S3. A replacement
instance reconstructs its only local Stalwart file from the RDS-managed secret,
then resumes against the existing RDS and S3 state. The bucket retains deleted
and overwritten object versions for 90 days. RDS and S3 both have OpenTofu
`prevent_destroy` protection, and RDS additionally has provider deletion
protection.

This is intentionally not multi-AZ. The mail protocols tolerate a short host or
database maintenance window, while managed PostgreSQL, S3 durability, and a
recoverable EC2 appliance address the requested data-safety boundary at much
lower recurring cost. If availability requirements change, enable Multi-AZ RDS
before adding Stalwart nodes; the current PostgreSQL-backed cache and registry
do not require a separate Redis coordinator for one node.

## Credential boundary

OpenTofu creates only empty Secrets Manager containers. It never creates a
secret version and never receives a database, administrator, mailbox, or Resend
value. RDS owns its password. On first boot the instance generates the two local
passwords, reconciles the declarative Stalwart account plan through the official
`stalwart-cli apply` interface, then publishes those values directly to their
least-privilege Secrets Manager containers without logging them. Its IAM role
cannot write the Resend container.

The final activation input is a temporary AWS bootstrap pair placed in the two
ignored mode-0600 `AWS_BOOTSTRAP_*` intake files. The cohesive credential tool
uses that authority only to reconcile the `fahrican-mail-gitops` IAM user and
the reviewed customer-managed regional policy in `bootstrap-iam-policy.json`,
creates one new access pair for that identity, encrypts only the narrower pair into the
`aws-mail-provisioning` SOPS Secret, verifies the dedicated identity, revokes
the exact temporary key, and only then clears the intake files. Neither pair is
passed as an OpenTofu variable, committed in plaintext, or placed in a shell
argument. Provider operations that require an access-key identifier receive it
through an immediately removed mode-0600 JSON input file. Identity verification
tolerates bounded IAM propagation delay, and unpersisted orphan keys are retired
before replacement. Interrupted revocation is resumable from the encrypted
dedicated pair, while a mismatch between AWS and existing ciphertext is a hard
failure. The GitOps Terraform object remains suspended until that final
enrollment.

RDS validates the creating principal's access to both AWS-managed KMS keys.
The provisioning identity can only describe KMS keys in Frankfurt whose
resource aliases are exactly `alias/aws/rds` or `alias/aws/secretsmanager`; it
cannot create, rotate, disable, decrypt with, or schedule deletion of any KMS
key. The master-secret key override remains absent so AWS does not interpret it
as a request for customer-managed-key grant permissions.

The same identity cannot retrieve any Secrets Manager value. Its lifecycle
access is limited to containers below `fahrican/stalwart/`; the only exception
is `CreateSecret` and `TagResource` on AWS's `rds!db-*` namespace, which RDS
requires when it creates a service-managed master credential. That exception
cannot read, change, or delete a secret value. The identity's only
secret-version mutation is `PutSecretValue` on the Resend container. Runtime
reads and the generated administrator/mailbox writes remain exclusive to the
EC2 role. Systems Manager inspection is Frankfurt-only, and Run Command is
limited to the AWS shell document and EC2 instances tagged
`Service=stalwart-mail`.

## Safe operation

The Git-pinned EC2 bootstrap accepts only the declared signed source revision.
After infrastructure changes, require the bootstrap marker, a healthy Stalwart
unit, RDS connectivity, the S3 read/write probe, and all declared CloudWatch
alarms. Confirm the SNS subscription remains active.

Rotate the domain-scoped Resend sending key with
`reconcile-services-resend apply`, then run `publish-aws-mail-resend` to stream
it from its admin-only SOPS document into `fahrican/stalwart/resend` without
printing it. Require `stalwart-resend-reconcile` to converge. For DNS changes,
validate DKIM, SPF, DMARC, autoconfiguration records, TLS hostname verification,
the EIP PTR, an independent Resend-to-MX delivery, and an authenticated IMAPS
read.

## Migration completion evidence

The production migration completed on 2026-08-23. The signed origin change in
`9d55a44ad7326b2821aedfb9723462c11a278fc3` moved the Git-managed mail names to
the AWS EIP only after the following recovery and data checks succeeded:

- the final encrypted source snapshot was created before cutover and used for
  qualification; after explicit approval, its Backblaze repository and every
  Hetzner provider backup were permanently erased on 2026-08-23;
- the source contained five folders and three INBOX messages. The initial
  standard IMAP copy transferred all three messages and 4,538 bytes. The final
  maintenance-window delta compared all five folders and reported no source-
  only or target-only messages and no bytes left to transfer;
- an isolated RDS logical restore reproduced the production schema and registry
  counts, and the disposable database and security group were removed. The
  encrypted `stalwart-mail-pre-cutover-20260823` snapshot remains available;
- an isolated S3 noncurrent-version restore reproduced and compared the selected
  object, after which the test object, versions, and delete marker were removed;
- authenticated IMAPS and implicit-TLS SMTP passed against the public hostname,
  and the submitted local message became visible in the mailbox. An independent
  Resend API submission then traversed the public MX and was found through
  authenticated IMAPS. Receipt was verified at the destination rather than
  broadening the domain-scoped sending key to permit delivery-status reads; and
- the resulting Stalwart queue was empty and the service remained active.

The accepted production shape is one running `t4g.micro` instance
`i-026dd3834bd8a5f52` at `18.195.240.25`, one available encrypted
`db.t4g.micro` PostgreSQL 17.10 database with 14-day recovery and deletion
protection, and the encrypted, versioned
`fahrican-stalwart-027355625923-eu-central-1` blob bucket. No restore database
remains. All three declared CloudWatch alarms were `OK`. Forward DNS resolves
`mail.fahrican.com` to the EIP, its PTR resolves back to `mail.fahrican.com`,
and public hostname verification passed on HTTPS, submissions, and IMAPS.

The former Hetzner server, retained IPv4, firewall, SSH key, provider backups,
and Backblaze Restic repository were explicitly approved for destruction and
retired on 2026-08-23. AWS is the sole mail origin. The pre-cutover RDS snapshot
remains an independent AWS recovery artifact.

RDS point-in-time recovery and S3 versions form one recovery procedure: restore
RDS to the selected time, remove any later S3 delete markers needed by the
restored registry, then attach a replacement EC2 instance to those stores. The
test must be performed with isolated copies and a non-public address; never test
a restore against the production bucket or MX.

For a credential-safe logical restore drill, temporarily set
`enable_restore_qualification` in the deployment root. OpenTofu creates a
private disposable `db.t4g.micro` target and grants only the mail instance role
access to its RDS-managed credential. Stream a custom-format `pg_dump` from the
production database into that target, compare non-secret schema and row counts,
then set the variable back to false and require a no-change plan after OpenTofu
has removed the disposable database and security group. The target has no
backups, final snapshot, public address, deletion protection, or retained
credential container; it must never receive production traffic.
