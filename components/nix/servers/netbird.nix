_: {
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
      source = ../../cloud/services/netbird;
    in
    {
      apps.netbird-admin = {
        meta.description = "Enroll homelab NetBird without printing credentials";
        program = "${
          pkgs.writeShellApplication {
            name = "netbird-admin";
            runtimeInputs = [
              pkgs.kubectl
              pkgs.sops
            ];
            text = ''exec ${python}/bin/python ${source}/admin.py "$@"'';
          }
        }/bin/netbird-admin";
      };
    };
}
