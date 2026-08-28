_: {
  home.gui =
    { lib, pkgs, ... }:
    let
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
      systemd.user.services = {
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
