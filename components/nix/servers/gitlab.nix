_: {
  nixos.modules.services-gitlab =
    { lib, pkgs, ... }:
    let
      image = "docker.io/gitlab/gitlab-ee:19.3.1-ee.0@sha256:b5167605564d64acf896be614791092d1409ac3f78214a9e4394ebb24a0be1b5";
      source = lib.fileset.toSource {
        root = ../../cloud/services/gitlab;
        fileset = lib.fileset.unions [
          ../../cloud/services/gitlab/gitlab.rb
          ../../cloud/services/gitlab/backup.sh
        ];
      };
      backup = pkgs.writeShellApplication {
        name = "gitlab-prepare-backup";
        runtimeInputs = with pkgs; [
          coreutils
          docker
          findutils
          gnugrep
          jq
          rclone
          util-linux
        ];
        text = builtins.readFile (source + /backup.sh);
      };
    in
    {
      # Operator keys are baked into the image; bootstrap secrets arrive over
      # pinned SSH. This host does not consume provider metadata or user-data.
      systemd.services.openstack-init.enable = false;
      systemd.services.amazon-init.enable = false;
      systemd.services.apply-ec2-data.enable = false;
      virtualisation.docker = {
        enable = true;
        daemon.settings = {
          log-driver = "local";
          live-restore = true;
        };
      };
      virtualisation.oci-containers = {
        backend = "docker";
        containers.gitlab = {
          inherit image;
          hostname = "gitlab-data";
          volumes = [
            "/var/lib/gitlab/config:/etc/gitlab"
            "/var/lib/gitlab/logs:/var/log/gitlab"
            "/var/lib/gitlab/data:/var/opt/gitlab"
            "/var/lib/gitlab-bootstrap:/run/gitlab-bootstrap:ro"
          ];
          # Neutron accepts only the dedicated GitLab tenant on these ports.
          ports = [
            "192.168.82.10:5432:5432"
            "192.168.82.10:6379:6379"
            "192.168.82.10:8075:8075"
          ];
          extraOptions = [
            "--shm-size=256m"
            "--health-cmd=/opt/gitlab/bin/gitlab-ctl status postgresql && /opt/gitlab/bin/gitlab-ctl status redis && /opt/gitlab/bin/gitlab-ctl status gitaly"
            "--health-interval=30s"
            "--health-timeout=10s"
            "--health-start-period=180s"
            "--health-retries=3"
          ];
        };
      };
      systemd.services.docker-gitlab = {
        preStart = lib.mkBefore ''
          test -s /var/lib/gitlab-bootstrap/credentials.json
          ${pkgs.jq}/bin/jq -e '
            [.postgres_password, .redis_password, .gitaly_token, .shell_token]
            | all(.[]; type == "string" and length >= 32)
          ' /var/lib/gitlab-bootstrap/credentials.json >/dev/null
          install -m 0600 ${source}/gitlab.rb /var/lib/gitlab/config/gitlab.rb
        '';
        unitConfig.RequiresMountsFor = [ "/var/lib/gitlab" ];
      };
      networking.firewall.interfaces.ens3.allowedTCPPorts = [
        5432
        6379
        8075
      ];
      # Gitaly fetches MR source refs through its advertised tenant address.
      # Docker's userland proxy receives that container-to-host connection here.
      networking.firewall.interfaces.docker0.allowedTCPPorts = [ 8075 ];
      servicesPlatform.backup = {
        paths = [ "/var/lib/gitlab-backup/current" ];
        tag = "gitlab-helm-native";
      };
      services.restic.backups.service-state.backupPrepareCommand = "${backup}/bin/gitlab-prepare-backup";
      servicesPlatform.alerting.units = [
        "docker-gitlab"
        "restic-backups-service-state"
      ];
      environment.systemPackages = [ pkgs.rclone ];
      systemd.tmpfiles.rules = [
        "d /var/lib/gitlab 0700 root root - -"
        "d /var/lib/gitlab/config 0700 root root - -"
        # These become /var/opt/gitlab and /var/log/gitlab inside the container.
        # Match the package's traversal modes for its unprivileged service users;
        # /var/lib/gitlab remains 0700 to protect both trees on the host.
        "d /var/lib/gitlab/data 0755 root root - -"
        "d /var/lib/gitlab/logs 0755 root root - -"
        "d /var/lib/gitlab-bootstrap 0700 root root - -"
        "d /var/lib/gitlab-backup 0700 root root - -"
      ];
    };
}
