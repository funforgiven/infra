{ lib, inputs, ... }:
{
  dendritic.hosts = lib.genAttrs [ "forge-macos" ] (name: {
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

  nixos.modules.services-forge-macos =
    { pkgs, ... }:
    let
      # Quickemu's SSH forward otherwise binds every interface. Patch the
      # pinned package to require loopback, even if the guest firewall changes.
      quickemu = pkgs.quickemu.overrideAttrs (old: {
        postPatch = (old.postPatch or "") + ''
          substituteInPlace quickemu \
            --replace-fail 'hostfwd=tcp::' 'hostfwd=tcp:127.0.0.1:' \
            --replace-fail 'hostfwd=udp::' 'hostfwd=udp:127.0.0.1:' \
            --replace-fail "HOST_CPU_SOCKETS=\$(get_cpu_info 'Socket')" 'HOST_CPU_SOCKETS=1'
        '';
      });
    in
    {
      # Applied inside this dedicated nested hypervisor, never to the physical
      # compute hosts. macOS probes MSRs that KVM does not implement.
      boot.extraModprobeConfig = "options kvm ignore_msrs=1";
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
      # Provisioning records this public key through the authenticated Nova
      # console before enrolling it into pinned SSH known-hosts.
      systemd.services.forge-host-identity = {
        description = "Publish the native host SSH public identity to its private console";
        wantedBy = [ "multi-user.target" ];
        after = [ "sshd-keygen.service" ];
        requires = [ "sshd-keygen.service" ];
        serviceConfig.Type = "oneshot";
        script = ''
          printf 'FORGE_HOST_KEY=%s\n' "$(cat /etc/ssh/ssh_host_ed25519_key.pub)" > /dev/ttyS0
        '';
      };
      environment.etc."forge/macos.conf".text = ''
        guest_os="macos"
        macos_release="sequoia"
        disk_img="/var/lib/quickemu/macos/disk.qcow2"
        ram="8G"
        cpu_cores="4"
        disk_size="160G"
        display="none"
        viewer="none"
        public_dir="none"
        ssh_port="22220"
        monitor="socket"
        serial="none"
        sound_card="none"
      '';
      systemd.services.quickemu-macos = {
        description = "Disposable macOS Forgejo guest on nested KVM";
        # The broker prepares a fresh disk overlay and starts one guest per
        # job. Do not automatically boot a previous job's writable state.
        after = [ "network-online.target" ];
        wants = [ "network-online.target" ];
        path = with pkgs; [
          bash
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
          ExecStart = "${quickemu}/bin/quickemu --vm /etc/forge/macos.conf --display none --viewer none";
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
