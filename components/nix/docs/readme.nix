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
    nix eval .#nixosConfigurations.${hostName}.config.system.build.toplevel.drvPath
    nix eval .#homeConfigurations."${homeConfigurationName}".activationPackage.drvPath
    ```

    ## Secrets

    The personal age identity at
    `${user.homeDirectory}/.config/sops/age/keys.txt` decrypts operator inputs.
    Keep its offline recovery copy. Cluster hosts use a dedicated age identity
    seeded during installation, and Flux has a separate age recipient. Host SSH
    identities are encrypted in `deployments/homelab/hosts/secrets.sops.yaml`.

    `render-cluster-credentials` refreshes encrypted application Secrets from
    local enrollment inputs; `provider-state` exports a provider's OpenTofu
    state. Neither applies changes.

    See [secret recovery](secrets/README.md) and
    [architecture](docs/ARCHITECTURE.md).

    ## World of Warcraft

    `components/nix/battle-net.nix` declares the shared UMU/Proton-CachyOS prefix,
    the `battlenet` and `wow-forever` launchers, and the Forever addon profile.
    `components/nix/packages/proton-cachyos.nix` pins the official x86_64 SLR
    release and its hash. Installation, Battle.net and WoW Forever all use
    that runner in `~/Games/world-of-warcraft`. Close Battle.net and WoW
    before applying a generation that changes Proton. Run `battlenet` to
    install or open Battle.net, `battlenet install` to rerun its installer,
    and `wow-forever` to launch the installed game directly.

    The instawow profile and direct-game shortcuts are inspired by
    [battlenet-umu](https://github.com/jacobjdowning/battlenet-umu), implemented
    locally without adding its flake. Two pinned upstream instawow patches
    add Forever support to the Nixpkgs package.

    The launcher declares browser hardware acceleration off after a CEF
    device-loss freeze coincided with an NVIDIA Xid 32 error. Before launch it
    merges that setting into Battle.net's private config, preserving login
    state and other preferences. It does not rewrite a running launcher's
    config. WoW uses its own graphics settings.

    Battle.net and its installer also pass `--in-process-gpu`, following
    [CachyOS's native Wayland workaround](https://github.com/CachyOS/proton-cachyos#proton-wayland-quirks)
    for blank white CEF windows in Proton 11. The direct WoW Forever launcher
    does not pass browser arguments.

    The shared prefix sets Wine Explorer's `ShowSystray` to `0`, hiding its
    standalone tray window on native Wayland. Battle.net stays accessible
    through its regular window and desktop launcher.

    The declared addons are What's Training?, Questie, Dungeon Quests Forever,
    Auctionator, OpenMap, Bagnon, Details! Damage Meter and FishFry Forever.
    `components/nix/battle-net/addons.lock.json` records exact release versions,
    public archive URLs, SHA-256 hashes and addon folders. Nix verifies and
    builds these archives, including QuestieDB, QuestieTrace, Bagnon's bundled
    BagBrother, bank and configuration modules, and the packaged Details!
    plugins. Bagnon is pinned from CurseForge because its GitHub repository
    publishes source without packaged releases.
    Home Manager links the declared folders into `_forever_/Interface/AddOns`.
    Rebuilds and rollbacks use the locked contents. Close WoW before activating
    a changed generation. Game preferences and character settings remain in
    `WTF`; Battle.net continues to manage the game client.

    To update an addon, resolve its Forever release with instawow or the
    publisher's release page, review the version, and update its lock entry.
    Hash the exact public archive with `nix store prefetch-file --json URL`.
    Keep every required addon folder in the lock. Rebuild to apply the reviewed
    changes; there is no background updater changing the live addon tree.

    The instawow `forever` profile uses `forever_classic` and a disposable
    directory under `~/.cache/instawow/forever`, so exploration cannot alter
    the Nix-managed game directory. API credentials support CurseForge
    discovery and optional GitHub authentication. Public pinned archive
    downloads do not require these credentials.

    Put the CurseForge key in the ignored mode-0600 intake file
    `secrets/INSTAWOW_CURSEFORGE_API_KEY.key`, then enroll it:

    ```sh
    nix run .#enroll-wow-addon-credentials --accept-flake-config -- --from-file
    ```

    Enrollment encrypts the credential into `secrets/instawow.json`, verifies
    decryption, and only then clears the intake file. An optional GitHub token
    uses `secrets/INSTAWOW_GITHUB_TOKEN.key` and the same command with `github`
    before `--from-file`. Without `--from-file`, enrollment prompts privately.
    Apply the host configuration after enrollment or rotation. sops-nix
    deploys the JSON as a private runtime file, and Home Manager manages
    `~/.config/instawow/config.access_tokens.json` as a link to it. The initial
    encrypted document has null providers until real credentials are enrolled.

    Validate the locked addon bundle and credential enrollment with:

    ```sh
    nix build .#checks.${host.system}.wow-addons .#checks.${host.system}.wow-addon-credentials --no-link --accept-flake-config
    ```

    ## Wallpaper

    The wallpaper is at
    `${user.homeDirectory}/Pictures/Wallpapers/current.png`; after replacing
    it, refresh the lock with `nix flake update wallpaper --accept-flake-config`.

    ## Credits

    The Nix module layout follows
    [mightyiam's dendritic pattern](https://github.com/mightyiam/dendritic).
    Quickshell adaptations and licenses are recorded in `THIRD_PARTY_NOTICES.md`.
  '';
}
