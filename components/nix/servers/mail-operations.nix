_: {
  nixos.modules.services-aws-mail-operations =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (p: [ p.boto3 ]);
      operations = pkgs.writeShellApplication {
        name = "mail-operations";
        runtimeInputs = [
          pkgs.stalwart-cli
          pkgs.stalwart-vandelay
          pkgs.postgresql_17
          pkgs.restic
          pkgs.systemd
        ];
        text = ''
          exec ${python}/bin/python ${../../cloud/services/mail-aws/operations.py} "$@"
        '';
      };
      unit = action: {
        description = "Mail readiness: ${action}";
        after = [
          "network-online.target"
          "stalwart.service"
        ];
        wants = [ "network-online.target" ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${operations}/bin/mail-operations ${action}";
          EnvironmentFile = "/etc/stalwart-bootstrap/aws.env";
          Environment = [
            "PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt"
            "XDG_CACHE_HOME=/var/lib/mail-operations/cache"
          ];
          StateDirectory = "mail-operations";
          StateDirectoryMode = "0700";
          UMask = "0077";
          NoNewPrivileges = true;
          PrivateTmp = true;
          ProtectHome = true;
          ProtectSystem = "strict";
          ReadWritePaths = [ "/var/lib/mail-operations" ];
          TimeoutStartSec = "2h";
        };
      };
      timer = schedule: delay: {
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnCalendar = schedule;
          OnBootSec = delay;
          Persistent = true;
          RandomizedDelaySec = "30s";
        };
      };
    in
    {
      environment.systemPackages = [
        operations
        pkgs.stalwart-vandelay
        pkgs.restic
      ];
      systemd.services = {
        mail-reconcile = (unit "reconcile") // {
          wantedBy = [ "multi-user.target" ];
          serviceConfig = (unit "reconcile").serviceConfig // {
            Restart = "on-failure";
            RestartSec = "30s";
          };
        };
        mail-health = unit "health";
        mail-canary = unit "canary";
        mail-backup = unit "backup";
        mail-restore-check = (unit "restore-check") // {
          # Export/pruning and restore verification share a repository and
          # staging disk; serialize their scheduled runs.
          after = [
            "network-online.target"
            "mail-backup.service"
          ];
        };
      };
      systemd.timers = {
        mail-health = timer "*:0/5" "2min";
        # 48 inbound test messages/day leaves room on a 100/day relay plan.
        mail-canary = timer "*:07,37" "4min";
        mail-backup = timer "*-*-* 02:10:00 UTC" "6min";
        mail-restore-check = timer "Sun *-*-* 04:10:00 UTC" "12min";
      };
    };
}
