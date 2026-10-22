# infra

Desired state for a homelab: a NixOS workstation, three NixOS servers running
one Flux-managed K3s cluster on Rook-Ceph, a NixOS mail host on AWS, external
services (ZITADEL, Cloudflare, NetBird, Backblaze) and the physical network.
[Architecture](docs/ARCHITECTURE.md) explains who owns what and why.

## Map

| Path | Contents | Applied by |
| --- | --- | --- |
| `components/nix/` | NixOS and Home Manager modules, packages and checks (the flake) | `nixos-rebuild` |
| `deployments/homelab/hosts/` | server inventory, disks, networking, K3s, host backups | `nixos-rebuild` per server |
| `deployments/homelab/cluster/` | everything in Kubernetes; `waves/stages.yaml` is the Flux graph | Flux, from `main` |
| `deployments/homelab/recovery/` | Flux overlay that holds stateful stages during a rebuild | by hand, see [recovery](docs/recovery.md) |
| `components/homelab/providers/` | OpenTofu roots for external services | `nix run .#tofu -- ROOT …` |
| `components/homelab/network-automation/`, `deployments/homelab/network/` | router and switch desired state | Ansible / Omada reconciler, see [network](docs/network.md) |
| `components/homelab/services/` | application code and tests shipped into the cluster or mail host | via the above |
| `components/homelab/operations/` | `cluster-access` (admin kubeconfig) and `identity-credentials` | `nix run .#…` |
| `secrets/` | workstation, network and recovery ciphertext | see [secrets](secrets/README.md) |

`outputs.nix` loads every module below `components/nix/`. `flake.nix` is
generated from the inputs those modules declare; after changing one, run
`nix run .#write-flake --accept-flake-config`.

## Common workflows

- Workstation: `sudo nixos-rebuild switch --flake .#parmigiano`.
- Servers: `nixos-rebuild switch --flake .#HOST` on the host or with
  `--target-host`; one host at a time.
- Cluster: commit to `main`; Flux applies it. Secrets are SOPS files beside
  their manifests.
- External services: `nix run .#tofu -- ROOT plan`, then `apply`, then commit
  the encrypted state ([providers](components/homelab/providers/README.md)).
- Secrets: `nix run .#sops -- FILE` ([secrets](secrets/README.md)).

## Validation

```sh
nix fmt
nix flake check
nix run .#repository-secret-scan
```

`nix flake check` builds every host and runs all repository checks without
network access to the cluster or decryption. `homelab-manifests` renders every
Kustomize entrypoint and HelmRelease and validates the output against
Kubernetes, KubeVirt and CRD schemas plus repository policies (Flux graph,
recovery holds, restore isolation, inventory copies). Charts and API schemas
are fetched by Nix from `deployments/homelab/validation/pins.json`; a
HelmRelease whose chart does not match its pin fails. To bump a chart, update
the HelmRelease and its pin (`url`/`ref`, and `sha256` from the build's `got:`
line), then rebuild. Vendored manifests are hash-checked through
`deployments/homelab/validation/vendors.json`. To validate a working tree
directly with Python (PyYAML, jsonschema), Helm and Kustomize on `PATH`:

```sh
python components/homelab/validation/validate.py --inputs \
  "$(nix build --print-out-paths .#checks.x86_64-linux.homelab-manifests.inputs)"
```

## Notes

- The flake's `wallpaper` input is a local path
  (`~/Pictures/Wallpapers/current.png`); after replacing the image run
  `nix flake update wallpaper`.
- The Nix module layout follows
  [mightyiam's dendritic pattern](https://github.com/mightyiam/dendritic).
  Adapted code and licences are listed in `THIRD_PARTY_NOTICES.md`.
