{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (builtins.fromJSON (builtins.readFile ./inventory.json)) hosts;
  # Stagger uploads ten minutes apart from :30, highest VRRP priority first.
  order = lib.sort (a: b: hosts.${a}.priority > hosts.${b}.priority) (lib.attrNames hosts);
  minute = lib.mod (
    30 + 10 * lib.lists.findFirstIndex (host: host == config.networking.hostName) 0 order
  ) 60;
in
{
  sops.secrets = {
    etcd-restic-password.key = "etcd_restic_password";
    etcd-backup-environment.key = "etcd_backup_environment";
  };
  services.restic.backups.homelab-etcd = {
    repository = "s3:s3.us-west-004.backblazeb2.com/fahrican-cloud-recovery/services/kubernetes/nixos-etcd";
    passwordFile = config.sops.secrets.etcd-restic-password.path;
    environmentFile = config.sops.secrets.etcd-backup-environment.path;
    initialize = false;
    paths = [ "/var/lib/homelab-etcd-export" ];
    extraBackupArgs = [
      "--host=${config.networking.hostName}"
      "--tag=homelab-etcd"
    ];
    pruneOpts = [
      "--keep-daily 14"
      "--keep-weekly 8"
      "--keep-monthly 12"
      "--keep-yearly 3"
      "--group-by host,tags"
    ];
    timerConfig = {
      OnCalendar = "*-*-* 00,06,12,18:${lib.fixedWidthNumber 2 minute}:00 UTC";
      Persistent = true;
      RandomizedDelaySec = "2m";
    };
    backupPrepareCommand = ''
      #!${pkgs.bash}/bin/bash
      set -euo pipefail
      umask 077
      latest=""
      latest_timestamp=0
      for snapshot in /var/lib/rancher/k3s/server/db/snapshots/homelab-*; do
        test -f "$snapshot" || continue
        timestamp=$(${pkgs.coreutils}/bin/stat -c %Y "$snapshot")
        if test "$timestamp" -gt "$latest_timestamp"; then
          latest="$snapshot"
          latest_timestamp="$timestamp"
        fi
      done
      test -n "$latest"
      age=$(($(${pkgs.coreutils}/bin/date +%s) - latest_timestamp))
      test "$age" -ge 0
      test "$age" -lt 28800
      stage=/var/lib/homelab-etcd-export
      ${pkgs.coreutils}/bin/install -d -m 0700 "$stage"
      ${pkgs.coreutils}/bin/cp --reflink=auto "$latest" "$stage/snapshot.db"
      ${pkgs.coreutils}/bin/cp /var/lib/rancher/k3s/server/token "$stage/token"
      ${pkgs.coreutils}/bin/cp -a /var/lib/rancher/k3s/server/tls "$stage/"
      ${pkgs.coreutils}/bin/cp -a /var/lib/rancher/k3s/server/cred "$stage/"
      ${pkgs.coreutils}/bin/cp /var/lib/sops-nix/key.txt "$stage/host-age-identity"
      ${pkgs.coreutils}/bin/cp /etc/ssh/ssh_host_ed25519_key "$stage/ssh_host_ed25519_key"
    '';
    backupCleanupCommand = ''
      #!${pkgs.bash}/bin/bash
      set -euo pipefail
      ${pkgs.coreutils}/bin/rm -rf /var/lib/homelab-etcd-export
      if test "''${SERVICE_RESULT:-unknown}" = success; then
        directory=/var/lib/node_exporter/textfile
        ${pkgs.coreutils}/bin/install -d -m 0755 "$directory"
        printf 'homelab_etcd_backup_last_success_timestamp_seconds %s\n' "$(${pkgs.coreutils}/bin/date +%s)" > "$directory/etcd-backup.prom.tmp"
        ${pkgs.coreutils}/bin/chmod 0644 "$directory/etcd-backup.prom.tmp"
        ${pkgs.coreutils}/bin/mv "$directory/etcd-backup.prom.tmp" "$directory/etcd-backup.prom"
      fi
    '';
  };
  systemd.services.restic-backups-homelab-etcd = {
    after = [
      "k3s.service"
      "sops-install-secrets.service"
      "network-online.target"
    ];
    requires = [ "sops-install-secrets.service" ];
    serviceConfig.TimeoutStartSec = "2h";
  };
  systemd.tmpfiles.rules = [ "d /var/lib/node_exporter/textfile 0755 root root -" ];
}
