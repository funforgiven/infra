{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    {
      checks.routeros-configuration =
        pkgs.runCommandLocal "routeros-configuration-check"
          {
            nativeBuildInputs = [
              pkgs.bash
              pkgs.coreutils
              (pkgs.python3.withPackages (pythonPackages: [ pythonPackages.paramiko ]))
              pkgs.ripgrep
              pkgs.shellcheck
            ];
          }
          ''
            mkdir -p source/components source/deployments/homelab
            cp -R ${inputs.self}/components/routeros source/components/routeros
            cp -R ${inputs.self}/deployments/homelab/routeros source/deployments/homelab/routeros
            chmod -R u+w source
            patchShebangs source
            cd source
            components/routeros/validate.sh
            touch "$out"
          '';
    };
}
