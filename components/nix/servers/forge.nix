_: {
  perSystem =
    { pkgs, lib, ... }:
    let
      source = ../../homelab/services/forge;
      python = pkgs.python3.withPackages (ps: [
        ps.pyyaml
        ps.requests
      ]);
      # Operator scripts run from the repository root: they read and write
      # SOPS files by repository-relative path.
      app =
        name:
        {
          script,
          description,
          runtimeInputs ? [ ],
        }:
        {
          meta.description = description;
          program = "${
            pkgs.writeShellApplication {
              inherit name;
              runtimeInputs = [ pkgs.sops ] ++ runtimeInputs;
              text = ''
                export PYTHONPATH=${../../homelab/operations}
                exec ${python}/bin/python ${source}/${script} "$@"
              '';
            }
          }/bin/${name}";
        };
    in
    {
      apps = lib.mapAttrs app {
        publish-image = {
          script = "publish-image.py";
          description = "Push a Nix-built image archive to the Forgejo registry and print its digest";
          runtimeInputs = [ pkgs.skopeo ];
        };
        forge-enroll = {
          script = "enroll.py";
          description = "Reconcile Forgejo's encrypted local runtime secrets";
        };
        forge-enroll-runners = {
          script = "enroll-runners.py";
          description = "Enroll the forge-runner account, qualification repository and CI tokens";
        };
        forge-enroll-agent-sessions = {
          script = "enroll-agent-sessions.py";
          description = "Renew the Atollion agents' Forgejo web sessions";
        };
      };
    };
}
