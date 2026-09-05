{ lib, inputs, ... }:
{
  dendritic.hosts = lib.genAttrs [ "gitlab-macos" ] (name: {
    system = "x86_64-linux";
    stateVersion = "26.05";
    user = "funforgiven";
    homeProfiles = [ ];
    features = [
      "services-server-common"
      "services-host-monitoring"
      "services-ci-guest"
      "services-${name}"
    ];
  });

  nixos.modules.services-ci-guest = { lib, ... }: {
    imports = [ (inputs.nixpkgs + "/nixos/modules/virtualisation/openstack-config.nix") ];
    # Neutron blocks metadata from CI. Operator public keys are baked into the
    # image; no private keys, user-data credentials or cloud tokens are needed.
    systemd.services.openstack-init.enable = false;
    systemd.services.amazon-init.enable = false;
    systemd.services.apply-ec2-data.enable = false;
    networking.enableIPv6 = false;
    networking.timeServers = lib.mkForce [
      "162.159.200.1"
      "162.159.200.123"
    ];
    networking.firewall.interfaces.ens3.allowedTCPPorts = [
      9100
      9252
    ];
  };

  nixos.modules.services-gitlab-macos =
    { pkgs, ... }:
    let
      # Quickemu's SSH forward otherwise binds every interface. Patch the
      # pinned package to require loopback, even if the guest firewall changes.
      quickemu = pkgs.quickemu.overrideAttrs (old: {
        postPatch = (old.postPatch or "") + ''
          substituteInPlace quickemu \
            --replace-fail 'hostfwd=tcp::' 'hostfwd=tcp:127.0.0.1:' \
            --replace-fail 'hostfwd=udp::' 'hostfwd=udp:127.0.0.1:'
        '';
      });
    in
    {
      environment.systemPackages = [
        quickemu
        pkgs.qemu
        pkgs.socat
      ];
      users.groups.quickemu = { };
      users.users.quickemu = {
        isSystemUser = true;
        group = "quickemu";
        extraGroups = [ "kvm" ];
        home = "/var/lib/quickemu";
        createHome = true;
      };
      environment.etc."gitlab/macos.conf".text = ''
        guest_os="macos"
        macos_release="sequoia"
        disk_img="/var/lib/quickemu/macos/disk.qcow2"
        ram="8G"
        cpu_cores="4"
        display="none"
        viewer="none"
        public_dir="none"
        ssh_port="22220"
        monitor="socket"
        serial="none"
        sound_card="none"
      '';
      systemd.services.quickemu-macos = {
        description = "macOS GitLab guest on nested KVM";
        wantedBy = [ "multi-user.target" ];
        after = [ "network-online.target" ];
        wants = [ "network-online.target" ];
        path = with pkgs; [
          coreutils
          gnugrep
        ];
        unitConfig.ConditionPathExists = "/var/lib/quickemu/macos/disk.qcow2";
        preStart = ''
          grep -qw vmx /proc/cpuinfo
          grep -qw avx2 /proc/cpuinfo
          test -r /dev/kvm && test -w /dev/kvm
          cd /var/lib/quickemu/macos
          # Immutable firmware and golden-image provenance are enrolled once;
          # boot never downloads firmware, tools or installers.
          sha256sum --check --strict firmware.sha256
          test -s OVMF_VARS-1920x1080.fd
          test -s OpenCore.qcow2
        '';
        serviceConfig = {
          Type = "forking";
          User = "quickemu";
          Group = "quickemu";
          WorkingDirectory = "/var/lib/quickemu";
          PIDFile = "/var/lib/quickemu/macos/macos.pid";
          ExecStart = "${quickemu}/bin/quickemu --vm /etc/gitlab/macos.conf --display none --viewer none";
          KillMode = "control-group";
          KillSignal = "SIGTERM";
          TimeoutStopSec = 120;
          Restart = "on-failure";
          RestartSec = 30;
          UMask = "0077";
          NoNewPrivileges = true;
          ProtectSystem = "strict";
          ProtectHome = true;
          ReadWritePaths = [ "/var/lib/quickemu" ];
          PrivateTmp = true;
          ProtectKernelTunables = true;
          ProtectKernelModules = true;
          ProtectControlGroups = true;
          RestrictSUIDSGID = true;
          DevicePolicy = "closed";
          DeviceAllow = [ "/dev/kvm rw" ];
        };
      };
    };
}
