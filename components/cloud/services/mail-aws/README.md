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
- CloudWatch alarms publish to an SNS email subscription.

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
- public HTTPS, submission, IMAPS, MX, and TLS hostname behavior.

For DNS changes, also verify DKIM, SPF, DMARC, autoconfiguration records, and
the EIP forward/reverse mapping.

Rotate the domain-scoped Resend key with:

```sh
nix run .#reconcile-services-resend -- apply
nix run .#publish-aws-mail-resend
```

Wait for `stalwart-resend-reconcile` to converge, then send an independent test
message through the public MX and confirm it over authenticated IMAPS.

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
