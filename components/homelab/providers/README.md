# External providers

These OpenTofu roots run from the workstation: `identity` (ZITADEL), `dns`
(Cloudflare), `netbird` (NetBird policy) and `mail-aws` (the paused AWS mail recovery infrastructure).
Their state lives in `secrets/current-provider-state.sops.yaml`, encrypted to
the personal and offline recovery age identities. Never start from an empty
state; the resources already exist.

To change a provider:

1. Export its state to a new owner-only file:
   `nix run .#provider-state -- PROVIDER --output /private/path/PROVIDER.tfstate`.
2. Run `tofu init` in the root, then `tofu plan -state=/private/path/PROVIDER.tfstate`
   and review the plan before applying it with the same `-state`.
3. Encrypt the updated state back into `secrets/current-provider-state.sops.yaml`
   and verify a Backblaze download of it.
4. Delete the plaintext state file.

The separate [mail-gcp root](mail-gcp/) keeps the live GCP stack's state in its
private versioned GCS backend. Its [operations guide](../services/mail-gcp/README.md)
covers deployment, mail checks, backups and recovery. Public DNS continues to
use the existing Cloudflare root and encrypted state above.
