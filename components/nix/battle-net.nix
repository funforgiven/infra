_: {
  home.gui =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      # Reuse the existing Battle.net installation. This prefix can hold
      # any Battle.net game, regardless of its original directory name.
      prefix = "${config.home.homeDirectory}/Games/world-of-warcraft";
      executable = "${prefix}/drive_c/Program Files (x86)/Battle.net/Battle.net.exe";
      registryExecutable = "${prefix}/drive_c/windows/system32/reg.exe";
      userRegistry = "${prefix}/user.reg";
      # Wine defaults to 96 DPI instead of inheriting the Wayland scale.
      dpi = builtins.floor (96 * (config.dendritic.niri.outputs.primary.scale or 1));

      # Use the compatibility-tool output of the flake-pinned GE-Proton.
      proton = pkgs.proton-ge-bin.steamcompattool;
      settings = {
        inherit prefix;
        proton = toString proton;
        exe = executable;
        game_id = "umu-default";
        store = "battlenet";
      };
      configuration = (pkgs.formats.toml { }).generate "battlenet.toml" { umu = settings; };
      launcher = pkgs.writeShellApplication {
        name = "battlenet";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.curl
          pkgs.gawk
          pkgs.umu-launcher
        ];
        text = ''
          install=false
          case "''${1:-}" in
            "") ;;
            install) install=true ;;
            -h|--help)
              printf 'Usage: battlenet [install]\n\nOpen Battle.net to install or play your games.\n'
              printf 'The first launch installs Battle.net; install reruns its installer.\n'
              exit 0
              ;;
            *)
              printf 'Usage: battlenet [install]\n' >&2
              exit 2
              ;;
          esac
          if [ "$#" -gt 1 ]; then
            printf 'Usage: battlenet [install]\n' >&2
            exit 2
          fi

          export WINEPREFIX=${lib.escapeShellArg settings.prefix}
          export PROTONPATH=${lib.escapeShellArg settings.proton}
          export GAMEID=${lib.escapeShellArg settings.game_id}
          export STORE=${lib.escapeShellArg settings.store}

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
            umu-run "$installer" --installpath='C:\Program Files (x86)\Battle.net' --lang=enUS
            exit 0
          fi

          exec umu-run --config ${configuration}
        '';
      };
    in
    {
      home.packages = [ launcher ];
      xdg.configFile."umu/battlenet.toml".source = configuration;

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
