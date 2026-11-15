{ lib, ... }:
let
  addonLock = builtins.fromJSON (builtins.readFile ./battle-net/addons.lock.json);
  addonFolders = lib.concatMap (addon: addon.folders) (builtins.attrValues addonLock.addons);
  mkAddons =
    pkgs:
    pkgs.runCommand "wow-forever-addons"
      {
        nativeBuildInputs = [ pkgs.unzip ];
        passthru.lock = addonLock;
      }
      (
        ''
          mkdir -p "$out"
        ''
        + lib.concatStrings (
          lib.mapAttrsToList (
            name: addon:
            let
              archive = pkgs.fetchurl {
                name = "${name}-${addon.version}.zip";
                inherit (addon) url hash;
              };
            in
            ''
              mkdir ${lib.escapeShellArg name}
              unzip -q ${archive} -d ${lib.escapeShellArg name}
            ''
            + lib.concatMapStrings (folder: ''
              test -d ${lib.escapeShellArg "${name}/${folder}"}
              cp -a ${lib.escapeShellArg "${name}/${folder}"} "$out"/
            '') addon.folders
          ) addonLock.addons
        )
      );
in
{
  perSystem =
    { pkgs, ... }:
    {
      packages.wow-addons = mkAddons pkgs;
    };

  home.gui =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      # This prefix can hold any Battle.net game, regardless of its
      # original directory name.
      prefix = "${config.home.homeDirectory}/Games/world-of-warcraft";
      executable = "${prefix}/drive_c/Program Files (x86)/Battle.net/Battle.net.exe";
      registryExecutable = "${prefix}/drive_c/windows/system32/reg.exe";
      userRegistry = "${prefix}/user.reg";
      wowDirectory = "${prefix}/drive_c/Program Files (x86)/World of Warcraft";
      addonDirectory = "${wowDirectory}/_forever_/Interface/AddOns";
      stagingDirectory = "${config.xdg.cacheHome}/instawow/forever/Interface/AddOns";
      addons = mkAddons pkgs;
      wowProfiles.forever = {
        executable = "${wowDirectory}/_forever_/Wow.exe";
        addon_dir = stagingDirectory;
        inherit (addonLock) flavour;
      };
      json = pkgs.formats.json { };
      clientSettings = json.generate "battlenet-client-settings.json" {
        # CEF lost its D3D11 device alongside an NVIDIA Xid 32 fault. Keep
        # the launcher browser off the GPU; games have their own renderer.
        HardwareAcceleration = "false";
      };
      # Wine defaults to 96 DPI instead of inheriting the Wayland scale.
      dpi = builtins.floor (96 * (config.dendritic.niri.outputs.primary.scale or 1));

      # Share the pinned CachyOS runner across installation and both launchers.
      proton = pkgs.proton-cachyos-bin.steamcompattool;
      settings = {
        inherit prefix;
        proton = toString proton;
        exe = executable;
        game_id = "umu-default";
        store = "battlenet";
      };
      # CachyOS 11 removed the automatic CEF Wayland workaround. Battle.net
      # needs its GPU process in-process even with hardware acceleration off.
      browserArguments = [ "--in-process-gpu" ];
      configuration = (pkgs.formats.toml { }).generate "battlenet.toml" {
        umu = settings // {
          launch_args = browserArguments;
        };
      };
      foreverConfiguration = (pkgs.formats.toml { }).generate "wow-forever.toml" {
        umu = settings // {
          exe = wowProfiles.forever.executable;
        };
      };
      launcher = pkgs.writeShellApplication {
        name = "battlenet";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.curl
          pkgs.gawk
          pkgs.python3
          pkgs.umu-launcher
        ];
        text = ''
          install=false
          game=battlenet
          case "''${1:-}" in
            "") ;;
            install) install=true ;;
            forever) game=forever ;;
            -h|--help)
              printf 'Usage: battlenet [install|forever]\n\nOpen Battle.net to install or play your games.\n'
              printf 'The first launch installs Battle.net; install reruns its installer.\n'
              printf 'forever launches the installed WoW Forever client directly.\n'
              exit 0
              ;;
            *)
              printf 'Usage: battlenet [install|forever]\n' >&2
              exit 2
              ;;
          esac
          if [ "$#" -gt 1 ]; then
            printf 'Usage: battlenet [install|forever]\n' >&2
            exit 2
          fi

          export WINEPREFIX=${lib.escapeShellArg settings.prefix}
          export PROTONPATH=${lib.escapeShellArg settings.proton}
          export GAMEID=${lib.escapeShellArg settings.game_id}
          export STORE=${lib.escapeShellArg settings.store}
          # Xwayland cannot move Battle.net's client-drawn windows and
          # misplaces its dialogs. Its games inherit native Wayland too.
          export PROTON_ENABLE_WAYLAND=1

          # Initialize a fresh prefix before applying its declared DPI.
          if [ ! -f ${lib.escapeShellArg registryExecutable} ]; then
            umu-run ""
          fi
          # Only write DPI when it changes. runinprefix also works while
          # another application is running in this prefix.
          if [ ! -f ${lib.escapeShellArg userRegistry} ] || ! awk -v expected=${toString dpi} '
            /^\[/ { desktop = ($0 ~ /^\[Control Panel\\\\Desktop\]/) }
            desktop && /^"LogPixels"=dword:/ {
              split($0, value, ":")
              current = (strtonum("0x" value[2]) == expected)
            }
            END { exit !current }
          ' ${lib.escapeShellArg userRegistry}; then
            PROTON_VERB=runinprefix \
              umu-run ${lib.escapeShellArg registryExecutable} \
              add 'HKCU\Control Panel\Desktop' /v LogPixels \
              /t REG_DWORD /d ${toString dpi} /f
          fi

          # Native Wayland otherwise shows Wine's standalone tray as a tiny
          # floating window. Keep this preference in the shared game prefix.
          if [ ! -f ${lib.escapeShellArg userRegistry} ] || ! awk '
            /^\[/ { explorer = ($0 ~ /^\[Software\\\\Wine\\\\Explorer\]/) }
            explorer && /^"ShowSystray"=dword:00000000$/ { hidden = 1 }
            END { exit !hidden }
          ' ${lib.escapeShellArg userRegistry}; then
            PROTON_VERB=runinprefix \
              umu-run ${lib.escapeShellArg registryExecutable} \
              add 'HKCU\Software\Wine\Explorer' /v ShowSystray \
              /t REG_DWORD /d 0 /f
          fi

          if [ "$game" = battlenet ]; then
            python3 ${./battle-net/prepare_client.py} \
              ${lib.escapeShellArg prefix} ${clientSettings}
          fi

          if "$install" || [ ! -f ${lib.escapeShellArg executable} ]; then
            # Blizzard's bootstrapper and game data are runtime downloads,
            # outside the Nix store. Always install into the launch prefix.
            # UMU's Nix FHS environment has a private /tmp. Keep the
            # bootstrapper in the shared home directory so it stays visible.
            installer_cache=${lib.escapeShellArg "${config.xdg.cacheHome}/battlenet"}
            mkdir -p -- "$installer_cache"
            installer_directory="$(mktemp -d "$installer_cache/installer.XXXXXXXX")"
            trap 'rm -rf -- "$installer_directory"' EXIT
            installer="$installer_directory/Battle.net-Setup.exe"
            curl --fail --location --show-error --retry 3 \
              --output "$installer" \
              'https://downloader.battle.net/download/getInstallerForGame?os=win&gameProgram=BATTLENET_APP&version=Live'
            umu-run "$installer" ${lib.escapeShellArgs browserArguments} \
              --installpath='C:\Program Files (x86)\Battle.net' --lang=enUS
            exit 0
          fi

          if [ "$game" = forever ]; then
            if [ ! -f ${lib.escapeShellArg wowProfiles.forever.executable} ]; then
              printf 'Install WoW Forever through Battle.net first: battlenet\n' >&2
              exit 1
            fi
            exec umu-run --config ${foreverConfiguration}
          fi

          exec umu-run --config ${configuration}
        '';
      };
      foreverLauncher = pkgs.writeShellApplication {
        name = "wow-forever";
        text = ''
          exec ${lib.getExe launcher} forever "$@"
        '';
      };
    in
    {
      assertions = [
        {
          assertion = addonLock.schemaVersion == 1 && addonLock.flavour == "forever_classic";
          message = "The WoW addon lock must use the supported Forever schema.";
        }
        {
          assertion = builtins.length addonFolders == builtins.length (lib.unique addonFolders);
          message = "Locked WoW addon archives must not claim the same folder.";
        }
      ];

      home.packages = [
        launcher
        foreverLauncher
        pkgs.instawow
      ];
      home.file = lib.listToAttrs (
        map (folder: {
          name = "${addonDirectory}/${folder}";
          value.source = "${addons}/${folder}";
        }) addonFolders
      );

      # instawow resolves candidate releases in a disposable staging profile.
      # Only the Nix lock controls the folders linked into the live game.
      home.activation.instawowStaging = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p ${lib.escapeShellArg stagingDirectory}
      '';
      xdg.configFile = {
        "umu/battlenet.toml".source = configuration;
        "umu/wow-forever.toml".source = foreverConfiguration;
        "instawow/config.json".source = json.generate "instawow-config.json" {
          auto_update_check = false;
        };
      }
      // lib.mapAttrs' (name: profile: {
        name = "instawow/profiles/${name}/config.json";
        value.source = json.generate "instawow-${name}.json" {
          profile = name;
          inherit (profile) addon_dir;
          flavour_override = profile.flavour;
        };
      }) wowProfiles;

      xdg.desktopEntries.wow-forever = {
        name = "World of Warcraft: Forever";
        comment = "Play WoW Forever with the Battle.net Wine prefix";
        exec = lib.getExe foreverLauncher;
        icon = "applications-games";
        categories = [ "Game" ];
        terminal = false;
      };

      xdg.desktopEntries.battlenet = {
        name = "Battle.net";
        comment = "Install and play Battle.net games";
        exec = lib.getExe launcher;
        icon = "applications-games";
        categories = [ "Game" ];
        terminal = false;
        actions.install = {
          name = "Install or repair Battle.net";
          exec = "${lib.getExe launcher} install";
        };
      };
    };
}
