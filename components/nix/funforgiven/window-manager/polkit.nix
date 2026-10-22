{ lib, ... }:
{
  nixos.modules.polkit-agent =
    { config, ... }:
    let
      kdeSelected = config.dendritic.polkit.agent == "kde";
    in
    {
      # The Quickshell agent (see quickshell/polkit) replaces niri-flake's KDE unit.
      systemd.user.services.niri-flake-polkit = lib.mkMerge [
        { enable = kdeSelected; }
        (lib.mkIf kdeSelected {
          wantedBy = lib.mkForce [ "graphical-session.target" ];
          unitConfig = {
            ConditionEnvironment = "WAYLAND_DISPLAY";
            Requisite = "graphical-session.target";
          };
          serviceConfig.Slice = "session-graphical.slice";
        })
      ];

      assertions = [
        {
          assertion = config.programs.niri.enable;
          message = "The selected polkit agent requires the Niri system feature.";
        }
      ];
    };
}
