# infra

Infrastructure configuration for the NixOS host `parmigiano` and the
surrounding homelab network.

`parmigiano` is built on NixOS unstable with Home Manager and the dendritic
module pattern. RouterOS deployment records cover the current router and
switching fabric. Cloud, cluster, and other platforms can be added when they
gain real configuration.

This is a concrete environment, not a reusable distribution. It can still
serve as a reference for a dendritic flake, a Niri desktop, declarative
PipeWire routing, SOPS secret delivery, or a device-oriented RouterOS layout.

## What It Configures Today

- AMD Ryzen desktop with an NVIDIA GPU
- Niri with a repository-owned Quickshell bar, dock, launcher, and mixer
- Fish for interactive use, with Bash available for scripts
- Home Manager profiles for command-line and graphical applications
- Four logical PipeWire/WirePlumber audio channels
- Turkish and Japanese input through Fcitx5 and Mozc
- Btrfs on NVMe through disko, with systemd-boot
- Wallpaper-derived colors shared through Matugen and Stylix
- SOPS/age for the account password hash, machine credentials, and
  homelab API/network credentials, with 1Password retained for desktop
  and browser password management
- RouterOS deployment records and tooling for a CCR2004 router and
  CRS510 switch

## Repository Layout

- `flake.nix` is generated; `outputs.nix` loads the Nix component tree.
- `components/nix/computers/` contains host facts and disk layout.
- `components/nix/funforgiven/` contains personal applications and desktop settings.
- `components/nix/hardware/` contains reusable hardware features.
- `components/nix/packages/` contains local packages and overlays.
- `components/nix/repository/` contains checks, formatting, and generated-file support.
- `components/nix/docs/` contains the sources for generated documentation.
- `components/routeros/` contains shared RouterOS validation, credential
  installation, and tests.
- `deployments/homelab/routeros/` contains device-specific router and
  switch identities, physical assignments, and secret-free `.rsc` records
  under each device's `applied/` directory.
- `secrets/` contains SOPS-encrypted machine and homelab credentials and
  their documentation.

`parmigiano` is assembled in `components/nix/computers/parmigiano.nix` by
selecting focused features and the user's Home Manager profiles.

Deployment identities and entry points belong under `deployments/`.
Implementations and reusable features remain under `components/`.
Directories are added only with their first real configuration.

## Dendritic Pattern

The Nix implementation follows the dendritic pattern from
`mightyiam/dendritic`: every Nix file under `components/nix/` is a top-level
flake-parts module, and feature modules register named NixOS and Home Manager
modules instead of importing distant paths directly.

## Homelab Network

RouterOS deployments are grouped by device identity:

```text
deployments/homelab/routeros/
├── core-router/
│   ├── applied/
│   └── install-pppoe.sh
└── core-switch/
    └── applied/
```

Each `applied/` directory contains selected, secret-free `.rsc` records
of one-shot changes that contributed to the current device state. They
are an audit trail, not a complete migration history, desired-state, or
convergence scripts. Every record aborts at its first executable line to
prevent accidental replay on a configured device.

Shared validation and credential tooling lives in `components/routeros/`.
Validate the records, shell entry point, and credential helper with:

```sh
components/routeros/validate.sh
```

Within Git, PPPoE and Omada values exist only as SOPS ciphertext in
`secrets/routeros.yaml` and `secrets/omada.yaml`. sops-nix materializes
the two PPPoE values for the current installer as user-owned `0400`
runtime files. The NixOS host is not an Omada recipient, so those
unused values remain recovery-key-only ciphertext. Device login
credentials, RouterOS exports, and binary backups are not committed.

The network plan, physical map, firewall policy, current transition
state, recovery paths, and remaining work are documented in the
[RouterOS deployment runbook](deployments/homelab/routeros/README.md).
This public repository treats internal addressing, device identities,
and port assignments as non-secret operational documentation; all
authentication material remains encrypted or outside Git.

## Local Files

The configuration relies on these files and identities outside Git:

- The wallpaper is expected at `/home/funforgiven/Pictures/Wallpapers/current.png`. Refresh its locked
  content after replacing it with:

  ```sh
  nix flake update wallpaper --accept-flake-config
  ```

- The complete personal age identity at
  `/home/funforgiven/.config/sops/age/keys.txt` is the recovery key
  for every SOPS secret and must be backed up securely.

- NixOS uses `/etc/ssh/ssh_host_ed25519_key` for unattended decryption.
  Backing it up is optional, but a replacement host key must be added as
  a recipient before installation.

See [`secrets/README.md`](secrets/README.md) for editing, recovery, and
rotation.

## Generated Files

`flake.nix`, `.gitignore`, `README.md`, `LICENSE`, and
`THIRD_PARTY_NOTICES.md` are generated. Edit their source modules, then run:

```sh
nix run .#write-flake --accept-flake-config
nix run .#write-files --accept-flake-config
```

The flake checks fail when a committed generated file is stale.

## Day-to-Day Use

Enter the development shell to install the checkout's pre-commit hook:

```sh
nix develop --accept-flake-config
```

Format and validate before rebuilding:

```sh
nix fmt --accept-flake-config
nix flake check --no-build --accept-flake-config
```

Apply the host configuration with:

```sh
sudo nixos-rebuild switch --flake .#parmigiano --accept-flake-config
```

A compositor update takes effect after logging out and back in. Once inside
the new Niri session, the deployed desktop and audio contracts can be checked
without changing state:

```sh
funforgiven-runtime-check
```

## Fresh Installation

The disko command below destroys the configured target disk. Read
`components/nix/computers/parmigiano-disko.nix` and verify the device path
first.

1. Provide the local wallpaper file described above.

2. Partition and mount the verified disk:

   ```sh
   sudo nix --experimental-features "nix-command flakes" run github:nix-community/disko -- \
     --mode destroy,format,mount --flake .#parmigiano
   ```

3. Restore the existing SSH host private key, or add a new host recipient
   as described in [`secrets/README.md`](secrets/README.md).

4. Install NixOS:

   ```sh
   sudo nixos-install --flake .#parmigiano
   ```

## Validation

Run the full flake evaluation and build the host and Home Manager outputs:

```sh
nix flake check --no-build --accept-flake-config
nix build \
  .#checks.x86_64-linux.parmigiano-home \
  .#checks.x86_64-linux.parmigiano-toplevel \
  --no-link --accept-flake-config
```

Useful targeted evaluations are:

```sh
nix eval .#diskoConfigurations.parmigiano.disko.devices.disk.main.device
nix eval .#nixosConfigurations.parmigiano.config.system.build.toplevel.drvPath
nix eval .#homeConfigurations."funforgiven@parmigiano".activationPackage.drvPath
```

## Credits

The Nix component architecture follows
[mightyiam's dendritic pattern](https://github.com/mightyiam/dendritic),
with [mightyiam/infra](https://github.com/mightyiam/infra) as its primary
reference configuration.

The Quickshell design draws on
[Noctalia v4](https://github.com/noctalia-dev/noctalia/tree/legacy-v4)
and [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell).

Exact snapshots and licenses for adapted source are recorded in
`THIRD_PARTY_NOTICES.md`.
