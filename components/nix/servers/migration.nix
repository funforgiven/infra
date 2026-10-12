_: {
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
      app =
        name: script:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = [
            pkgs.sops
            pkgs.openssl
            pkgs.kustomize
          ];
          text = "exec ${python}/bin/python ${../../homelab/operations}/${script} \"$@\"";
        };
      state = app "migration-provider-state" "provider_state.py";
      credentials = app "render-cluster-credentials" "render_credentials.py";
      certificates = app "migration-certificate-bundle" "certificate_bundle.py";
      volumes = app "migration-volume-plan" "volume_plan.py";
      databases = app "migration-database-bootstrap" "database_bootstrap.py";
      capture = pkgs.writeShellApplication {
        name = "migration-source-capture";
        runtimeInputs = [
          pkgs.nix
          pkgs.gitMinimal
          pkgs.sops
          pkgs.openssl
        ];
        text = "exec ${python}/bin/python ${../../homelab/operations}/source_capture.py \"$@\"";
      };
    in
    {
      apps.migration-source-capture = {
        program = "${capture}/bin/migration-source-capture";
        meta.description = "Read the frozen source and encrypt a fresh private recovery capture; no live writes";
      };
      apps.migration-provider-state = {
        program = "${state}/bin/migration-provider-state";
        meta.description = "Export encrypted archived provider state without remote API calls";
      };
      apps.migration-database-bootstrap = {
        program = "${databases}/bin/migration-database-bootstrap";
        meta.description = "Export a private database-only restore bootstrap without cluster calls";
      };
      apps.migration-volume-plan = {
        program = "${volumes}/bin/migration-volume-plan";
        meta.description = "Render offline transfer manifests for an inventoried claim";
      };
      apps.migration-certificate-bundle = {
        program = "${certificates}/bin/migration-certificate-bundle";
        meta.description = "Export validated retained TLS/account Secrets for one-time recovery";
      };
      apps.render-cluster-credentials = {
        program = "${credentials}/bin/render-cluster-credentials";
        meta.description = "Refresh concrete SOPS application Secrets from local enrollment inputs";
      };
    };
}
