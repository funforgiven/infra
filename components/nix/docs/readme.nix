{ config, ... }:
let
  hostName = "parmigiano";
  host = config.dendritic.hosts.${hostName};
  user = config.users.${host.user};
  homeConfigurationName = "${user.username}@${hostName}";
in
{
  perSystem.files.file."README.md".text = ''
    # infra

    NixOS, Kubernetes, desktop and physical-network configuration for this
    homelab. Three NixOS/K3s servers run one Flux-managed cluster with direct
    Rook-Ceph storage. Independent AWS mail and external provider resources
    retain their declarative configuration and existing state.

    This migration branch is preparation only. Live installation and provider
    changes require the documented backup, restore and hardware gates.

    ## Repository map

    - `components/nix/`: NixOS/Home Manager modules, packages, checks and generated files.
    - `deployments/homelab/hosts/`: physical host inventory, declarative mirrored-SATA disko, NixOS networking, K3s and encrypted bootstrap.
    - `deployments/homelab/cluster/`: one semantic Flux dependency graph, infrastructure and apps.
    - `deployments/homelab/recovery/`: suspension overlay for restoring persistent data before applications start.
    - `components/homelab/providers/`: independent identity, Cloudflare DNS, AWS mail and NetBird OpenTofu configurations.
    - `components/homelab/operations/`: encrypted credential/state and migration inventory helpers.
    - `deployments/homelab/network/` and `components/homelab/network-automation/`: RouterOS/Omada/UniFi desired network state.
    - `docs/migration/`: architecture, complete source/PVC mapping, owner inputs, console qualification and migration evidence.
    - `secrets/`: SOPS ciphertext and secret recovery instructions.

    `outputs.nix` loads every Nix module below `components/nix/`. Edit generated
    `flake.nix`, `.gitignore`, `README.md`, `LICENSE` and `THIRD_PARTY_NOTICES.md`
    through their Nix sources, then run:

    ```sh
    nix run .#write-flake --accept-flake-config
    nix run .#write-files --accept-flake-config
    ```

    ## Local validation

    ```sh
    nix develop --accept-flake-config
    nix fmt --accept-flake-config
    nix flake check --no-build --accept-flake-config
    nix build .#checks.${host.system}.homelab-configuration --no-link --accept-flake-config
    nix run .#repository-secret-scan --accept-flake-config
    ```

    The homelab check combines strict native manifest validation, retained
    service tests, OpenTofu formatting, RouterOS syntax and shell checks.
    Full pinned Helm rendering and schema validation are documented in
    [VALIDATION.md](docs/migration/VALIDATION.md).

    Read-only evaluations of host and disk configuration:

    ```sh
    nix eval .#nixosConfigurations.pecorino.config.system.build.toplevel.drvPath
    nix eval --json .#diskoConfigurations.pecorino.disko.devices.disk --apply 'disks: builtins.mapAttrs (_: disk: disk.device) disks'
    nix eval .#nixosConfigurations.${hostName}.config.system.build.toplevel.drvPath
    nix eval .#homeConfigurations."${homeConfigurationName}".activationPackage.drvPath
    ```

    ## Secrets and execution

    The personal age identity at
    `${user.homeDirectory}/.config/sops/age/keys.txt` decrypts operator inputs.
    Keep its offline recovery copy. Cluster hosts use a dedicated age identity
    seeded during installation; existing Ed25519 SSH host identities remain
    encrypted in the host bootstrap. Flux has a separate age recipient.

    `migration-source-capture` reads the frozen old deployment into a new private
    directory outside Git and encrypts runtime/configuration/provider archives.
    It does not update the target or export application-volume bytes.

    Export archived provider state locally with the
    `migration-provider-state` app; never initialize an empty state for existing
    external resources. `render-cluster-credentials` refreshes concrete encrypted
    application Secrets from local enrollment inputs. Neither helper applies
    cluster or provider resources. `migration-certificate-bundle` exports the
    validated one-time TLS seed. `migration-volume-plan` renders claim transfer
    resources, and `migration-database-bootstrap` exports a private PostgreSQL
    bootstrap while application stages stay held.

    See [preparation acceptance](docs/migration/ACCEPTANCE.md),
    [migration status](docs/migration/PROGRESS.md),
    [architecture](docs/migration/ARCHITECTURE.md),
    [data migration](docs/migration/DATA-MIGRATION.md),
    [execution runbook](docs/migration/RUNBOOK.md),
    [complete inventory](docs/migration/INVENTORY.md),
    [owner execution inputs](docs/migration/DECISIONS-REQUIRED.md),
    [PiKVM console access](docs/migration/CONSOLE-ACCESS.md) and
    [secret recovery](secrets/README.md). Source disks, databases, certificates
    and Ceph monitor state must have verified independent recovery before any
    destructive installation. Keeping OSD disks alone is not a Ceph restore.

    The wallpaper remains at
    `${user.homeDirectory}/Pictures/Wallpapers/current.png`; after replacing
    it, refresh the lock with `nix flake update wallpaper --accept-flake-config`.

    ## Credits

    The Nix module layout follows
    [mightyiam's dendritic pattern](https://github.com/mightyiam/dendritic).
    Quickshell adaptations and licenses are recorded in `THIRD_PARTY_NOTICES.md`.
  '';
}
