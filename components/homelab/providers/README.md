# External providers

These OpenTofu roots run from the workstation: `identity` (ZITADEL), `dns`
(Cloudflare), `netbird` (NetBird policy) and `mail-aws` (the AWS mail host).
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
