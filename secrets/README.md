# Secrets

Commit secret values only as SOPS ciphertext; recipient rules are in
[`../.sops.yaml`](../.sops.yaml). Workstation, host, network and recovery
material lives here; workload and host credentials live beside their consumer
(`deployments/homelab/cluster/**`, `deployments/homelab/credentials/**`,
`deployments/homelab/hosts/secrets.sops.yaml`). **The consumer's file is the
only copy**: there is no intermediate store or renderer. Retired
OpenStack/CAPI-era archives were removed from the tree and remain retrievable
from git history before the refactor branch (commit `7078aef`).

## Recipients and recovery keys

| Recipient | Who decrypts |
| --- | --- |
| personal age key (`~/.config/sops/age/keys.txt`) | everything; the recovery identity |
| parmigiano SSH host key | workstation sops-nix (`secrets/`, `deployments/homelab/credentials/`, host secrets) |
| cluster host identity (`secrets/kubernetes.yaml` `cluster.host_age_identity`) | pecorino, taleggio and asiago, all sharing this one key at `/var/lib/sops-nix/key.txt` |
| Flux identity (`cluster.flux_age_identity`) | `deployments/homelab/cluster/**` in the cluster |

Back up the personal key outside the workstation and test the backup. It
decrypts the OpenTofu state passphrase (`opentofu-state.sops.yaml`), and with
it the provider states that hold the only copy of the ZITADEL machine key.
Backblaze restore readers, recovery age identities (`backblaze.yaml`) and the
ZITADEL break-glass credential are administrator-only and never deployed.

The cluster hosts' identity is also inside every etcd backup. A compromised
host therefore exposes all host secrets; per-host recipients would need each
host's own key in `.sops.yaml` and re-encryption of the host file.

## Edit and rotate

```sh
nix run .#sops --accept-flake-config -- path/to/file.sops.yaml   # edit in place
nix run .#sops --accept-flake-config -- updatekeys PATH           # after editing .sops.yaml
nix run .#sops --accept-flake-config -- rotate --in-place PATH    # after removing a recipient
```

Set a generated value without it appearing in arguments or output (values
under a `data:` map are base64, under `stringData:` plain):

```sh
head -c 32 /dev/urandom | base64 -w0 | jq -Rs . | \
  sops set --value-stdin FILE '["stringData"]["KEY"]'
```

Then apply the consumer: Flux for cluster Secrets, `nixos-rebuild` for
sops-nix files, `nix run .#tofu -- mail-aws apply` for the mail host's
Resend, backup and VPN values, `enroll-service-host-secrets` for the UniFi
guest. Re-encryption never removes old ciphertext from Git history, so rotate
the underlying credential after a recipient compromise.

- **ZITADEL OIDC clients**: change them in the `identity` root, then
  `nix run .#tofu -- identity output -json | nix run .#identity-credentials`
  updates Forgejo, Grafana, media and Matrix (NetBird reads identity state).
- **Backblaze keys** are minted by hand so rotation never revokes a key in
  use: `b2 key create --bucket fahrican-cloud-recovery --name-prefix PREFIX NAME
  deleteFiles,listBuckets,listFiles,readBuckets,readFiles,writeFiles`, write it
  into every consumer of that prefix, roll the consumers out, verify a backup,
  and only then `b2 key delete` the old key. Writers per prefix:
  `services/kubernetes/` Velero (`velero/credentials.sops.yaml`) and NetBird
  Barman (`netbird/server/backup.sops.yaml`); `services/etcd/` the hosts'
  `etcd_backup_environment`; `services/hosts/mail-aws/` and
  `services/hosts/unifi/` in `credentials/host-runtime/backups.sops.yaml`;
  `undercloud/zitadel/` the identity database backup.
- **Resend**: create a sending-access key restricted to `fahrican.com` in the
  Resend dashboard, store it (Stalwart: `mail-aws/resend.sops.yaml`; Forgejo
  and Matrix: their runtime/email Secrets), deploy, then revoke the old key.
- **AWS gitops key**: with an administrator session,
  `aws iam create-access-key --user-name fahrican-mail-gitops`, store it in
  `credentials/mail-aws/aws.sops.yaml`, verify `aws sts get-caller-identity`,
  then delete the old key. The policies are in `providers/aws-iam`.
- **Telegram alert bot**: revoke and reissue in BotFather; store the token in
  the observability `infrastructure-telegram` Secret.
- **Restic and database passwords** are never rotated in place; changing them
  orphans existing backups.
- **Account password**: `mkpasswd -m yescrypt`, then
  `users/funforgiven/password_hash` in `password-hashes.yaml`.

PPPoE credentials are recovery material with no runtime
consumer; Omada credentials are only streamed to a manual reconciliation.
`windows-gorgonzola.yaml` and `local-recovery.yaml` are personal-key-only
records, never deployed.

## Plaintext safety

- Never decrypt into a tracked path or a predictable temporary file, print a
  value, or pass one as a command argument; use pipes and `--value-stdin`.
- Do not use a root `.env`. Keep recovery readers apart from upload-only keys.
- Prove a change by ciphertext and structure in review, not by revealing values.

## Atollion GitHub CLI token

Create a fine-grained token at
<https://github.com/settings/personal-access-tokens/new>: owner `funforgiven`,
repository `atollion` only, Contents read-only, Issues and Pull requests
read/write, short expiry. Never a classic token. Replace
`codex/atollion_github_cli_token` in `api-tokens.yaml`, rebuild the workstation
and check `gh repo view` from `~/dev/atollion`; the `gh` wrapper only uses it
there and rejects `gh auth`.

Replace the binary GitHub SSH key without copying it into the repository:
`sops encrypt --input-type binary --output-type binary --filename-override
secrets/github-ssh-key.sops --output secrets/github-ssh-key.sops /secure/path/key`.
