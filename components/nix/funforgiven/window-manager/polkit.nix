{ lib, ... }:
{
  nixos.modules.polkit-agent =
    { config, ... }:
    let
      kdeSelected = config.dendritic.polkit.agent == "kde";
    in
    {
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
        {
          assertion = config.systemd.user.services.niri-flake-polkit.enable == kdeSelected;
          message = "The KDE polkit unit must match dendritic.polkit.agent.";
        }
        {
          assertion =
            !kdeSelected
            || config.systemd.user.services.niri-flake-polkit.wantedBy == [ "graphical-session.target" ];
          message = "The KDE polkit unit must be owned by the UWSM graphical session.";
        }
      ];
    };
}
