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
    {
      config,
      lib,
      pkgs,
      ...
    }:
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
          serviceConfig = {
            UMask = "0077";
            ExecStartPost = [
              (pkgs.writeShellScript "record-restic-success" ''
                set -eu
                target=/var/lib/node-exporter-textfile/services-restic.prom
                temporary="$target.$$"
                printf 'services_restic_last_success_unixtime{host="%s"} %s\n' \
                  ${lib.escapeShellArg config.networking.hostName} \
                  "$(${pkgs.coreutils}/bin/date +%s)" > "$temporary"
                chmod 0644 "$temporary"
                mv -f "$temporary" "$target"
              '')
            ];
          };
        };

        systemd.tmpfiles.rules = [
          "d /var/lib/backup-bootstrap 0700 root root - -"
        ];
      };
    };

  nixos.modules.services-host-monitoring =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      alerting = config.servicesPlatform.alerting;
      notifier = pkgs.writeShellApplication {
        name = "notify-telegram-unit-failure";
        runtimeInputs = [
          pkgs.curl
          pkgs.jq
        ];
        text = ''
          set -euo pipefail

          readonly unit="$1"
          readonly token_file=/var/lib/monitoring-bootstrap/bot-token
          readonly chat_file=/var/lib/monitoring-bootstrap/chat-id

          IFS= read -r token < "$token_file"
          [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]
          grep -Eq '^-?[0-9]+$' "$chat_file"

          message="Critical unit failed on ${config.networking.hostName}: $unit"
          jq --null-input --compact-output \
            --rawfile chat_id "$chat_file" \
            --arg text "$message" \
            '{chat_id: ($chat_id | rtrimstr("\n")), text: $text}' | \
          curl \
            --silent \
            --show-error \
            --fail \
            --output /dev/null \
            --config <(
            printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token"
            ) \
            --request POST \
            --header 'Content-Type: application/json' \
            --data-binary @-
          unset token
        '';
      };
    in
    {
      options.servicesPlatform.alerting.units = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Critical systemd units that notify the infrastructure Telegram chat on failure.";
      };

      config = {
        services.prometheus.exporters.node = {
          enable = true;
          enabledCollectors = [ "systemd" ];
          extraFlags = [
            "--collector.textfile.directory=/var/lib/node-exporter-textfile"
          ];
          listenAddress = "0.0.0.0";
          openFirewall = false;
        };

        systemd.services = {
          "telegram-unit-failure@" = {
            description = "Notify the infrastructure Telegram chat about %i";
            unitConfig.ConditionPathExists = [
              "/var/lib/monitoring-bootstrap/bot-token"
              "/var/lib/monitoring-bootstrap/chat-id"
            ];
            serviceConfig = {
              Type = "oneshot";
              ExecStart = "${notifier}/bin/notify-telegram-unit-failure %i";
              UMask = "0077";
            };
          };
        }
        // lib.genAttrs alerting.units (_: {
          unitConfig.OnFailure = [ "telegram-unit-failure@%n.service" ];
        });

        systemd.tmpfiles.rules = [
          "d /var/lib/monitoring-bootstrap 0700 root root - -"
          "d /var/lib/node-exporter-textfile 0755 root root - -"
        ];

        assertions = [
          {
            assertion = !builtins.elem 9100 config.networking.firewall.allowedTCPPorts;
            message = "Node exporter must be allowed only on an explicit private interface.";
          }
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
