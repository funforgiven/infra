_: {
  nixos.modules.niri-greeter =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      # NixOS exposes display-manager sessions through two XDG data paths, and
      # Tuigreet lists the same desktop entry from both. Link only the supported
      # Niri UWSM session.
      uwsmSessions = pkgs.linkFarm "funforgiven-greetd-uwsm-sessions" [
        {
          name = "niri-uwsm.desktop";
          path = "${config.services.displayManager.sessionData.desktops}/share/wayland-sessions/niri-uwsm.desktop";
        }
      ];
    in
    {
      assertions = [
        {
          assertion = config.programs.niri.enable;
          message = "The Niri greetd session requires programs.niri.enable.";
        }
        {
          assertion = config.programs.uwsm.enable;
          message = "The Niri greetd session requires programs.uwsm.enable.";
        }
        {
          assertion = builtins.hasAttr "niri" config.programs.uwsm.waylandCompositors;
          message = "The Niri greetd session requires a UWSM Niri compositor definition.";
        }
        {
          assertion = !(builtins.hasAttr "dank-material-shell" config.programs);
          message = "DankMaterialShell modules and its greeter must stay disabled.";
        }
      ];

      services = {
        displayManager.defaultSession = "niri-uwsm";

        greetd = {
          enable = true;
          useTextGreeter = true;
          settings.default_session = {
            command = lib.escapeShellArgs [
              (lib.getExe pkgs.tuigreet)
              "--time"
              "--remember"
              "--asterisks"
              "--sessions"
              (toString uwsmSessions)
              "--cmd"
              (lib.escapeShellArgs [
                (lib.getExe config.programs.uwsm.package)
                "start"
                "-F"
                "--"
                "/run/current-system/sw/bin/niri"
                "--session"
              ])
            ];
            user = "greeter";
          };
        };
      };
    };
}
