{ inputs, ... }:
{
  nixos.modules.services-openstack-guest = {
    imports = [
      (inputs.nixpkgs + "/nixos/modules/virtualisation/openstack-config.nix")
    ];
  };
}
