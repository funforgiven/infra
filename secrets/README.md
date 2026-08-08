# Repository Secrets

Commit secret values only as SOPS ciphertext. Recipients are declared in
`../.sops.yaml`.

## Inventory

| SOPS file and key | Purpose |
| --- | --- |
| `github-ssh-key.sops` | GitHub SSH/signing and physical-host automation |
| `api-tokens.yaml` → `codex/anwa_github_mcp_token` | Anwa workspace GitHub MCP server |
| `api-tokens.yaml` → `codex/github_mcp_token` | GitHub MCP server |
| `api-tokens.yaml` → `codex/context7_api_key` | Context7 MCP server |
| `omada.yaml` → `omada/api_base` | Omada Cloud API endpoint |
| `omada.yaml` → `omada/id` | Omada controller identifier |
| `omada.yaml` → `omada/client_id` | Omada API client identifier |
| `omada.yaml` → `omada/client_secret` | Omada API client secret |
| `omada.yaml` → `wireless/psks/personal` | `Rooftrollen` WPA2-PSK |
| `omada.yaml` → `wireless/psks/iot` | `Rooftrollen_IoT` WPA2-PSK |
| `backblaze.yaml` → `undercloud/etcd_recovery/age_identity` | Cluster-external etcd backup decryption identity |
| `backblaze.yaml` → `undercloud/etcd_restore_reader/application_key_id` | Read-only B2 recovery key identifier |
| `backblaze.yaml` → `undercloud/etcd_restore_reader/application_key` | Read-only B2 recovery key secret |
| `backblaze.yaml` → `undercloud/openstack_restore_reader/application_key_id` | Read-only OpenStack B2 recovery key identifier |
| `backblaze.yaml` → `undercloud/openstack_restore_reader/application_key` | Read-only OpenStack B2 recovery key secret |
| `backblaze.yaml` → `management/etcd_recovery/age_identity` | Cluster-external management-etcd backup decryption identity |
| `backblaze.yaml` → `management/etcd_restore_reader/application_key_id` | Read-only management B2 recovery key identifier |
| `backblaze.yaml` → `management/etcd_restore_reader/application_key` | Read-only management B2 recovery key secret |
| `capi-management-kubeconfig.sops` | Encrypted administrative kubeconfig for management-cluster recovery |
| `../deployments/homelab/cloud/undercloud/20-backup/writer.sops.yaml` | Flux-managed, upload-only B2 credential |
| `../deployments/homelab/cloud/undercloud/50-openstack-core/compute/openstack-backup-writer.sops.yaml` | Flux-managed, upload-only OpenStack B2 credential |
| `../deployments/homelab/cloud/management/30-backup/writer.sops.yaml` | Flux-managed, upload-only management B2 credential |
| `routeros.yaml` → `routeros/pppoe_username` | TurkNet PPPoE username |
| `routeros.yaml` → `routeros/pppoe_password` | TurkNet PPPoE password |
| `routeros.yaml` → `routeros/ccr2004_login_password` | CCR2004 `admin` login password |
| `routeros.yaml` → `routeros/crs510_login_password` | CRS510 `admin` login password |
| `cloud-hosts.yaml` → `cloud_hosts/taleggio/ubuntu_console_password` | Taleggio local-console and sudo recovery password |
| `cloud-hosts.yaml` → `cloud_hosts/asiago/ubuntu_console_password` | Asiago local-console and sudo recovery password |
| `cloud-hosts.yaml` → `cloud_hosts/pecorino/ubuntu_console_password` | Pecorino local-console and sudo recovery password |
| `kubernetes.yaml` → `undercloud/kube_encrypt_token` | Stable Kubernetes API secret-at-rest encryption key |
| `kubernetes.yaml` → `undercloud/flux_age_identity` | Stable Flux SOPS age identity for undercloud reconciliation |
| `kubernetes.yaml` → `management/k3s_token` | Stable k3s join and recovery token for the management cluster |
| `kubernetes.yaml` → `management/flux_age_identity` | Stable Flux SOPS age identity for the management cluster |
| `password-hashes.yaml` → `users/funforgiven/password_hash` | NixOS account password hash |

## Recovery

Back up the complete personal age identity at
`~/.config/sops/age/keys.txt`. It can decrypt and rekey every current secret.

NixOS also derives a recipient from `/etc/ssh/ssh_host_ed25519_key` for
secrets consumed during unattended activation. Backing up that host key is
optional; it preserves the host identity and avoids updating those recipient
sets. `omada.yaml` deliberately excludes the host because it has no deployed
unattended runtime-file consumer. The manual Omada reconciler receives a
personal-recipient decryption stream on standard input and does not require a
host recipient. When replacing the host key, derive the new recipient, add it
to `../.sops.yaml`, and update every host-consumed SOPS file before
`nixos-install`.

The undercloud and management Flux age identities are stable recovery assets. sops-nix
materializes them only on the controller, and bootstrap injects each as
`flux-system/sops-age`. Do not regenerate them during a workstation, host, or
cluster rebuild; rotate them only as an explicit recipient migration.

## Editing

Edit the structured files with the repository-pinned CLI:

```sh
nix run .#sops --accept-flake-config -- secrets/api-tokens.yaml
nix run .#sops --accept-flake-config -- secrets/backblaze.yaml
nix run .#sops --accept-flake-config -- secrets/cloud-hosts.yaml
nix run .#sops --accept-flake-config -- secrets/kubernetes.yaml
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

Use the management kubeconfig without leaving a plaintext copy behind:

```sh
nix run .#sops --accept-flake-config -- exec-file \
  secrets/capi-management-kubeconfig.sops \
  'kubectl --kubeconfig={} get nodes'
```

Generate a replacement password hash with `mkpasswd -m yescrypt`, then update
`users/funforgiven/password_hash` in `password-hashes.yaml`.

Cloud-host console secrets are different: store a unique high-entropy
plaintext value per host inside `cloud-hosts.yaml`; never commit a precomputed
host hash. sops-nix materializes only the selected value on the controller,
while the Ubuntu host receives only a salted one-way hash during supervised
enrollment. OpenSSH password authentication stays disabled; the runtime value
is used solely for password-required sudo over an SSH-key-authenticated
connection and for PiKVM console recovery.

After changing a secret, activate the NixOS configuration and restart its
consumer:

```sh
sudo nixos-rebuild switch --flake .#parmigiano --accept-flake-config
```

## Controller Runtime Files

sops-nix decrypts selected keys from `routeros.yaml`, `cloud-hosts.yaml`, and
`kubernetes.yaml` during system activation and materializes them as separate
files owned by `funforgiven` with mode `0400`:

| Runtime path | Consumer |
| --- | --- |
| `/run/secrets/homelab-routeros-ccr2004-login-password` | CCR2004 Ansible network automation |
| `/run/secrets/homelab-routeros-crs510-login-password` | CRS510 Ansible network automation |
| `/run/secrets/cloud-host-taleggio-ubuntu-console-password` | Taleggio Ansible sudo and PiKVM console recovery |
| `/run/secrets/cloud-host-asiago-ubuntu-console-password` | Asiago Ansible sudo and PiKVM console recovery |
| `/run/secrets/cloud-host-pecorino-ubuntu-console-password` | Pecorino Ansible sudo and PiKVM console recovery |
| `/run/secrets/undercloud-kube-encrypt-token` | Kubespray secret-at-rest encryption configuration |
| `/run/secrets/undercloud-flux-age-identity` | Flux `flux-system/sops-age` bootstrap and recovery |
| `/run/secrets/management-k3s-token` | Management k3s bootstrap and recovery |
| `/run/secrets/management-flux-age-identity` | Management Flux `flux-system/sops-age` bootstrap and recovery |

The two login passwords are independent URL-safe encodings of 32 random bytes:
exactly 43 characters from `A-Z`, `a-z`, `0-9`, `_`, and `-`. Ansible checks
the shape without printing a value. Rotate one device at a time through its
direct console or WinBox, then update the matching SOPS value before the next
automation run.

The PPPoE values remain encrypted in `routeros.yaml` as the recovery source for
future Terraform/REST adoption. They have no runtime files while there is no
declarative consumer. The Omada reconciler documented under
`components/cloud/network-automation/` accepts the complete decrypted JSON
document only through standard input for manual runs. `omada.yaml` remains
encrypted only to the personal recovery recipient: its values are not
decryptable by the host, materialized as runtime files, or exported into an
environment. Add a narrowly scoped host recipient and runtime declarations
only when an unattended consumer exists.

`backblaze.yaml` is likewise an admin-only recovery source. It contains the
separate offline age identity for each cluster and the application keys that
can only list and read their corresponding etcd or OpenStack backup versions.
None is materialized by sops-nix or injected into a cluster. Each upload-only
credential has exactly one Flux-managed ciphertext source and cannot read,
list, delete, or administer the bucket. The regenerated B2 master key is never
committed.

A root `.env` is forbidden; its ignore rule is defense in depth, not a secret
storage mechanism. Use the SOPS editor above rather than
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
nix run .#sops --accept-flake-config -- updatekeys secrets/backblaze.yaml
nix run .#sops --accept-flake-config -- updatekeys secrets/cloud-hosts.yaml
nix run .#sops --accept-flake-config -- updatekeys secrets/kubernetes.yaml
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
