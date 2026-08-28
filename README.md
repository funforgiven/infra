# infra

NixOS, desktop, network, and private-cloud configuration for this homelab.
Nix, OpenTofu, Flux, Kustomize, and SOPS hold desired state. Imperative tools
are limited to hardware changes, credential issuance, provider APIs without a
suitable provider, and recovery operations.

## Repository map

- `components/nix/` contains NixOS and Home Manager modules, packages, checks,
  and generated-file sources.
- `components/cloud/` contains reusable host, network, identity, DNS, and
  service infrastructure.
- `deployments/homelab/routeros/` contains the physical-network runbook.
- `deployments/homelab/cloud/` contains the OpenStack, Kubernetes, Flux, and
  service-cluster desired state.
- `secrets/` contains SOPS ciphertext and the secret-recovery runbook.

`outputs.nix` loads every Nix module below `components/nix/`. The generated
`flake.nix` declares inputs; host and feature selection lives in
`components/nix/computers/`.

## Common commands

Enter the development shell and install the repository pre-commit hook:

```sh
nix develop --accept-flake-config
```

Format and evaluate the repository:

```sh
nix fmt --accept-flake-config
nix flake check --no-build --accept-flake-config
```

Build all checks before merging a change:

```sh
nix flake check --accept-flake-config
```

Cloud checks are split by tool and can be built together or separately:

```sh
nix build .#checks.x86_64-linux.cloud-configuration \
  --no-link --accept-flake-config
nix build .#checks.x86_64-linux.cloud-kustomize \
  --no-link --accept-flake-config
```

Scan the working tree and Git history for plaintext secrets:

```sh
nix run .#repository-secret-scan --accept-flake-config
```

Apply the desktop host configuration:

```sh
sudo nixos-rebuild switch --flake .#parmigiano --accept-flake-config
```

## Local state and secrets

The personal age identity at
`/home/funforgiven/.config/sops/age/keys.txt` can decrypt every SOPS file
in this repository. Keep an offline backup.

NixOS uses `/etc/ssh/ssh_host_ed25519_key` for unattended decryption. Before
replacing that key, add its new age recipient to `.sops.yaml` and rekey the
affected files. See [secrets/README.md](secrets/README.md) for recovery,
editing, and rotation.

The wallpaper is expected at
`/home/funforgiven/Pictures/Wallpapers/current.png`. After replacing it,
refresh the locked content with:

```sh
nix flake update wallpaper --accept-flake-config
```

## Generated files

`flake.nix`, `.gitignore`, `README.md`, `LICENSE`, and
`THIRD_PARTY_NOTICES.md` are generated. Edit their Nix sources and then run:

```sh
nix run .#write-flake --accept-flake-config
nix run .#write-files --accept-flake-config
```

Do not edit generated files by hand.

## Fresh installation

The disko command below destroys the disk selected in
`components/nix/computers/parmigiano-disko.nix`. Verify that path first.

1. Partition and mount the target disk:

   ```sh
   sudo nix run .#disko --accept-flake-config -- \
     --mode destroy,format,mount --flake .#parmigiano
   ```

2. Restore the existing SSH host private key, or add the replacement host as
   a SOPS recipient.

3. Install NixOS:

   ```sh
   sudo nixos-install --flake .#parmigiano
   ```

Useful non-destructive evaluations are:

```sh
nix eval .#diskoConfigurations.parmigiano.disko.devices.disk.main.device
nix eval .#nixosConfigurations.parmigiano.config.system.build.toplevel.drvPath
nix eval .#homeConfigurations."funforgiven@parmigiano".activationPackage.drvPath
```

## Operations

- [RouterOS topology and recovery](deployments/homelab/routeros/README.md)
- [Cloud topology and operations](deployments/homelab/cloud/README.md)
- [Service catalog](deployments/homelab/cloud/services/README.md)
- [Secret recovery and rotation](secrets/README.md)
- [Audio routing](components/nix/audio-channels/README.md)
- [Quickshell behavior and manual tests](components/nix/funforgiven/window-manager/quickshell/README.md)

## Credits

The Nix module layout follows
[mightyiam's dendritic pattern](https://github.com/mightyiam/dendritic).
Quickshell work draws on Noctalia v4 and DankMaterialShell. Exact adapted
snapshots and licenses are recorded in `THIRD_PARTY_NOTICES.md`.
