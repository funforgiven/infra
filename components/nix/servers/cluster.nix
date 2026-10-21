{ inputs, lib, ... }:
let
  inherit (builtins.fromJSON (builtins.readFile ../../../deployments/homelab/hosts/inventory.json))
    hosts
    ;
in
{
  dendritic.hosts = lib.mapAttrs (_: _: {
    system = "x86_64-linux";
    stateVersion = "26.05";
    user = "funforgiven";
    homeProfiles = [ ];
    features = [ "homelab-cluster-host" ];
  }) hosts;
  flake.diskoConfigurations = lib.mapAttrs (
    name: _:
    let
      configuration = import ../../../deployments/homelab/hosts/disks.nix {
        config.networking.hostName = name;
        inherit lib;
      };
    in
    {
      inherit (configuration) disko;
    }
  ) hosts;
  nixos.modules.homelab-cluster-host.imports = [
    inputs.disko.nixosModules.disko
    inputs.sops-nix.nixosModules.sops
    ../../../deployments/homelab/hosts/common.nix
    ../../../deployments/homelab/hosts/disks.nix
  ];
}
