_: {
  nixos.modules.niri-portals =
    { config, pkgs, ... }:
    {
      programs.fuse.enable = true;

      assertions = [
        {
          assertion = config.programs.fuse.enable;
          message = "The desktop portal feature requires the NixOS FUSE wrappers.";
        }
      ];

      xdg = {
        portal = {
          enable = true;
          xdgOpenUsePortal = true;
          extraPortals = [
            pkgs.kdePackages.xdg-desktop-portal-kde
            pkgs.xdg-desktop-portal-gtk
          ];
          config = {
            niri = {
              default = [
                "kde"
                "gtk"
              ];
              "org.freedesktop.impl.portal.FileChooser" = "kde";
              "org.freedesktop.impl.portal.Notification" = "gtk";
              "org.freedesktop.impl.portal.ScreenCast" = "gnome";
              "org.freedesktop.impl.portal.Screenshot" = "gnome";
              "org.freedesktop.impl.portal.Secret" = "gnome-keyring";
            };
          };
        };
      };

      environment.etc."xdg/menus/applications.menu".text = ''
        <!DOCTYPE Menu PUBLIC "-//freedesktop//DTD Menu 1.0//EN"
          "http://www.freedesktop.org/standards/menu-spec/menu-1.0.dtd">
        <Menu>
          <Name>Applications</Name>
          <DefaultAppDirs/>
          <DefaultDirectoryDirs/>
          <DefaultMergeDirs/>
          <Include>
            <All/>
          </Include>
        </Menu>
      '';
    };
}
