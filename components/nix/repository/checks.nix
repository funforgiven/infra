{
  config,
  lib,
  ...
}:
let
  hostChecksFor =
    system:
    lib.mergeAttrsList (
      lib.mapAttrsToList (
        hostname: host:
        let
          user = config.users.${host.user};
          homeConfigurationName = "${user.username}@${hostname}";
        in
        {
          "${hostname}-toplevel" = config.flake.nixosConfigurations.${hostname}.config.system.build.toplevel;
        }
        // lib.optionalAttrs (host.homeProfiles != [ ]) {
          "${hostname}-home" = config.flake.homeConfigurations.${homeConfigurationName}.activationPackage;
        }
      ) (lib.filterAttrs (_: host: host.system == system) config.dendritic.hosts)
    );
in
{
  perSystem = { system, ... }: {
    checks = hostChecksFor system;
  };
}
