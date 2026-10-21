# Credential enrollment and recovery

The single homelab cluster consumes concrete SOPS Secrets beside each workload.
Workstation enrollment inputs live here and in `secrets/service-runtime.sops.yaml`.
`runtime-contract.yaml` declares each input's destination, generation or external
provisioner. Host-only inputs are in `host-runtime`; they are not a Flux bundle.
Host and Flux age identities are in `../../../secrets/kubernetes.yaml`; host SSH
keys are in `../hosts/secrets.sops.yaml`.

On restore, reuse the enrolled values; do not generate replacement secrets or
initialize backup repositories. Restore runtime, signing, database, backup,
OIDC, radio and device identities before starting writers.

## Local encrypted updates

Run from the repository root with the operator age identity available. Inspect
the contract or a command's help before an enrollment:

```sh
nix run .#runtime-contract -- --help
nix run .#enroll-services-credential -- --help
nix run .#generate-services-credential -- --help
nix run .#render-cluster-credentials
```

Enrollment reads secret values through the supported private input mechanism;
do not put values in arguments, tracing or terminal output. The renderer updates
encrypted concrete B2 (Velero and NetBird Barman), monitoring, game and media
inputs from local enrollment.
It keeps unrelated app keys and does not contact Kubernetes or a provider.
Review the resulting ciphertext/file changes before publishing a deployment.

For changed OIDC clients, feed the complete identity OpenTofu outputs through
stdin:

```sh
tofu -chdir=components/homelab/providers/identity output -json | \
  nix run .#render-cluster-credentials -- --identity-outputs-stdin
```

Set up the provider backend as described in the
[providers README](../../../components/homelab/providers/README.md). That
pipeline does not apply provider changes.
The renderer requires all seven client ID/secret pairs and updates Forgejo,
Grafana, media, MAS's matching ZITADEL upstream and NetBird's policy
inputs. App signing/session material and other MAS upstreams are left
unchanged. Incomplete outputs fail before decryption or writes.

## External provisioners and host delivery

Backblaze, Telegram, Resend and AWS credential helpers call external APIs;
they create or rotate external credentials. Keep resource IDs, scoped
credentials, bucket prefixes and Restic/Kopia passwords stable. Never run
`initialize-services-restic` over an existing repository as recovery.

`enroll-service-host-secrets` transfers a selected profile over verified SSH
using private stdin and changes the destination host. UniFi's guest identity
and backup inputs are documented in its [runbook](../cluster/apps/unifi/README.md).
Home automation's credentials
are mounted through its Kubernetes deployment.

cert-manager owns gateway TLS renewal.
