# Credential enrollment and recovery

The single homelab cluster consumes concrete SOPS Secrets beside each workload.
Workstation enrollment inputs live here and in `secrets/service-runtime.sops.yaml`.
`runtime-contract.yaml` declares each input's destination, generation or external
provisioner. Host-only inputs are in `host-runtime`; they are not a Flux bundle.
Host NixOS/Flux age identities and preserved SSH keys have their own encrypted
bootstrap in `../hosts/secrets.sops.yaml`.

For migration, preserve the enrolled values. Follow
[DATA-MIGRATION.md](../../../docs/migration/DATA-MIGRATION.md) for the fresh
read-only source capture and [RUNBOOK.md](../../../docs/migration/RUNBOOK.md)
for the future outage. Restore runtime, signing, database, backup, OIDC, radio
and device identities before starting writers. Do not generate replacement
secrets or initialize a backup repository as part of an ordinary restore.

## Local encrypted updates

Run from the repository root with the operator age identity available. Inspect
the contract or a command's help before an intentional enrollment:

```sh
nix run .#runtime-contract -- --help
nix run .#enroll-services-credential -- --help
nix run .#generate-services-credential -- --help
nix run .#render-cluster-credentials
```

Enrollment reads secret values through the supported private input mechanism;
do not put values in arguments, tracing or terminal output. The renderer updates
encrypted concrete B2, monitoring, game and media inputs from local enrollment.
It preserves unrelated app keys and does not contact Kubernetes or a provider.
Review the resulting ciphertext/file changes before publishing a deployment.

For intentionally changed OIDC clients, feed the complete current retained
identity provider output through stdin:

```sh
tofu -chdir=components/homelab/providers/identity output -json | \
  nix run .#render-cluster-credentials -- --identity-outputs-stdin
```

Use the restored private provider backend, credentials and preserved lineage
as described in the runbook. That pipeline does not apply provider changes.
The renderer requires all eight client ID/secret pairs and updates Forgejo,
Grafana, media, Wallos, MAS's matching ZITADEL upstream and NetBird's independent
policy inputs. Existing app signing/session material and other MAS upstreams
remain intact. Incomplete outputs fail before decryption or writes.

## External provisioners and host delivery

Backblaze, Telegram, Resend and AWS credential helpers can call external APIs;
they are future intentional enrollment/rotation operations. Preserve existing
resource IDs, scoped credentials, bucket prefixes and Restic/Kopia passwords.
Independent AWS mail retains its existing AWS resources and encrypted state.
Never run `initialize-services-restic` over an existing repository as recovery.

`enroll-service-host-secrets` transfers a selected profile over verified SSH
using private stdin. It changes the destination host and is a future live step.
UniFi's migration cloud-init/runtime and backup inputs already contain its
preserved source identities; follow its [runbook](../cluster/apps/unifi/README.md).
For an intentionally added Matrix host producer, generate the scoped encrypted
input using `matrix-admin configure-alerting --phase dual --host HOST`, then
deliver the corresponding `matrix-monitoring:HOST` profile. Native runner host
enrollment is retired. Home automation's target credentials are mounted through
the Kubernetes deployment rather than an old standalone host.

Private source/provider archives under `secrets/` support review and recovery;
they are not manifests to apply wholesale. Use `migration-provider-state` and
`migration-certificate-bundle` for explicit owner-only exports. Gateway TLS/ACME
is seeded once; cert-manager subsequently owns certificate renewal. General
credential reconciliation does not reapply an old gateway private key.
