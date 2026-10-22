_: {
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
    in
    {
      apps.cluster-access = {
        meta.description = "Run a command with an ephemeral homelab kubeconfig";
        program = "${
          pkgs.writeShellApplication {
            name = "cluster-access";
            runtimeInputs = [
              pkgs.openssh
              pkgs.kubectl
            ];
            text = ''
              export HOMELAB_INVENTORY=${../../../deployments/homelab/hosts/inventory.json}
              exec ${python}/bin/python ${../../homelab/operations/cluster_access.py} "$@"
            '';
          }
        }/bin/cluster-access";
      };
    };
}
