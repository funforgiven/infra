# Repository Secrets

Commit secret values only as SOPS ciphertext. Recipients are declared in
`../.sops.yaml`.

## Inventory

| SOPS file and key | Purpose |
| --- | --- |
| `github-ssh-key.sops` | GitHub SSH authentication and signing |
| `api-tokens.yaml` → `codex/anwa_github_mcp_token` | Anwa workspace GitHub MCP server |
| `api-tokens.yaml` → `codex/github_mcp_token` | GitHub MCP server |
| `api-tokens.yaml` → `codex/context7_api_key` | Context7 MCP server |
| `omada.yaml` → `omada/api_base` | Omada Cloud API endpoint |
| `omada.yaml` → `omada/id` | Omada controller identifier |
| `omada.yaml` → `omada/client_id` | Omada API client identifier |
| `omada.yaml` → `omada/client_secret` | Omada API client secret |
| `routeros.yaml` → `routeros/pppoe_username` | TurkNet PPPoE username |
| `routeros.yaml` → `routeros/pppoe_password` | TurkNet PPPoE password |
| `password-hashes.yaml` → `users/funforgiven/password_hash` | NixOS account password hash |

## Recovery

Back up the complete personal age identity at
`~/.config/sops/age/keys.txt`. It can decrypt and rekey every current secret.

NixOS also derives a recipient from `/etc/ssh/ssh_host_ed25519_key` for
secrets consumed during unattended activation. Backing up that host key is
optional; it preserves the host identity and avoids updating those recipient
sets. `omada.yaml` deliberately excludes the host because it has no deployed
consumer. When replacing the host key, derive the new recipient, add it to
`../.sops.yaml`, and update every host-consumed SOPS file before
`nixos-install`.

## Editing

Edit the structured files with the repository-pinned CLI:

```sh
nix run .#sops --accept-flake-config -- secrets/api-tokens.yaml
nix run .#sops --accept-flake-config -- secrets/omada.yaml
nix run .#sops --accept-flake-config -- secrets/password-hashes.yaml
nix run .#sops --accept-flake-config -- secrets/routeros.yaml
```

Replace the binary SSH key by encrypting a new private key directly. Do not
copy the plaintext key into this repository:

```sh
nix run .#sops --accept-flake-config -- encrypt \
  --input-type binary \
  --output-type binary \
  --filename-override secrets/github-ssh-key.sops \
  --output secrets/github-ssh-key.sops \
  /secure/path/github_ed25519
```

Generate a replacement password hash with `mkpasswd -m yescrypt`, then update
`users/funforgiven/password_hash` in `password-hashes.yaml`.

After changing a secret, activate the NixOS configuration and restart its
consumer:

```sh
sudo nixos-rebuild switch --flake .#parmigiano --accept-flake-config
```

## Network Runtime Files

sops-nix decrypts `routeros.yaml` during system activation and materializes
its values as separate files owned by `funforgiven` with mode `0400`:

| Runtime path | Consumer |
| --- | --- |
| `/run/secrets/homelab-routeros-pppoe-username` | RouterOS PPPoE installer |
| `/run/secrets/homelab-routeros-pppoe-password` | RouterOS PPPoE installer |

The RouterOS launcher reads the two PPPoE files directly and prompts
interactively for the separate RouterOS administrator password. The
repository does not yet have an Omada API consumer, so `omada.yaml` is
encrypted only to the personal recovery recipient. Its values are not
decryptable by the host, materialized as runtime files, exported into an
environment, or used to reconcile controller state. Add a narrowly scoped
host recipient and runtime declarations only when that consumer exists.

The root `.env` migration is complete. Do not recreate it: the ignore rule is
retained only as defense in depth. Use the SOPS editor above rather than
redirecting decrypted output into a repository or temporary file. Never
decrypt a secret into a committed path, pass a secret value in a command
argument, or print it in validation output.

## Recipient Changes

Derive a recipient from a host public key with:

```sh
nix run .#ssh-to-age --accept-flake-config \
  < /path/to/ssh_host_ed25519_key.pub
```

After changing `../.sops.yaml`, update every encrypted file:

```sh
nix run .#sops --accept-flake-config -- updatekeys secrets/api-tokens.yaml
nix run .#sops --accept-flake-config -- updatekeys secrets/github-ssh-key.sops
nix run .#sops --accept-flake-config -- updatekeys secrets/omada.yaml
nix run .#sops --accept-flake-config -- updatekeys secrets/password-hashes.yaml
nix run .#sops --accept-flake-config -- updatekeys secrets/routeros.yaml
```

If a recipient is compromised, remove it, run `updatekeys`, and rotate each
affected file's SOPS data key:

```sh
nix run .#sops --accept-flake-config -- rotate --in-place FILE
```

Also rotate every affected API token, SSH key, or password. Old ciphertext
remains available in Git history.
