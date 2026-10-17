{
  config,
  inputs,
  ...
}:
let
  operator = config.users.funforgiven;
in
{
  nixos.modules.services-server-common =
    { lib, pkgs, ... }:
    {
      imports = [
        inputs.sops-nix.nixosModules.sops
      ];

      boot.tmp.cleanOnBoot = true;

      environment.systemPackages = with pkgs; [
        curl
        gitMinimal
        jq
      ];

      networking = {
        firewall.enable = true;
        useDHCP = lib.mkDefault true;
      };

      nix = {
        gc = {
          automatic = true;
          dates = "weekly";
          options = "--delete-older-than 14d";
        };
        optimise = {
          automatic = true;
          dates = [ "weekly" ];
        };
        settings = {
          experimental-features = [
            "nix-command"
            "flakes"
          ];
          trusted-users = [
            "root"
            "@wheel"
          ];
        };
        registry.nixpkgs.flake = inputs.nixpkgs;
      };

      security.sudo-rs = {
        enable = true;
        # Service hosts have no password login. The pinned operator SSH key is
        # therefore the only way to obtain an interactive sudo session.
        wheelNeedsPassword = false;
      };

      services = {
        openssh = {
          enable = true;
          openFirewall = true;
          settings = {
            KbdInteractiveAuthentication = false;
            PasswordAuthentication = false;
            PermitRootLogin = lib.mkForce "no";
          };
        };
      };

      systemd.network.wait-online.anyInterface = true;

      users = {
        mutableUsers = false;
        users.${operator.username} = {
          isNormalUser = true;
          description = operator.name;
          home = operator.homeDirectory;
          shell = pkgs.bashInteractive;
          extraGroups = [
            "systemd-journal"
            "wheel"
          ];
          openssh.authorizedKeys.keys = [
            operator.accounts.github.sshPublicKey
          ];
        };
      };
    };
}
