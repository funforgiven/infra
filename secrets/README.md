# Secrets

Commit secret values only as SOPS ciphertext. Recipient rules live in
[`../.sops.yaml`](../.sops.yaml). Never decrypt a secret into a tracked path,
pass it as a command argument, or print it during validation.

This directory holds workstation, host, network, and offline recovery material.
Kubernetes workload secrets are generally stored beside the deployment that
consumes them. The Nix modules, runtime credential schemas, and SOPS documents
are the inventory; this README does not duplicate every key.

## Recovery keys

Back up the complete personal age identity at:

```text
~/.config/sops/age/keys.txt
```

It can decrypt and rekey every current SOPS document. Store its backup outside
the workstation and test that the backup is readable.

NixOS also derives a recipient from `/etc/ssh/ssh_host_ed25519_key` for secrets
needed during unattended activation. Backing up that host key preserves the
machine identity and avoids a recipient migration. If the key is replaced, add
the new recipient and update every host-consumed SOPS document before
installation.

The undercloud and management Flux age identities are stable cluster-recovery
assets. Do not regenerate them during a workstation, host, or cluster rebuild.
Rotate them only as a planned recipient migration.

The management kubeconfig, Backblaze restore readers, backup decryption
identities, and the ZITADEL break-glass credential are administrator recovery
material. They are not deployed by sops-nix or injected into application
clusters.

## Edit a secret

Use the repository-pinned SOPS CLI:

```sh
nix run .#sops --accept-flake-config -- secrets/routeros.yaml
nix run .#sops --accept-flake-config -- path/to/workload-secrets.sops.yaml
```

Generate a replacement account password hash with `mkpasswd -m yescrypt`, then
update `users/funforgiven/password_hash` in `password-hashes.yaml`.

Cloud-host console passwords are stored as unique high-entropy plaintext values
inside the encrypted `cloud-hosts.yaml` document. Do not precompute and commit a
host hash: the controller sends only a salted one-way hash during enrollment.
Password SSH login remains disabled; the original value is for supervised sudo
and PiKVM console recovery.

Replace the binary GitHub SSH private key without first copying it into the
repository:

```sh
nix run .#sops --accept-flake-config -- encrypt \
  --input-type binary \
  --output-type binary \
  --filename-override secrets/github-ssh-key.sops \
  --output secrets/github-ssh-key.sops \
  /secure/path/github_ed25519
```

Use the encrypted management kubeconfig without creating a plaintext copy:

```sh
nix run .#sops --accept-flake-config -- exec-file \
  secrets/capi-management-kubeconfig.sops \
  'kubectl --kubeconfig={} get nodes'
```

After changing a secret consumed by the NixOS controller, apply the host
configuration so sops-nix refreshes its runtime file:

```sh
sudo nixos-rebuild switch --flake .#parmigiano --accept-flake-config
```

Restart or reconcile the affected consumer after the new value is present.

## External credential intake

Ignored `*.key` files are one-way intake files, not a secret store. Each file
must be a non-symlink with mode `0600` and contain exactly one value. The current
external intake names are:

| File | Issuer and use |
| --- | --- |
| `B2_MASTER_APPLICATION_KEY_ID.key` | Temporary Backblaze key ID used to create scoped writers |
| `B2_MASTER_APPLICATION_KEY.key` | Temporary Backblaze key used to create scoped writers |
| `INFRA_TELEGRAM_BOT_TOKEN.key` | Infrastructure alert bot token |
| `ND_LASTFM_APIKEY.key` | Navidrome Last.fm application key |
| `ND_LASTFM_SECRET.key` | Navidrome Last.fm application secret |
| `DISCORD_MUSIC_BOT_TOKEN.key` | Private Muse Discord application bot token |
| `DISCORD_MUSIC_YOUTUBE_API_KEY.key` | Muse key restricted to YouTube Data API v3 |
| `RESEND_ADMIN_API_KEY.key` | Resend administration key used to create a scoped sending key |
| `FACTORIO_USERNAME.key` | Factorio account name used to publish the Space Age server |
| `FACTORIO_TOKEN.key` | Factorio service token used by the public matching server |
| `FACTORIO_GAME_PASSWORD.key` | Shared game password; generate and retain it in a password manager |
| `AWS_BOOTSTRAP_ACCESS_KEY_ID.key` | Temporary AWS identity used to create the mail provisioning identity |
| `AWS_BOOTSTRAP_SECRET_ACCESS_KEY.key` | Temporary AWS bootstrap secret |

Enroll a declared value without echoing it:

```sh
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake KEY
```

The enrollment tool truncates the intake file only after successful SOPS
encryption. Provider reconcilers may also consume a temporary bootstrap value to
create narrower credentials; they clear it only after the returned credentials
are encrypted and verified.

Generated passwords and provider-derived identifiers do not have intake files.
See the [service operations guide](../deployments/homelab/cloud/services/ACTIVATION.md)
for Backblaze, Telegram, Discord music, Resend, AWS mail, and host enrollment.
The Discord and YouTube issuance, least-privilege installation, rotation, and
playback checks are detailed in the
[Muse onboarding guide](../deployments/homelab/cloud/services/40-media/MUSE.md).

## Runtime files

sops-nix decrypts only values declared by the active NixOS configuration. Files
are owned by their consumer account and use mode `0400` unless the service
requires a different mode.

RouterOS automation currently receives five files:

| Runtime path | Use |
| --- | --- |
| `/run/secrets/homelab-routeros-ccr2004-login-password` | CCR2004 login |
| `/run/secrets/homelab-routeros-crs510-login-password` | CRS510 login |
| `/run/secrets/homelab-routeros-ccr2004-wireguard-private-key` | Administration WireGuard interface |
| `/run/secrets/homelab-routeros-ccr2004-wireguard-parmigiano-preshared-key` | Workstation WireGuard peer |
| `/run/secrets/homelab-routeros-ccr2004-mullvad-private-key` | Destination-scoped Mullvad tunnel |

Other controller runtime files include the per-host Ubuntu console passwords,
the Kubernetes API encryption token, and stable undercloud/management Flux and
k3s bootstrap identities. Their exact declarations live in the Nix secret
module and the cloud inventory.

PPPoE credentials remain encrypted recovery material because there is no
declarative runtime consumer. Omada credentials are decrypted only for a manual
reconciliation stream on standard input. Neither is exported to an environment
or written to a runtime file.

## Change recipients

Derive an age recipient from an SSH public key:

```sh
nix run .#ssh-to-age --accept-flake-config \
  < /path/to/ssh_host_ed25519_key.pub
```

After editing `.sops.yaml`, update each affected encrypted document:

```sh
nix run .#sops --accept-flake-config -- updatekeys PATH
```

Review the recipient diff and verify that both the retained recovery identity
and every required host or cluster identity can still decrypt their documents.

If a recipient is compromised, remove it and rotate the SOPS data key in every
affected file:

```sh
nix run .#sops --accept-flake-config -- rotate --in-place PATH
```

Then rotate the underlying API token, SSH key, password, or provider credential.
Re-encryption cannot remove old ciphertext from Git history.

## Plaintext safety

- Do not use a root `.env` as secret storage.
- Do not redirect decrypted output into the repository or a predictable
  temporary file.
- Do not place credentials in command arguments, environment variables, plan
  files, screenshots, chat, or logs.
- Keep recovery readers and decryption identities separate from upload-only
  cluster credentials.
- Verify ciphertext and structure in reviews; do not reveal values to prove that
  an update succeeded.
