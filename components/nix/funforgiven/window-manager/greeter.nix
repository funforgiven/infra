{ config, inputs, ... }:
let
  hosts = config.dendritic.hosts;
in
{
  nixos.modules.niri-greeter =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      outputs =
        lib.throwIfNot (hosts.${config.networking.hostName}.niri.outputs != null)
          "The Niri greeter requires host-specific output settings."
          hosts.${config.networking.hostName}.niri.outputs;
      regreet = config.services.displayManager.regreet;
      niri = lib.getExe config.programs.niri.package;

      # Offer only the UWSM session, so logging in keeps the desktop's service
      # lifecycle instead of starting a second, unmanaged Niri session.
      uwsmSessions = pkgs.linkFarm "funforgiven-greetd-uwsm-sessions" [
        {
          name = "wayland-sessions/niri-uwsm.desktop";
          path = "${config.services.displayManager.sessionData.desktops}/share/wayland-sessions/niri-uwsm.desktop";
        }
      ];
      greeterDataDirs = lib.concatStringsSep ":" [
        (toString uwsmSessions)
        "${regreet.iconTheme.package}/share"
        "${regreet.cursorTheme.package}/share"
      ];
      greeterSession = pkgs.writeShellScript "regreet-session" ''
        ${lib.getExe' pkgs.coreutils "env"} XDG_DATA_DIRS=${lib.escapeShellArg greeterDataDirs} ${lib.getExe regreet.package}
        exec ${niri} msg action quit --skip-confirmation
      '';
      greeterSettings =
        (lib.evalModules {
          modules = [
            inputs.niri.lib.internal.settings-module
            {
              programs.niri.settings = {
                # The console cannot reliably drive all three NVIDIA outputs.
                # Configure the greeter with the same modes and layout as the desktop.
                outputs = lib.mapAttrs' (
                  _role: output:
                  lib.nameValuePair output.identifier {
                    inherit (output)
                      mode
                      position
                      scale
                      transform
                      ;
                    focus-at-startup = output.focusAtStartup;
                  }
                ) outputs;
                input.keyboard = {
                  xkb.layout = config.services.xserver.xkb.layout;
                  numlock = true;
                };
                cursor = {
                  theme = config.stylix.cursor.name;
                  size = config.stylix.cursor.size;
                };
                environment = {
                  GDK_BACKEND = "wayland";
                  GDK_DEBUG = "no-portals";
                  GTK_USE_PORTAL = "0";
                };
                spawn-at-startup = [
                  { argv = [ (toString greeterSession) ]; }
                  {
                    argv = [
                      (lib.getExe pkgs.swaybg)
                      "--image"
                      (toString config.stylix.image)
                      "--mode"
                      "fill"
                    ];
                  }
                ];
                window-rules = [
                  {
                    open-on-output = outputs.primary.identifier;
                    open-fullscreen = true;
                  }
                ];
                hotkey-overlay.skip-at-startup = true;
                prefer-no-csd = true;
                animations.enable = false;
                gestures.hot-corners.enable = false;
                xwayland-satellite.enable = false;
              };
            }
          ];
        }).config.programs.niri.finalConfig;
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

      # Steam ignores SIGTERM, so the default 90s stop timeout stalls every
      # logout, restart, and shutdown on a blank console after Niri exits.
      systemd.user.settings.Manager.DefaultTimeoutStopSec = "10s";

      environment.etc."greetd/niri.kdl".source =
        inputs.niri.lib.internal.validated-config-for pkgs config.programs.niri.package
          greeterSettings;

      users.users.greeter = {
        home = "/var/lib/greeter";
        createHome = true;
      };

      services = {
        displayManager = {
          defaultSession = "niri-uwsm";
          regreet = {
            enable = true;
            font = {
              inherit (config.stylix.fonts.sansSerif) name package;
            };
            cursorTheme = {
              inherit (config.stylix.cursor) name package;
            };
            iconTheme = {
              inherit (config.stylix.icons) package;
              name = config.stylix.icons.dark;
            };
            settings = {
              skip_selection = true;
              GTK.application_prefer_dark_theme = true;
              background = {
                path = toString config.stylix.image;
                fit = "Cover";
              };
            };
          };
        };

        greetd = {
          enable = true;
          useTextGreeter = false;
          settings.default_session = {
            command = lib.escapeShellArgs [
              (lib.getExe' pkgs.dbus "dbus-run-session")
              niri
              "--config"
              "/etc/greetd/niri.kdl"
            ];
            user = "greeter";
          };
        };
      };
    };
}
