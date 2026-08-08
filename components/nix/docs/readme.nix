{ config, lib, ... }:
let
  hostName = "parmigiano";
  host = config.dendritic.hosts.${hostName};
  user = config.users.${host.user};
  homeConfigurationName = "${user.username}@${hostName}";
  wallpaperPath = config.dendritic.wallpaper.path;
in
{
  perSystem = psArgs: {
    text.readme = {
      order = [
        "intro"
        "overview"
        "layout"
        "dendritic"
        "routeros"
        "cloud"
        "local-files"
        "generated-files"
        "daily-use"
        "install"
        "checks"
        "credits"
      ];

      parts = {
        intro = ''
          # infra

          Infrastructure configuration for the NixOS host `${hostName}`, the
          surrounding homelab network, and a three-node OpenStack private cloud.

          `${hostName}` is built on NixOS unstable with Home Manager and the dendritic
          module pattern. Git-controlled automation covers the current RouterOS
          fabric. All three private-cloud hosts now pass the automated physical
          baseline and supervised failure of each LACP member. Independent
          OS-disk boot acceptance is a deferred resilience exercise. Kubernetes,
          Flux, Ceph, observability, private service ingress, MariaDB Galera, RabbitMQ,
          and the installed OpenStack services are qualified. The separate HA CAPI
          management cluster is recoverable, and Magnum has completed create, scale,
          worker-replacement, upgrade, Cinder/Manila storage, and clean-deletion
          qualification with a five-node Kubernetes canary.

          This is a concrete environment, not a reusable distribution. It can still
          serve as a reference for a dendritic flake, a Niri desktop, declarative
          PipeWire routing, SOPS secret delivery, or a device-oriented RouterOS layout.

        '';

        overview = ''
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
          - RouterOS desired state and reconciliation for a CCR2004 router and
            CRS510 switch
          - A three-node OpenStack cloud foundation with declarative physical
            networking and Ubuntu host automation

        '';

        layout = ''
          ## Repository Layout

          - `flake.nix` is generated; `outputs.nix` loads the Nix component tree.
          - `components/nix/computers/` contains host facts and disk layout.
          - `components/nix/${host.user}/` contains personal applications and desktop settings.
          - `components/nix/hardware/` contains reusable hardware features.
          - `components/nix/packages/` contains local packages and overlays.
          - `components/nix/repository/` contains checks, formatting, and generated-file support.
          - `components/nix/docs/` contains the sources for generated documentation.
          - `components/cloud/` contains the current Ubuntu host and physical-network
            automation.
          - `deployments/homelab/routeros/` contains the RouterOS runbook;
            `deployments/homelab/ssh-host-keys.json` pins managed-device identities.
          - `deployments/homelab/cloud/` contains the cloud architecture, exact
            version selections, host inventory, and network desired state.
          - `secrets/` contains SOPS-encrypted machine and homelab credentials and
            their documentation.

          `${hostName}` is assembled in `components/nix/computers/${hostName}.nix` by
          selecting focused features and the user's Home Manager profiles.

          Deployment identities and entry points belong under `deployments/`.
          Implementations and reusable features remain under `components/`.
          Directories are added only with their first real configuration.

        '';

        routeros = ''
          ## Homelab Network

          RouterOS desired state lives in the cloud network inventory and is
          reconciled by one Ansible playbook:

          ```text
          deployments/homelab/cloud/network-inventory.yaml
          components/cloud/network-automation/reconcile-routeros.yaml
          ```

          Its default run is read-only. Validate the current inventories, tests, and
          Ansible syntax without contacting a device with:

          ```sh
          nix build .#checks.${host.system}.cloud-configuration \
            --no-link --accept-flake-config
          ```

          RouterOS login passwords are SOPS ciphertext and sops-nix materializes
          only the two values consumed by Ansible as user-owned `0400` files. PPPoE
          values remain encrypted for future Terraform/REST adoption and have no
          runtime file or bespoke installer. Omada secrets are streamed to its manual
          reconciler only through standard input. Plaintext credentials, exports,
          historical command snapshots, plan files, and binary backups are not
          committed.

          The network plan, physical map, firewall policy, reconciled endpoint
          state, recovery paths, and remaining qualifications are documented in
          the [RouterOS deployment runbook](deployments/homelab/routeros/README.md).
          This public repository treats internal addressing, device identities,
          and port assignments as non-secret operational documentation; all
          authentication material remains encrypted or outside Git.

        '';

        cloud = ''
          ## OpenStack Private Cloud

          The target is a three-node hyperconverged cloud based on Ubuntu Noble,
          Kubespray, Cilium, Flux, Rook-Ceph, and upstream OpenStack-Helm. All three
          hosts are installed, managed, and pass automated host and network
          qualification, including failure of each LACP member. Kubernetes, Flux,
          Rook-Ceph, observability, service ingress, and the OpenStack-Helm
          MariaDB and RabbitMQ infrastructure charts are running. Keystone,
          Glance, Cinder, Placement, Nova, Neutron, Heat, Octavia, Manila, and
          Barbican are running. The three-node CAPI management cluster, its Flux root,
          CAPI/CAPO controllers, encrypted off-site etcd recovery, and Magnum are also
          running. Magnum's initial five-node canary passed its complete lifecycle
          through clean deletion. Production acceptance still requires the remaining
          destructive failure and recovery exercises documented in the cloud runbook.

          The current repository records:

          - a 2×25Gbps LACP trunk per node and isolated Ceph, migration, Geneve,
            and Manila service VLANs on the CRS510;
          - Ansible for unavoidable Ubuntu host state and RouterOS reconciliation;
          - a narrow Omada compatibility adapter for the controller API currently in use;
          - exact selected component versions and immutable Ceph image identity;
          - one OpenStack-Helm owner each for MariaDB Galera and RabbitMQ;
          - Cilium L2 service announcements with a mutually exclusive MetalLB
            rollback profile;
          - internal split-horizon CoreDNS and explicitly opt-in public Cloudflare
            records;
          - six NVMe Rook-Ceph OSDs and dedicated OpenStack/CephFS pools;
          - installation and major-upgrade ordering with semantic readiness gates;
          - a separately recoverable HA CAPI management cluster for Magnum;
          - backup requirements and destructive-operation boundaries.

          Start with the
          [cloud deployment runbook](deployments/homelab/cloud/README.md). Architecture
          records and version selections are desired state, not installation evidence.

          Validate the executable host/network automation and current inventories with:

          ```sh
          nix build .#checks.${host.system}.cloud-configuration \
            --no-link --accept-flake-config
          ```

        '';

        local-files = ''
          ## Local Files

          The configuration relies on these files and identities outside Git:

          - The wallpaper is expected at `${wallpaperPath}`. Refresh its locked
            content after replacing it with:

            ```sh
            nix flake update wallpaper --accept-flake-config
            ```

          - The complete personal age identity at
            `${user.homeDirectory}/.config/sops/age/keys.txt` is the recovery key
            for every SOPS secret and must be backed up securely.

          - NixOS uses `/etc/ssh/ssh_host_ed25519_key` for unattended decryption.
            Backing it up is optional, but a replacement host key must be added as
            a recipient before installation.

          See [`secrets/README.md`](secrets/README.md) for editing, recovery, and
          rotation.

        '';

        generated-files = ''
          ## Generated Files

          `flake.nix`, `.gitignore`, `README.md`, `LICENSE`, and
          `THIRD_PARTY_NOTICES.md` are generated. Edit their source modules, then run:

          ```sh
          nix run .#write-flake --accept-flake-config
          nix run .#write-files --accept-flake-config
          ```

          The flake checks fail when a committed generated file is stale.

        '';

        daily-use = ''
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
          sudo nixos-rebuild switch --flake .#${hostName} --accept-flake-config
          ```

          A compositor update takes effect after logging out and back in. Once inside
          the new Niri session, the deployed desktop and audio contracts can be checked
          without changing state:

          ```sh
          funforgiven-runtime-check
          ```

        '';

        install = ''
          ## Fresh Installation

          The disko command below destroys the configured target disk. Read
          `components/nix/computers/${hostName}-disko.nix` and verify the device path
          first.

          1. Provide the local wallpaper file described above.

          2. Partition and mount the verified disk:

             ```sh
             sudo nix --experimental-features "nix-command flakes" run github:nix-community/disko -- \
               --mode destroy,format,mount --flake .#${hostName}
             ```

          3. Restore the existing SSH host private key, or add a new host recipient
             as described in [`secrets/README.md`](secrets/README.md).

          4. Install NixOS:

             ```sh
             sudo nixos-install --flake .#${hostName}
             ```

        '';

        checks = ''
          ## Validation

          Run the full flake evaluation and build the host and Home Manager outputs:

          ```sh
          nix flake check --no-build --accept-flake-config
          nix build \
            .#checks.${host.system}.${hostName}-home \
            .#checks.${host.system}.${hostName}-toplevel \
            --no-link --accept-flake-config
          ```

          Useful targeted evaluations are:

          ```sh
          nix eval .#diskoConfigurations.${hostName}.disko.devices.disk.main.device
          nix eval .#nixosConfigurations.${hostName}.config.system.build.toplevel.drvPath
          nix eval .#homeConfigurations."${homeConfigurationName}".activationPackage.drvPath
          ```

        '';

        credits = ''
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

        '';
      };
    };

    files.file."README.md".text = lib.removeSuffix "\n\n" psArgs.config.text.readme + "\n";
  };
}
