{
  config,
  inputs,
  lib,
  ...
}:
let
  cfg = config;
  polkitAgentType = lib.types.enum [
    "kde"
    "quickshell"
  ];

  mkHostModule =
    hostname: host:
    let
      user = cfg.users.${host.user};
    in
    { config, lib, ... }:
    {
      imports = [ inputs.home-manager.nixosModules.home-manager ];

      options.dendritic = {
        primaryUser = lib.mkOption {
          type = lib.types.attrs;
          readOnly = true;
          description = "Login name and home directory of this host's primary user.";
        };

        polkit.agent = lib.mkOption {
          type = polkitAgentType;
          default = "kde";
          description = "Authentication agent used in the Niri session.";
        };
      };

      config = {
        dendritic.primaryUser = { inherit (user) homeDirectory username; };

        networking.hostName = hostname;
        nixpkgs.hostPlatform = host.system;
        system.stateVersion = host.stateVersion;

        home-manager = {
          useGlobalPkgs = true;
          useUserPackages = true;
          backupFileExtension = "hm-bak";
          users.${user.username}.imports = [
            {
              options.dendritic = {
                niri.outputs = lib.mkOption {
                  type = lib.types.nullOr (lib.types.attrsOf lib.types.attrs);
                  readOnly = true;
                  description = "Host Niri output settings, or null for a host without the desktop.";
                };
                polkit.agent = lib.mkOption {
                  type = polkitAgentType;
                  readOnly = true;
                  description = "Authentication agent selected by the NixOS host.";
                };
              };

              config = {
                dendritic.niri.outputs = host.niri.outputs;
                dendritic.polkit.agent = config.dendritic.polkit.agent;
                home.stateVersion = host.stateVersion;
              };
            }
          ]
          ++ map (profile: user.home.${profile}) host.homeProfiles;
        };
      };
    };
in
{
  options = {
    nixos.modules = lib.mkOption {
      type = lib.types.lazyAttrsOf lib.types.deferredModule;
      default = { };
      description = "Named NixOS feature modules available to hosts.";
    };

    home = lib.mkOption {
      type = lib.types.lazyAttrsOf lib.types.deferredModule;
      default = { };
      description = "Named Home Manager profiles available to users.";
    };

    users = lib.mkOption {
      type = lib.types.lazyAttrsOf (
        lib.types.submodule (
          { name, config, ... }:
          {
            options = {
              username = lib.mkOption {
                type = lib.types.singleLineStr;
                default = name;
                description = "Login name.";
              };

              name = lib.mkOption {
                type = lib.types.singleLineStr;
                default = name;
                description = "Full name.";
              };

              email = lib.mkOption {
                type = lib.types.singleLineStr;
                description = "Email address used by Git and account tools.";
              };

              homeDirectory = lib.mkOption {
                type = lib.types.strMatching "/.*";
                default = "/home/${config.username}";
                description = "Absolute home directory.";
              };

              home = lib.mkOption {
                type = lib.types.lazyAttrsOf lib.types.deferredModule;
                default = { };
                description = "Home Manager profiles available to this user.";
              };

              accounts.github = {
                username = lib.mkOption {
                  type = lib.types.singleLineStr;
                  description = "GitHub account name.";
                };

                sshPublicKey = lib.mkOption {
                  type = lib.types.addCheck lib.types.singleLineStr (value: lib.hasPrefix "ssh-ed25519 " value);
                  description = "Ed25519 public key used for GitHub SSH and commit signing.";
                };
              };
            };
          }
        )
      );
      default = { };
      description = "User accounts and their Home Manager profiles.";
    };

    dendritic.hosts = lib.mkOption {
      type = lib.types.lazyAttrsOf (
        lib.types.submodule {
          options = {
            system = lib.mkOption {
              type = lib.types.singleLineStr;
              description = "Nix system used to build this host, such as x86_64-linux.";
            };

            stateVersion = lib.mkOption {
              type = lib.types.singleLineStr;
              description = "NixOS and Home Manager state version for this host.";
            };

            user = lib.mkOption {
              type = lib.types.singleLineStr;
              description = "Name of the user record assigned to this host.";
            };

            features = lib.mkOption {
              type = lib.types.listOf lib.types.singleLineStr;
              description = "Named NixOS feature modules (nixos.modules) enabled on this host.";
            };

            homeProfiles = lib.mkOption {
              type = lib.types.listOf lib.types.singleLineStr;
              description = "Home Manager profiles (users.<user>.home) enabled for this host's user.";
            };

            niri.outputs = lib.mkOption {
              type = lib.types.nullOr (lib.types.attrsOf lib.types.attrs);
              default = null;
              description = ''
                Niri outputs by role (primary, secondary, ...), each with
                connector, identifier, mode, scale, position, transform,
                variableRefreshRate and focusAtStartup; null without a desktop.
              '';
            };
          };
        }
      );
      default = { };
      description = "Host build settings and enabled modules.";
    };
  };

  config.flake.nixosConfigurations = lib.mapAttrs (
    hostname: host:
    inputs.nixpkgs.lib.nixosSystem {
      inherit (host) system;
      modules = map (name: cfg.nixos.modules.${name}) host.features ++ [ (mkHostModule hostname host) ];
    }
  ) cfg.dendritic.hosts;
}
