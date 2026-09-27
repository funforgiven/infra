_: {
  home.gui =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      chatLayout = pkgs.writeShellApplication {
        name = "niri-chat-layout";
        text = ''
          exec ${lib.getExe pkgs.python3} ${./chat-layout.py} \
            --niri ${lib.getExe config.programs.niri.package} "$@"
        '';
      };

      graphicalApplicationService =
        {
          command,
          description,
        }:
        {
          Unit = {
            Description = description;
            PartOf = [ "graphical-session.target" ];
            ConditionEnvironment = [
              "WAYLAND_DISPLAY"
              "NIRI_SOCKET"
            ];
            After = [
              "graphical-session.target"
              "quickshell.service"
            ];
            Wants = [ "quickshell.service" ];
            Requisite = [ "graphical-session.target" ];
          };
          Service = {
            ExecStart = command;
            # Signal the application leader first so multi-process clients can
            # flush state and retire their children before systemd's bounded
            # final cgroup cleanup.
            KillMode = "mixed";
            Slice = "app-graphical.slice";
          };
          Install.WantedBy = [ "graphical-session.target" ];
        };
    in
    {
      home.packages = [ chatLayout ];

      systemd.user.services = {
        niri-chat-layout = {
          Unit = {
            Description = "Stack Telegram above Discord on the right monitor";
            PartOf = [ "graphical-session.target" ];
            Requisite = [ "graphical-session.target" ];
            ConditionEnvironment = "NIRI_SOCKET";
            After = [
              "graphical-session.target"
              "discord.service"
              "telegram.service"
            ];
            Wants = [
              "discord.service"
              "telegram.service"
            ];
          };
          Service = {
            Type = "oneshot";
            ExecStart = lib.getExe chatLayout;
            TimeoutStartSec = 130;
            RemainAfterExit = true;
            Slice = "session-graphical.slice";
          };
          Install.WantedBy = [ "graphical-session.target" ];
        };

        discord = graphicalApplicationService {
          description = "Discord";
          command = lib.getExe pkgs.discord;
        };

        telegram = graphicalApplicationService {
          description = "Telegram Desktop";
          command = lib.getExe pkgs.telegram-desktop;
        };

        "1password" = graphicalApplicationService {
          description = "1Password";
          command = "${lib.getExe pkgs._1password-gui} --silent";
        };

        steam = graphicalApplicationService {
          description = "Steam";
          command = "${lib.getExe pkgs.steam} -silent";
        };
      };
    };
}
