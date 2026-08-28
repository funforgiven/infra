{ inputs, ... }:
let
  niriPackage =
    pkgs:
    pkgs.niri.overrideAttrs (previous: {
      patches = (previous.patches or [ ]) ++ [ ./patches/niri-focus-window-no-pointer-warp.patch ];
    });
in
{
  dendritic.nixpkgs.overlays = [ inputs.niri.overlays.niri ];

  homeManager.standaloneModules.niri.imports = [
    inputs.niri.homeModules.config
    inputs.niri.homeModules.stylix
  ];

  nixos.modules.niri =
    { pkgs, ... }:
    {
      imports = [ inputs.niri.nixosModules.niri ];

      programs.niri = {
        enable = true;
        package = niriPackage pkgs;
      };

      programs.uwsm = {
        enable = true;
        waylandCompositors.niri = {
          prettyName = "Niri";
          comment = "Niri managed by UWSM";
          binPath = "/run/current-system/sw/bin/niri";
          # UWSM owns the process and target lifecycle. Niri still needs its
          # session mode to export compositor environment and provide its
          # org.freedesktop.ScreenSaver idle-inhibit bridge for portals.
          extraArgs = [ "--session" ];
        };
      };
    };

  home.gui =
    { lib, pkgs, ... }:
    {
      home.packages = [ pkgs.wl-clipboard ];

      programs.niri = {
        package = niriPackage pkgs;

        settings = {
          # UWSM owns the graphical-session targets, while Niri supplies the
          # compositor-created Wayland and IPC variables at readiness.
          spawn-at-startup = [
            {
              argv = [
                (lib.getExe pkgs.uwsm)
                "finalize"
              ];
            }
          ];

          prefer-no-csd = true;
          screenshot-path = "~/Pictures/Screenshots/Screenshot from %Y-%m-%d %H-%M-%S.png";

          cursor = {
            hide-when-typing = true;
          };

          gestures.hot-corners.enable = false;

          xwayland-satellite.path = lib.getExe pkgs.xwayland-satellite-unstable;
        };
      };
    };
}
