_: {
  nixos.modules.niri-portals =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      kdePortalPluginPath = lib.makeSearchPath "lib/qt-6/plugins" [
        pkgs.kdePackages.plasma-integration
        pkgs.qt6Packages.qtstyleplugin-kvantum
      ];
    in
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
              default = [ "gtk" ];
              "org.freedesktop.impl.portal.FileChooser" = "kde";
              "org.freedesktop.impl.portal.Notification" = "gtk";
              "org.freedesktop.impl.portal.ScreenCast" = "gnome";
              "org.freedesktop.impl.portal.Screenshot" = "gnome";
              "org.freedesktop.impl.portal.Secret" = "gnome-keyring";
            };
          };
        };
      };

      # The portal backend cannot use qt6ct: its configured dialog helper is
      # xdgdesktopportal, which would ask the frontend to call this same backend
      # and deadlock until D-Bus times out. KDE's platform theme reads the
      # managed kdeglobals palette and creates a native KFileWidget instead.
      systemd.user.services.plasma-xdg-desktop-portal-kde = {
        overrideStrategy = "asDropin";
        serviceConfig.Environment = [
          "QT_QPA_PLATFORMTHEME=kde"
          "QT_QPA_PLATFORMTHEME_QT6=kde"
          "QT_PLUGIN_PATH=${kdePortalPluginPath}"
        ];
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
