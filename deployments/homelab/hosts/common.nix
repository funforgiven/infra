{
  config,
  lib,
  pkgs,
  ...
}:
let
  inventory = builtins.fromJSON (builtins.readFile ./inventory.json);
  name = config.networking.hostName;
  host = inventory.${name};
  bootstrap = name == "pecorino";
  operatorKey = lib.removeSuffix "\n" (builtins.readFile ../../../secrets/github-ssh-key.pub);
  peers = map (item: item.management) (
    lib.attrValues (lib.filterAttrs (peer: _: peer != name) inventory)
  );
  cniArchive = pkgs.fetchurl {
    url = "https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz";
    sha256 = "b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303";
  };
  secondaryPlugins = pkgs.runCommand "secondary-cni-plugins-1.9.1" { } ''
    mkdir -p "$out/bin"
    tar -xzf ${cniArchive} -C "$out/bin" ./macvlan ./static ./tuning ./bridge ./host-local ./loopback
  '';
  apiCheck = pkgs.writeShellScript "kubernetes-api-ready" ''
    exec ${pkgs.k3s}/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml --request-timeout=2s get --raw=/readyz >/dev/null 2>&1
  '';
  vlan = id: mtu: {
    netdevConfig = {
      Kind = "vlan";
      Name = "bond0.${toString id}";
      MTUBytes = toString mtu;
    };
    vlanConfig.Id = id;
  };
in
{
  imports = [ ./backup.nix ];
  boot = {
    initrd.availableKernelModules = [
      "ahci"
      "xhci_pci"
      "nvme"
      "usbhid"
      "sd_mod"
      "ice"
    ];
    kernelModules = [
      "ice"
      "bonding"
      "8021q"
      "br_netfilter"
      "rbd"
      "ceph"
      "tun"
      "kvm_${host.cpu}"
    ];
    kernelParams = [
      "${host.cpu}_iommu=on"
      "iommu=pt"
    ];
    kernel.sysctl = {
      "net.ipv4.ip_forward" = 1;
      "net.bridge.bridge-nf-call-iptables" = 1;
      "net.bridge.bridge-nf-call-ip6tables" = 1;
      "net.ipv4.conf.all.rp_filter" = 0;
      "net.ipv4.conf.default.rp_filter" = 0;
      "net.ipv6.conf.iot0.disable_ipv6" = 1;
    };
    tmp.cleanOnBoot = true;
  };
  hardware.enableRedistributableFirmware = true;
  hardware.cpu.${if host.cpu == "intel" then "intel" else "amd"}.updateMicrocode = true;
  time.timeZone = "Europe/Istanbul";
  networking = {
    useDHCP = false;
    useNetworkd = true;
    firewall = {
      enable = true;
      checkReversePath = false;
      trustedInterfaces = [
        "lxc+"
        "cilium_host"
        "cilium_net"
        "cilium_vxlan"
      ];
      interfaces = {
        "bond0.20" = {
          allowedTCPPorts = [
            22
            2379
            2380
            6443
            10250
            4240
            7946
          ];
          allowedUDPPorts = [
            8472
            7946
          ];
        };
        "bond0.30" = {
          allowedTCPPorts = [
            3300
            6789
          ];
          allowedTCPPortRanges = [
            {
              from = 6800;
              to = 7568;
            }
          ];
        };
      };
      # Secondary IoT has no host identity; only macvlan pods use this LAN.
      extraCommands = "iptables -I INPUT -i iot0 -j DROP\nip6tables -I INPUT -i iot0 -j DROP";
      extraStopCommands = "iptables -D INPUT -i iot0 -j DROP || true\nip6tables -D INPUT -i iot0 -j DROP || true";
    };
  };
  services.resolved.enable = true;
  systemd.network = {
    enable = true;
    netdevs = {
      "10-bond" = {
        netdevConfig = {
          Kind = "bond";
          Name = "bond0";
          MTUBytes = "9000";
        };
        bondConfig = {
          Mode = "802.3ad";
          LACPTransmitRate = "fast";
          TransmitHashPolicy = "layer3+4";
          MIIMonitorSec = "100ms";
          MinLinks = 1;
        };
      };
      "20-management" = vlan 20 1500;
      "20-ceph" = vlan 30 9000;
      "20-services" = vlan 40 1500;
      "20-iot" = {
        netdevConfig = {
          Kind = "vlan";
          Name = "iot0";
          MTUBytes = "1500";
        };
        vlanConfig.Id = 50;
      };
      "30-service-bridge".netdevConfig = {
        Kind = "bridge";
        Name = "br-services";
        MTUBytes = "1500";
      };
    };
    networks = {
      "10-fabric" = {
        matchConfig.Driver = "ice";
        linkConfig.MTUBytes = "9000";
        networkConfig = {
          Bond = "bond0";
          LinkLocalAddressing = "no";
        };
      };
      "15-bond" = {
        matchConfig.Name = "bond0";
        networkConfig = {
          VLAN = [
            "bond0.20"
            "bond0.30"
            "bond0.40"
            "iot0"
          ];
          LinkLocalAddressing = "no";
        };
      };
      "20-management" = {
        matchConfig.Name = "bond0.20";
        address = [ "${host.management}/24" ];
        gateway = [ "10.21.20.1" ];
        dns = [ "10.21.20.1" ];
        networkConfig = {
          LinkLocalAddressing = "no";
          IPv6AcceptRA = false;
        };
        linkConfig.RequiredForOnline = "routable";
      };
      "20-ceph" = {
        matchConfig.Name = "bond0.30";
        address = [ "${host.ceph}/24" ];
        networkConfig = {
          LinkLocalAddressing = "no";
          IPv6AcceptRA = false;
        };
      };
      "20-services" = {
        matchConfig.Name = "bond0.40";
        networkConfig = {
          Bridge = "br-services";
          LinkLocalAddressing = "no";
        };
      };
      "30-service-bridge" = {
        matchConfig.Name = "br-services";
        networkConfig = {
          LinkLocalAddressing = "no";
          IPv6AcceptRA = false;
          ConfigureWithoutCarrier = true;
        };
      };
      "30-iot" = {
        matchConfig.Name = "iot0";
        networkConfig = {
          LinkLocalAddressing = "no";
          IPv6AcceptRA = false;
          ConfigureWithoutCarrier = true;
        };
      };
    };
    wait-online.anyInterface = true;
  };
  systemd.services.fabric-link-settings = {
    description = "Qualify the two ice links and set the switch-matched RS-FEC policy";
    wantedBy = [ "multi-user.target" ];
    before = [ "systemd-networkd.service" ];
    after = [ "systemd-udev-settle.service" ];
    wants = [ "systemd-udev-settle.service" ];
    serviceConfig.Type = "oneshot";
    path = [
      pkgs.ethtool
      pkgs.coreutils
    ];
    script = ''
      count=0
      for device in /sys/class/net/*; do
        test -L "$device/device/driver" || continue
        test "$(basename "$(readlink -f "$device/device/driver")")" = ice || continue
        interface=$(basename "$device")
        ethtool -s "$interface" speed 25000 duplex full autoneg off
        ethtool --set-fec "$interface" encoding rs
        count=$((count + 1))
      done
      test "$count" -eq 2
    '';
  };
  sops = {
    useSystemdActivation = true;
    defaultSopsFile = ./secrets.sops.yaml;
    age = {
      keyFile = "/var/lib/sops-nix/key.txt";
      sshKeyPaths = [ ];
    };
    secrets = {
      k3s-token.key = "k3s_token";
      ssh-host-key = {
        key = "hosts/${name}/ssh_host_ed25519_key";
        path = "/etc/ssh/ssh_host_ed25519_key";
        mode = "0600";
      };
      console-password-hash = {
        key = "hosts/${name}/console_password_hash";
        neededForUsers = true;
      };
    };
  };
  users.mutableUsers = false;
  users.users.root.hashedPasswordFile = config.sops.secrets.console-password-hash.path;
  users.users.funforgiven = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    openssh.authorizedKeys.keys = [ operatorKey ];
  };
  security.sudo-rs = {
    enable = true;
    wheelNeedsPassword = false;
  };
  services.openssh = {
    hostKeys = [
      {
        path = "/etc/ssh/ssh_host_ed25519_key";
        type = "ed25519";
      }
    ];
    enable = true;
    openFirewall = false;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "prohibit-password";
    };
  };
  users.users.root.openssh.authorizedKeys.keys = [ operatorKey ];
  systemd.services.sshd = {
    after = [ "sops-install-secrets.service" ];
    requires = [ "sops-install-secrets.service" ];
  };
  environment.etc."kubernetes/authentication.yaml".source = ./authentication.yaml;
  services.k3s = {
    enable = true;
    package = pkgs.k3s;
    role = "server";
    clusterInit = bootstrap;
    serverAddr = if bootstrap then "" else "https://10.21.20.128:6443";
    tokenFile = config.sops.secrets.k3s-token.path;
    disable = [
      "traefik"
      "servicelb"
      "local-storage"
    ];
    nodeLabel = [
      "homelab.fahrican.com/hypervisor=${name}"
      "homelab.fahrican.com/iot=true"
      "homelab.fahrican.com/storage=true"
      "homelab.fahrican.com/ci-node=true"
    ];
    extraFlags = [
      "--node-ip=${host.management}"
      "--advertise-address=${host.management}"
      "--tls-san=10.21.20.128"
      "--tls-san=cluster-api.mgmt.cloud.fahrican.com"
      "--cluster-cidr=10.100.0.0/16"
      "--service-cidr=172.24.0.0/13"
      "--cluster-dns=172.24.0.10"
      "--flannel-backend=none"
      "--disable-network-policy"
      "--disable-kube-proxy"
      "--disable-helm-controller"
      "--kube-apiserver-arg=authentication-config=/etc/kubernetes/authentication.yaml"
      "--secrets-encryption"
      "--write-kubeconfig-mode=0600"
      "--etcd-snapshot-schedule-cron=\"0 */6 * * *\""
      "--etcd-snapshot-retention=20"
      "--etcd-snapshot-name=homelab"
    ];
    extraKubeletConfig = {
      imageGCHighThresholdPercent = 70;
      imageGCLowThresholdPercent = 60;
      containerLogMaxSize = "16Mi";
      containerLogMaxFiles = 3;
    };
  };
  systemd.services.secondary-cni-plugins = {
    wantedBy = [ "multi-user.target" ];
    before = [ "k3s.service" ];
    serviceConfig.Type = "oneshot";
    script = ''
      mkdir -p /opt/cni/bin /etc/cni/net.d
      for plugin in macvlan static tuning bridge host-local loopback; do
        install -m 0755 ${secondaryPlugins}/bin/$plugin /opt/cni/bin/$plugin
      done
    '';
  };
  systemd.services.k3s = {
    environment.TZ = "UTC";
    after = [
      "sops-install-secrets.service"
      "systemd-networkd-wait-online.service"
    ];
    requires = [ "sops-install-secrets.service" ];
  };
  services.keepalived = {
    enable = true;
    openFirewall = true;
    enableScriptSecurity = true;
    vrrpScripts.api-ready = {
      script = toString apiCheck;
      interval = 3;
      fall = 2;
      rise = 2;
      user = "root";
    };
    vrrpInstances.kubernetes-api = {
      interface = "bond0.20";
      state = "BACKUP";
      virtualRouterId = 128;
      inherit (host) priority;
      unicastSrcIp = host.management;
      unicastPeers = peers;
      trackScripts = [ "api-ready" ];
      virtualIps = [
        {
          addr = "10.21.20.128/24";
          dev = "bond0.20";
        }
      ];
    };
  };
  services.journald.settings.Journal = {
    SystemMaxUse = "512M";
    SystemMaxFileSize = "64M";
    MaxRetentionSec = "7day";
  };
  services.fstrim.enable = true;
  systemd.tmpfiles.rules = [
    "d /var/lib/rook 0700 root root -"
    "d /etc/cni/net.d 0755 root root -"
    "d /opt/cni/bin 0755 root root -"
  ];
  environment.systemPackages = with pkgs; [
    ceph
    ethtool
    iproute2
    kubectl
    lvm2
    mdadm
    nftables
  ];
  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 14d";
  };
  nix.optimise.automatic = true;
}
