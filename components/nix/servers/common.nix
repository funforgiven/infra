{
  config,
  inputs,
  ...
}:
let
  operator = config.users.funforgiven;
in
{
  nixos.modules.services-host-backup =
    { config, lib, ... }:
    let
      backup = config.servicesPlatform.backup;
    in
    {
      options.servicesPlatform.backup = {
        paths = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Persistent service paths included in the off-site Restic backup.";
        };
        tag = lib.mkOption {
          type = lib.types.str;
          default = config.networking.hostName;
          description = "Stable Restic snapshot tag for this service host.";
        };
      };

      config = lib.mkIf (backup.paths != [ ]) {
        services.restic.backups.service-state = {
          inherit (backup) paths;
          repositoryFile = "/var/lib/backup-bootstrap/repository";
          passwordFile = "/var/lib/backup-bootstrap/password";
          environmentFile = "/var/lib/backup-bootstrap/environment";
          initialize = false;
          extraBackupArgs = [
            "--tag"
            backup.tag
            "--host"
            config.networking.hostName
          ];
          pruneOpts = [
            "--keep-daily 14"
            "--keep-weekly 8"
            "--keep-monthly 12"
            "--keep-yearly 3"
            "--group-by host,tags"
          ];
          timerConfig = {
            OnCalendar = "*-*-* 02:00:00";
            RandomizedDelaySec = "2h";
            Persistent = true;
          };
        };

        systemd.services.restic-backups-service-state = {
          unitConfig = {
            ConditionPathExists = [
              "/var/lib/backup-bootstrap/repository"
              "/var/lib/backup-bootstrap/password"
              "/var/lib/backup-bootstrap/environment"
            ];
            RequiresMountsFor = backup.paths;
          };
          serviceConfig.UMask = "0077";
        };

        systemd.tmpfiles.rules = [
          "d /var/lib/backup-bootstrap 0700 root root - -"
        ];
      };
    };

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

      security.sudo-rs.enable = true;

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
        qemuGuest.enable = true;
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
