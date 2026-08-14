{ inputs, ... }:
{
  nixos.modules.services-hetzner-guest =
    { lib, ... }:
    {
      imports = [
        inputs.disko.nixosModules.disko
        (inputs.nixpkgs + "/nixos/modules/profiles/qemu-guest.nix")
      ];

      boot = {
        initrd.availableKernelModules = [
          "ahci"
          "sd_mod"
          "sr_mod"
          "virtio_pci"
          "virtio_scsi"
        ];
        loader.grub = {
          enable = true;
          efiInstallAsRemovable = true;
          efiSupport = true;
        };
      };

      disko.devices.disk.system = {
        device = lib.mkDefault "/dev/sda";
        type = "disk";
        content = {
          type = "gpt";
          partitions = {
            bios = {
              name = "boot";
              size = "1M";
              type = "EF02";
            };
            esp = {
              name = "ESP";
              size = "512M";
              type = "EF00";
              content = {
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot";
                mountOptions = [
                  "defaults"
                  "umask=0077"
                ];
              };
            };
            root = {
              name = "root";
              size = "100%";
              content = {
                type = "filesystem";
                format = "ext4";
                mountpoint = "/";
                mountOptions = [
                  "defaults"
                  "noatime"
                ];
              };
            };
          };
        };
      };
    };
}
