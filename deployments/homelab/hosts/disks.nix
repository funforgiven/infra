{ config, lib, ... }:
let
  inventory = builtins.fromJSON (builtins.readFile ./inventory.json);
  host = inventory.${config.networking.hostName};
  makeDisk = index: device: {
    name = "os${toString index}";
    value = {
      type = "disk";
      inherit device;
      content = {
        type = "gpt";
        partitions = {
          esp = {
            size = "1G";
            type = "EF00";
            content = {
              type = "mdraid";
              name = "boot";
            };
          };
          root = {
            size = "100%";
            content = {
              type = "mdraid";
              name = "system";
            };
          };
        };
      };
    };
  };
in
{
  # Only the SATA pair is in disko. Ceph NVMes are excluded.
  disko.devices = {
    disk = builtins.listToAttrs (lib.imap0 makeDisk host.osDisks);
    mdadm = {
      boot = {
        type = "mdadm";
        level = 1;
        metadata = "1.0";
        content = {
          type = "filesystem";
          format = "vfat";
          mountpoint = "/boot";
          mountOptions = [ "umask=0077" ];
        };
      };
      system = {
        type = "mdadm";
        level = 1;
        metadata = "1.2";
        content = {
          type = "filesystem";
          format = "ext4";
          mountpoint = "/";
        };
      };
    };
  };
  boot.swraid.enable = true;
  boot.swraid.mdadmConf = "MAILADDR root";
  boot.loader = {
    grub = {
      enable = true;
      device = "nodev";
      efiSupport = true;
      efiInstallAsRemovable = true;
    };
    efi.canTouchEfiVariables = false;
  };
  assertions = [
    {
      assertion =
        builtins.length host.osDisks == 2
        && builtins.all (disk: !(builtins.elem disk host.cephDisks)) host.osDisks;
      message = "disko must select exactly the two inventoried SATA OS connectors, never a Ceph device.";
    }
  ];
}
