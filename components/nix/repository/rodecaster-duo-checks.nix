{ config, lib, ... }:
{
  perSystem =
    { pkgs, system, ... }:
    {
      checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
        rodecaster-duo-ucm = pkgs.runCommandLocal "rodecaster-duo-ucm-check" { } ''
          ${pkgs.python3}/bin/python3 ${../rodecaster-duo/check-ucm.py} \
            ${config.flake.nixosConfigurations.parmigiano.config.system.build.rodecaster-duo-ucm} \
            ${pkgs.alsa-lib}/lib/libasound.so.2
          touch "$out"
        '';
      };
    };
}
