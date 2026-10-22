# External providers

Each directory is an OpenTofu root run from the workstation:

| Root | Owns | Provider credentials (environment) |
| --- | --- | --- |
| `identity` | ZITADEL projects, clients, machine user | `TF_VAR_jwt_profile_json` |
| `netbird` | NetBird policy, DNS, IdP | `TF_VAR_netbird_token`, `TF_VAR_default_policy_id` (`../../../deployments/homelab/credentials/netbird-policy/credentials.sops.yaml`) |
| `dns` | Cloudflare records | `CLOUDFLARE_API_TOKEN` (`cloudflare-token.sops.yaml`), `TF_VAR_resend_records_json` |
| `mail-aws` | AWS mail host and its secret values | gitops pair from `mail-aws/aws.sops.yaml` (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) |
| `aws-iam` | the gitops user, its policies and role boundaries | an AWS administrator session (`AWS_PROFILE`) |
| `backblaze` | the `fahrican-cloud-recovery` bucket settings | an account-level B2 key (`B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY`) |

Run every command through the wrapper, which supplies the state passphrase
from `secrets/opentofu-state.sops.yaml` without writing it anywhere:

```sh
nix run .#tofu -- dns init
nix run .#tofu -- dns plan -out=dns.plan
nix run .#tofu -- dns apply dns.plan
nix run .#tofu -- mail-aws output -json   # machine-readable outputs
```

## Why state is committed

Each root's `terraform.tfstate` is committed, encrypted by OpenTofu with
AES-GCM under a PBKDF2 key from that passphrase (`encryption.tf`; plans are
encrypted too and unencrypted state is refused). Git then versions and backs it
up, and `dns` and `netbird` read the `mail-aws` and `identity` states directly
through `terraform_remote_state`. Commit the state after every apply. Never
start a root from empty state: the resources exist.

The identity state is the only copy of the ZITADEL identity-controller machine
key, and the mail-aws and identity states hold client secrets. The passphrase
file and the personal age key that decrypts it are therefore recovery-critical.
Losing the passphrase means re-importing every resource.

Operator-held secrets reach AWS through `mail-aws/secrets.tf` as ephemeral
values in write-only attributes, so they are not stored in state.

## One-time migration

Until every root is migrated, the previous snapshot is in
`secrets/current-provider-state.sops.yaml` (Kubernetes-backend format). For
each of `identity`, `dns`, `netbird` and `mail-aws`:

```sh
nix run .#tofu -- ROOT migrate-legacy-state   # decrypt | unpack | `tofu state push -`
nix run .#tofu -- ROOT plan                    # with the root's credentials; expect no changes
```

Expected first-plan differences: `mail-aws` removes the `SourceRevision` tag,
writes new versions of the resend, backup and vpn secrets (same values), and
needs the role boundaries below; `netbird` reads its client from identity
state. The `mail-aws` feature switches (`enable_reverse_dns`,
`enable_matrix_monitoring`, `enable_matrix_delivery_alerts`) used to come from
untracked tfvars; the last recorded values (commit `b48b84b`) were all `true`,
with `enable_restore_qualification` `false`. If the plan would destroy a
feature, set that variable's default to `true` and commit it instead of
applying. Then commit the `terraform.tfstate` files, delete
`secrets/current-provider-state.sops.yaml` and the `migrate-legacy-state`
branch in `components/nix/servers/providers.nix`.

New roots start by importing what exists:

- `aws-iam`: `apply` imports the gitops user, its two policies and their
  attachments (import blocks) and creates the two role boundaries. Then attach
  them once with administrator credentials, because the gitops identity cannot
  set boundaries:
  `aws iam put-role-permissions-boundary --role-name stalwart-mail --permissions-boundary arn:aws:iam::ACCOUNT:policy/stalwart-mail-boundary`
  (and `stalwart-matrix-probe` with `stalwart-matrix-probe-boundary` if Matrix
  monitoring is enabled). Apply `aws-iam` before the next `mail-aws` apply.
- `backblaze`: `nix run .#tofu -- backblaze import b2_bucket.recovery BUCKET_ID`
  (`b2 bucket get fahrican-cloud-recovery` shows the ID), then plan.
