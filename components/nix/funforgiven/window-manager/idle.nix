{ config, ... }:
let
  configName = config.dendritic.quickshell.configName;
in
{
  home.gui =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      idleTimeoutSeconds = 120;
      cursorHideDelayMilliseconds = 30000;
      # Disabled after repeated occupied reports from an empty desk.
      deskPresenceEnabled = false;
      quickshell = lib.getExe' config.programs.quickshell.package "qs";
      presencePython = pkgs.python3.withPackages (ps: [ ps.websocket-client ]);
      swayidle = pkgs.swayidle.override {
        systemdSupport = false;
      };
      ipc =
        action:
        lib.escapeShellArgs [
          quickshell
          "-c"
          configName
          "ipc"
          "call"
          "amoled"
          action
        ];
      activateOverlay = ipc "activate";
      deactivateOverlay = ipc "deactivate";
      idleTimeouts = [
        {
          # Wake on input even when presence blanked the screen before the
          # fallback timeout. This timeout itself never blanks the screen.
          timeout = 1;
          command = "${pkgs.coreutils}/bin/true";
          resumeCommand = deactivateOverlay;
        }
        {
          timeout = idleTimeoutSeconds;
          command = activateOverlay;
          resumeCommand = deactivateOverlay;
        }
      ];
    in
    {
      programs.niri.settings.cursor.hide-after-inactive-ms = cursorHideDelayMilliseconds;

      services.swayidle = {
        enable = true;
        package = swayidle;
        extraArgs = [ "-w" ];
        systemdTargets = [ "graphical-session.target" ];
        timeouts = idleTimeouts;
      };

      assertions = [
        {
          assertion = config.services.swayidle.extraArgs == [ "-w" ];
          message = "The AMOLED idle daemon must keep swayidle's wait mode enabled.";
        }
        {
          assertion = config.services.swayidle.timeouts == idleTimeouts;
          message = "The AMOLED idle daemon must retain input wake and the two-minute inactivity timeout.";
        }
        {
          assertion =
            config.programs.niri.settings.cursor.hide-after-inactive-ms == cursorHideDelayMilliseconds;
          message = "Niri must hide the cursor after 30 seconds of inactivity.";
        }
        {
          assertion = lib.filterAttrs (_: command: command != null) config.services.swayidle.events == { };
          message = "The AMOLED idle daemon must not add lock, suspend, or resume event commands.";
        }
      ];

      systemd.user.services.desk-presence = lib.mkIf deskPresenceEnabled {
        Unit = {
          Description = "Fahrican Loft desk presence screen control";
          # This target also wants the reader. Ordering explicitly after it
          # prevents its default ordering from putting us before the session,
          # while Quickshell and our graphical slice must start after it.
          After = [
            "graphical-session.target"
            "quickshell.service"
          ];
          Wants = [ "quickshell.service" ];
          PartOf = [ "graphical-session.target" ];
          Requisite = [ "graphical-session.target" ];
        };
        Service = {
          ExecStart = lib.escapeShellArgs [
            "${presencePython}/bin/python3"
            "${./desk-presence/reader.py}"
            "--url"
            "wss://home.fahrican.com/api/websocket"
            "--entity"
            "binary_sensor.0x54ef4410017220eb_presence"
            "--quickshell"
            quickshell
            "--config"
            configName
          ];
          LoadCredential = [ "ha-token:/run/secrets/home-assistant-presence-token" ];
          ExecStopPost = "-${ipc "updatePresence"} unknown";
          Restart = "always";
          RestartSec = 5;
          NoNewPrivileges = true;
          RestrictSUIDSGID = true;
          UMask = "0077";
          Slice = "background-graphical.slice";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };

      systemd.user.services.swayidle = {
        Unit = {
          After = [
            "quickshell.service"
          ];
          Wants = [ "quickshell.service" ];
          Requisite = [ "graphical-session.target" ];
        };

        Service = {
          ExecCondition = [ "${lib.getExe config.programs.niri.package} msg --json version" ];
          ExecStopPost = "-${deactivateOverlay}";
          Restart = lib.mkForce "on-failure";
          RestartSec = 1;
          Slice = "background-graphical.slice";
          TimeoutStopSec = "10s";
        };
      };
    };
}
