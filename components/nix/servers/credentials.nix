_: {
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
      app =
        name: script:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = [ pkgs.sops ];
          text = "exec ${python}/bin/python ${../../homelab/operations}/${script} \"$@\"";
        };
      state = app "provider-state" "provider_state.py";
      credentials = app "render-cluster-credentials" "render_credentials.py";
    in
    {
      apps.provider-state = {
        program = "${state}/bin/provider-state";
        meta.description = "Export encrypted provider state without remote API calls";
      };
      apps.render-cluster-credentials = {
        program = "${credentials}/bin/render-cluster-credentials";
        meta.description = "Refresh concrete SOPS application Secrets from local enrollment inputs";
      };
    };
}
