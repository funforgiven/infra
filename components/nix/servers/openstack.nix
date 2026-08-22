{ inputs, ... }:
{
  nixos.modules.services-openstack-guest =
    { config, ... }:
    {
      imports = [
        (inputs.nixpkgs + "/nixos/modules/virtualisation/openstack-config.nix")
      ];

      # The OpenStack image consistently names its services-network NIC ens3.
      # Neutron limits TCP 9100 on that port to the services subnet; the native
      # interface rule preserves the same boundary in the guest firewall.
      networking.firewall.interfaces.ens3.allowedTCPPorts = [ 9100 ];

      assertions = [
        {
          assertion = builtins.elem 9100 config.networking.firewall.interfaces.ens3.allowedTCPPorts;
          message = "OpenStack service hosts must expose node exporter only through their private services interface.";
        }
      ];
    };
}
