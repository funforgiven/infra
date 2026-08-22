# AWS Stalwart mail platform

This is the prepared replacement for the legacy Hetzner mail host. It is fixed
to `eu-central-1` and deliberately favors the smallest simple durable design:

- one Graviton `t4g.micro` EC2 instance running the signed NixOS `mail-aws`
  configuration, with a NixOS-owned 2 GiB swapfile created before the first
  rebuild so the 1 GiB appliance remains viable without a larger instance;
- one single-AZ encrypted `db.t4g.micro` RDS PostgreSQL 17.10 instance with
  14-day point-in-time recovery, deletion protection, a final snapshot, and an
  RDS-managed master password. Storage explicitly uses the no-cost AWS-managed
  `alias/aws/rds` key, while the managed password intentionally inherits RDS's
  documented `alias/aws/secretsmanager` default;
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
access is limited to containers below `fahrican/stalwart/`, and its only
secret-version mutation is `PutSecretValue` on the Resend container. Runtime
reads and the generated administrator/mailbox writes remain exclusive to the
EC2 role. Systems Manager inspection is Frankfurt-only, and Run Command is
limited to the AWS shell document and EC2 instances tagged
`Service=stalwart-mail`.

## Safe activation and migration

1. Finish and sign the implementation commit. Pin that commit as
   `source_revision` in the suspended Terraform object. The EC2 bootstrap
   accepts only that exact commit and verifies its SSH signature against the
   repository signing key using Nix verified fetches.
2. Put the temporary AWS bootstrap pair in the declared intake files and run
   `nix run .#enroll-aws-mail-auth`. Verify that both files are empty, review
   the dedicated identity and policy, confirm the temporary key was revoked,
   review the OpenTofu plan, and unsuspend only `mail-aws`. Do not change
   `active-mail-origin`; Hetzner remains the live MX and rollback source.
3. Confirm the SNS email subscription. Through Session Manager, require the
   bootstrap marker, a healthy Stalwart unit, RDS connectivity, an S3 write/read
   probe, and generated administrator and mailbox secret versions.
4. Run `nix run .#publish-aws-mail-resend` to stream the existing domain-scoped
   Resend sending key directly from its
   admin-only SOPS document into `fahrican/stalwart/resend` without printing it.
   Require the `stalwart-resend-reconcile` unit to converge.
5. Export the AWS domain's public DNS zone through the authenticated CLI, add
   its generated DKIM records to the Git-managed DNS root, and validate SPF,
   DKIM, DMARC, autoconfiguration records, TLS, submission, IMAPS, inbound SMTP,
   and outbound Resend relay against the AWS EIP before cutover.
6. Make a final encrypted backup of the Hetzner server. Copy the mailbox with a
   standard IMAP migration tool using credential files or no-echo prompts, run a
   second delta pass during the maintenance window, and compare message and
   folder counts. No password may appear in an argument or log.
7. Change `active-mail-origin` from `hetzner` to `aws`. The existing reconciler
   selects the AWS output in memory and the Cloudflare root moves the A/MX-facing
   mail names without changing any workload secret. After forward DNS has
   propagated, set `enable_reverse_dns` to true and verify the EIP PTR.
8. Repeat the independent Resend-to-MX acceptance test and authenticated IMAPS
   read. Retain the protected Hetzner server and backup for at least 14 days.
   Remove it only in a later explicit, reviewed change after RDS point-in-time
   recovery and S3 version recovery have both been exercised.

RDS point-in-time recovery and S3 versions form one recovery procedure: restore
RDS to the selected time, remove any later S3 delete markers needed by the
restored registry, then attach a replacement EC2 instance to those stores. The
test must be performed with isolated copies and a non-public address; never test
a restore against the production bucket or MX.
