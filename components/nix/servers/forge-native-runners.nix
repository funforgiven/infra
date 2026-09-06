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
      # Preserve the enrolled host UID and let nftables validate in the Nix
      # build sandbox, where the target system's user database is absent.
      quickemuUid = 996;
      # Quickemu's SSH forward otherwise binds every interface. Patch the
      # pinned package to require loopback, even if the guest firewall changes.
      quickemu = pkgs.quickemu.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ../../cloud/services/forge/macos/quickemu-overlay.patch ];
        postPatch = (old.postPatch or "") + ''
          substituteInPlace quickemu \
            --replace-fail 'hostfwd=tcp::' 'hostfwd=tcp:127.0.0.1:' \
            --replace-fail 'hostfwd=udp::' 'hostfwd=udp:127.0.0.1:' \
            --replace-fail "HOST_CPU_SOCKETS=\$(get_cpu_info 'Socket')" 'HOST_CPU_SOCKETS=1'
        '';
      });
      macosJob = pkgs.writeShellApplication {
        name = "forge-macos-job";
        runtimeInputs = with pkgs; [
          python3
          qemu
          cdrtools
          systemd
        ];
        text = ''
          exec python3 ${../../cloud/services/forge/macos/host-job.py}
        '';
      };
    in
    {
      # Applied inside this dedicated nested hypervisor, never to the physical
      # compute hosts. macOS probes MSRs that KVM does not implement.
      boot.extraModprobeConfig = "options kvm ignore_msrs=1";
      environment.systemPackages = [
        quickemu
        pkgs.qemu
        pkgs.socat
        macosJob
      ];
      users.groups.quickemu = { };
      users.users.quickemu = {
        uid = quickemuUid;
        isSystemUser = true;
        group = "quickemu";
        extraGroups = [ "kvm" ];
        home = "/var/lib/quickemu";
        createHome = true;
      };
      users.groups.forge-broker = { };
      users.users.forge-broker = {
        isSystemUser = true;
        group = "forge-broker";
        home = "/var/lib/forge-broker";
        createHome = true;
        shell = pkgs.bash;
        openssh.authorizedKeys.keys = [
          (
            "restrict,command=\"sudo -n ${macosJob}/bin/forge-macos-job\" "
            + lib.removeSuffix "\n" (builtins.readFile ../../cloud/services/forge/macos/broker.pub)
          )
        ];
      };
      security.sudo-rs.extraRules = [
        {
          users = [ "forge-broker" ];
          commands = [
            {
              command = "${macosJob}/bin/forge-macos-job \"\"";
              options = [
                "NOPASSWD"
                "NOSETENV"
              ];
            }
          ];
        }
      ];
      # Slirp maps 10.0.2.2 to the outer host. Neutron cannot see those local
      # connections, so explicitly prevent the QEMU user from opening them.
      # Established operator console/SSH forwards and the local DNS stub work.
      networking.nftables = {
        enable = true;
        tables.forge-guest-isolation = {
          family = "inet";
          content = ''
            chain output {
              type filter hook output priority 0; policy accept;
              meta skuid ${toString quickemuUid} ct state established,related accept
              meta skuid ${toString quickemuUid} ip daddr 127.0.0.53 udp dport 53 accept
              meta skuid ${toString quickemuUid} ip daddr 127.0.0.53 tcp dport 53 accept
              meta skuid ${toString quickemuUid} ip daddr 127.0.0.0/8 reject
              meta skuid ${toString quickemuUid} fib daddr type local reject
            }
          '';
        };
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
        # The QEMU user cannot probe loopback ports through the isolation
        # firewall. One guest is allowed, so reserve its console port directly.
        spice_port="5930"
        monitor="socket"
        serial="none"
        sound_card="none"
        extra_args="-drive if=none,id=ForgeJob,format=raw,file=/var/lib/quickemu/macos/job.iso,readonly=on -device ide-cd,bus=ahci.2,drive=ForgeJob"
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
          Restart = "no";
          RuntimeMaxSec = 8100;
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
