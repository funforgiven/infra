_: {
  home.gui =
    { lib, pkgs, ... }:
    let
      prismLauncher = pkgs.prismlauncher;
    in
    {
      assertions = [
        {
          assertion = lib.versionAtLeast prismLauncher.version "11.0.3";
          message = "Prism Launcher 11.0.3 or newer is required for current CurseForge imports.";
        }
      ];

      home.packages = [ prismLauncher ];
    };

  nixos.modules.minecraft =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      serviceName = "minecraft-exosphere-2-create";
      serviceUser = "minecraft-exosphere";
      stateDirectoryName = serviceName;
      stateDirectory = "/var/lib/${stateDirectoryName}";
      serverDirectory = "${stateDirectory}/server";
      consoleFifo = "/run/${serviceName}.stdin";
      serverPort = 25565;
      java = pkgs.jdk21_headless;

      # The modpack is an All Rights Reserved download fetched at build time;
      # neither its archive nor its contents are part of this repository.
      packVersion = "2.8.1";
      pack =
        pkgs.runCommandLocal "exosphere-2-create-server-${packVersion}"
          {
            src = pkgs.fetchurl {
              url = "https://www.curseforge.com/api/v1/mods/1530020/files/8446077/download";
              name = "exosphere-2-create-server-${packVersion}.zip";
              sha256 = "c46ef7d7e5fd4d319e912578de8d5c175330f29e74d24118c3c9ef442b769a42";
            };
            nativeBuildInputs = [ pkgs.unzip ];
          }
          ''
            unzip -q "$src" 'Exo2+create-${packVersion}-server/*'
            mv 'Exo2+create-${packVersion}-server' "$out"
          '';

      # Installs the pack once, then owns only the launcher, network and
      # startup settings; the world and other pack settings stay mutable.
      prepareServer = pkgs.writeShellApplication {
        name = "${serviceName}-prepare";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gawk
        ];
        text = ''
          server=${serverDirectory}
          marker="$server/.nix-managed-pack-version"

          if [[ ! -e $server ]]; then
            staging=$(mktemp -d "$server.XXXXXX")
            cp -rT --no-preserve=mode ${pack} "$staging"
            echo ${packVersion} >"$staging/.nix-managed-pack-version"
            mv -T "$staging" "$server"
          elif [[ ! -f $marker || $(<"$marker") != ${packVersion} ]]; then
            echo "$server is not pack ${packVersion}; back up the world and migrate the pack manually" >&2
            exit 1
          fi

          # set_key FILE KEY SEPARATOR VALUE replaces KEY's line or appends it.
          set_key() {
            touch "$1"
            awk -v key="$2" -v line="$2$3$4" '
              $0 ~ "^[[:space:]]*" key "[[:space:]]*=" { print line; found = 1; next }
              { print }
              END { if (!found) print line }
            ' "$1" >"$1.tmp"
            mv "$1.tmp" "$1"
          }

          # systemd owns the lifecycle and supplies the exact Java runtime.
          set_key "$server/variables.txt" WAIT_FOR_USER_INPUT = false
          set_key "$server/variables.txt" JAVA = '"${lib.getExe java}"'
          set_key "$server/variables.txt" JAVA_ARGS = '"-Xms10G -Xmx10G"'
          set_key "$server/variables.txt" RESTART = false
          set_key "$server/variables.txt" SKIP_JAVA_CHECK = false
          set_key "$server/variables.txt" SERVERSTARTERJAR_FORCE_FETCH = false

          # Online mode authenticates players; access is not allowlisted.
          set_key "$server/server.properties" server-ip = ""
          set_key "$server/server.properties" server-port = ${toString serverPort}
          set_key "$server/server.properties" online-mode = true
          set_key "$server/server.properties" enable-query = false
          set_key "$server/server.properties" enable-rcon = false
          set_key "$server/server.properties" white-list = false
          set_key "$server/server.properties" enforce-whitelist = false

          # Serialize early mod initialization to avoid the pack's Mixin/LibJF deadlock.
          set_key "$server/config/fml.toml" maxThreads " = " 1

          # Accepting the Minecraft EULA is part of enabling this feature.
          echo eula=true >"$server/eula.txt"
        '';
      };

      stopServer = pkgs.writeShellScript "${serviceName}-stop" ''
        echo stop >${consoleFifo}
        # Let Minecraft finish saving before systemd's final kill phase.
        while ${pkgs.coreutils}/bin/kill -0 "$1" 2>/dev/null; do
          ${pkgs.coreutils}/bin/sleep 1
        done
      '';
    in
    {
      users = {
        groups.${serviceUser} = { };

        users = {
          ${serviceUser} = {
            description = "Exosphere 2 + Create Minecraft server";
            isSystemUser = true;
            group = serviceUser;
            home = stateDirectory;
          };

          ${config.dendritic.primaryUser.username}.extraGroups = [ serviceUser ];
        };
      };

      networking.firewall.allowedTCPPorts = [ serverPort ];
      networking.firewall.allowedUDPPorts = [ serverPort ];

      systemd = {
        sockets.${serviceName} = {
          bindsTo = [ "${serviceName}.service" ];
          socketConfig = {
            ListenFIFO = consoleFifo;
            SocketMode = "0660";
            SocketUser = serviceUser;
            SocketGroup = serviceUser;
            RemoveOnStop = true;
            FlushPending = true;
          };
        };

        services.${serviceName} = {
          description = "Exosphere 2 + Create Minecraft server";
          wantedBy = [ "multi-user.target" ];
          wants = [ "network-online.target" ];
          requires = [ "${serviceName}.socket" ];
          after = [
            "network-online.target"
            "${serviceName}.socket"
          ];
          path = [
            pkgs.coreutils
            pkgs.curl
            pkgs.gawk
            pkgs.gnugrep
            java
          ];
          unitConfig = {
            StartLimitBurst = 3;
            StartLimitIntervalSec = "15min";
          };
          serviceConfig = {
            ExecStartPre = lib.getExe prepareServer;
            ExecStart = lib.escapeShellArgs [
              (lib.getExe pkgs.bash)
              "${serverDirectory}/start.sh"
            ];
            ExecStop = "${stopServer} $MAINPID";
            Restart = "always";
            RestartSec = "15s";
            TimeoutStartSec = "30min";
            TimeoutStopSec = "2min";

            User = serviceUser;
            Group = serviceUser;
            StateDirectory = stateDirectoryName;
            StateDirectoryMode = "0750";
            WorkingDirectory = stateDirectory;
            UMask = "0027";

            Environment = [
              "HOME=${stateDirectory}"
              "LC_ALL=C.UTF-8"
            ];
            StandardInput = "socket";
            StandardOutput = "journal";
            StandardError = "journal";

            CapabilityBoundingSet = "";
            LockPersonality = true;
            NoNewPrivileges = true;
            PrivateDevices = true;
            PrivateTmp = true;
            PrivateUsers = true;
            ProtectClock = true;
            ProtectControlGroups = true;
            ProtectHome = true;
            ProtectHostname = true;
            ProtectKernelLogs = true;
            ProtectKernelModules = true;
            ProtectKernelTunables = true;
            ProtectProc = "invisible";
            ProtectSystem = "strict";
            RestrictAddressFamilies = [
              "AF_UNIX"
              "AF_INET"
              "AF_INET6"
            ];
            RestrictNamespaces = true;
            RestrictRealtime = true;
            RestrictSUIDSGID = true;
            SystemCallArchitectures = "native";
          };
        };
      };
    };
}
