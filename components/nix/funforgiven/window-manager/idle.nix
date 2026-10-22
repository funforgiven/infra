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
      quickshell = lib.getExe' config.programs.quickshell.package "qs";
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
      deactivateOverlay = ipc "deactivate";
    in
    {
      programs.niri.settings.cursor.hide-after-inactive-ms = 30000;

      services.swayidle = {
        enable = true;
        package = pkgs.swayidle.override { systemdSupport = false; };
        extraArgs = [ "-w" ];
        systemdTargets = [ "graphical-session.target" ];
        timeouts = [
          {
            timeout = 120;
            command = ipc "activate";
            resumeCommand = deactivateOverlay;
          }
        ];
      };

      systemd.user.services.swayidle = {
        Unit = {
          After = [ "quickshell.service" ];
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
