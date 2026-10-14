# Current external provider ownership

Workstation OpenTofu owns identity, Cloudflare DNS, NetBird policy and the
existing AWS mail infrastructure. `secrets/current-provider-state.sops.yaml`
contains their current states with original lineages. It is encrypted to the
personal age identity and the independent offline recovery identity. The
original `secrets/migration-state.sops.yaml` remains the source recovery archive.

`migration-provider-state PROVIDER --output PRIVATE_PATH` exports current
state to a new owner-only file. Use `--snapshot` explicitly to inspect the
historical source archive. Initialize the matching pinned provider root with
an explicit local backend path to the exported state. Check every plan before
applying; never apply a saved plan against the default empty backend. Encrypt
the resulting state back into the current snapshot and verify an independent
Backblaze download after each apply.

Identity serial 24 removes only the retired OpenStack and CAPI management
clients and renames the retained Kubernetes client in place. All eight retained
application client ID/secret pairs and the Kubernetes OIDC audience are
unchanged. The final identity plan is empty. DNS and NetBird plans are empty.
AWS EC2/EIP/RDS/S3 identities and the source revision remain preserved. AWS
policy/Lambda drift was reviewed separately and was not applied as part of
the address-only mail administration gateway correction.
