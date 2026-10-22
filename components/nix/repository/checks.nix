{ config, lib, ... }:
{
  perSystem =
    { system, ... }:
    {
      checks = lib.concatMapAttrs (
        hostname: host:
        let
          hostConfig = config.flake.nixosConfigurations.${hostname}.config;
          userName = config.users.${host.user}.username;
        in
        {
          "${hostname}-toplevel" = hostConfig.system.build.toplevel;
        }
        // lib.optionalAttrs (host.homeProfiles != [ ]) {
          "${hostname}-home" = hostConfig.home-manager.users.${userName}.home.activationPackage;
        }
      ) (lib.filterAttrs (_: host: host.system == system) config.dendritic.hosts);
    };
}
