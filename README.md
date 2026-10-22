# infra

NixOS, Kubernetes, desktop and physical-network configuration for this
homelab. Three NixOS/K3s servers run one Flux-managed cluster with direct
Rook-Ceph storage. AWS mail and external provider resources (identity, DNS,
NetBird) are managed by separate OpenTofu roots run from the workstation.

## Repository map

- `components/nix/`: NixOS/Home Manager modules, packages, checks and generated files.
- `deployments/homelab/hosts/`: physical host inventory, declarative mirrored-SATA disko, NixOS networking, K3s and encrypted bootstrap.
- `deployments/homelab/cluster/`: Flux dependency graph (`waves/`), infrastructure and apps.
- `deployments/homelab/recovery/`: Flux overlay that holds Ceph and stateful apps while restoring a cluster from backup.
- `components/homelab/providers/`: identity, Cloudflare DNS, AWS mail and NetBird OpenTofu configurations.
- `components/homelab/operations/`: credential rendering and provider-state helpers.
- `deployments/homelab/network/` and `components/homelab/network-automation/`: RouterOS/Omada/UniFi desired network state.
- `docs/`: [architecture](docs/ARCHITECTURE.md).
- `secrets/`: SOPS ciphertext and secret recovery instructions.

`outputs.nix` loads every Nix module below `components/nix/`. `flake.nix` is
generated from the inputs those modules declare; after changing an input, run:

```sh
nix run .#write-flake --accept-flake-config
```

## Local validation

```sh
nix develop --accept-flake-config
nix fmt --accept-flake-config
nix flake check --no-build --accept-flake-config
nix build .#checks.x86_64-linux.homelab-configuration --no-link --accept-flake-config
nix run .#repository-secret-scan --accept-flake-config
```

The homelab check combines strict native manifest validation, service
tests, OpenTofu formatting, RouterOS syntax and shell checks. It uses the
committed schema bundle and needs no decryption or network access.

Full pinned Helm rendering and schema validation need Python with
PyYAML/requests, Helm, Kustomize and SOPS. Refresh the public schema and
chart cache, then validate with decrypted Helm values:

```sh
python components/homelab/validation/refresh.py --cache /tmp/homelab-validation
python components/homelab/validation/validate.py --helm-cache /tmp/homelab-validation --decrypt
```

The cache holds only public upstream data, never decrypted values.
Pinned sources are described in
[the validation README](deployments/homelab/validation/README.md).

Read-only evaluations of host and disk configuration:

```sh
nix eval .#nixosConfigurations.pecorino.config.system.build.toplevel.drvPath
nix eval --json .#diskoConfigurations.pecorino.disko.devices.disk --apply 'disks: builtins.mapAttrs (_: disk: disk.device) disks'
nix eval .#nixosConfigurations.parmigiano.config.system.build.toplevel.drvPath
nix eval .#homeConfigurations."funforgiven@parmigiano".activationPackage.drvPath
```

## Secrets

The personal age identity at
`/home/funforgiven/.config/sops/age/keys.txt` decrypts operator inputs.
Keep its offline recovery copy. Cluster hosts use a dedicated age identity
seeded during installation, and Flux has a separate age recipient. Host SSH
identities are encrypted in `deployments/homelab/hosts/secrets.sops.yaml`.

`render-cluster-credentials` refreshes encrypted application Secrets from
local enrollment inputs; `provider-state` exports a provider's OpenTofu
state. Neither applies changes.

See [secret recovery](secrets/README.md) and
[architecture](docs/ARCHITECTURE.md).

## Wallpaper

The wallpaper is at
`/home/funforgiven/Pictures/Wallpapers/current.png`; after replacing
it, refresh the lock with `nix flake update wallpaper --accept-flake-config`.

## Credits

The Nix module layout follows
[mightyiam's dendritic pattern](https://github.com/mightyiam/dendritic).
Quickshell adaptations and licenses are recorded in `THIRD_PARTY_NOTICES.md`.
