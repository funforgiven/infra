{ lib, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      source = lib.fileset.toSource {
        root = ../../..;
        fileset = lib.fileset.unions [
          ../../homelab
          ../../../deployments/homelab
        ];
      };
      python = pkgs.python3.withPackages (ps: [
        ps.ansible
        ps.ansible-core
        ps.boto3
        ps.jsonpatch
        ps.jsonschema
        (ps.matrix-nio.override { withVodozemac = true; })
        ps.pyyaml
        ps.requests
      ]);
      prepare = ''
        cp -R ${source}/components ./components
        cp -R ${source}/deployments ./deployments
        chmod -R u+w components deployments
        export ANSIBLE_HOME="$TMPDIR/ansible-home"
        export ANSIBLE_LOCAL_TEMP="$TMPDIR/ansible-local"
        export PYTHONPYCACHEPREFIX="$TMPDIR/pycache"
        mkdir -p "$ANSIBLE_HOME" "$ANSIBLE_LOCAL_TEMP"
      '';
      manifests =
        pkgs.runCommandLocal "homelab-manifests"
          {
            nativeBuildInputs = [
              python
              pkgs.kustomize
            ];
          }
          (
            prepare
            + ''
              python components/homelab/validation/validate.py
              touch "$out"
            ''
          );
      tests =
        pkgs.runCommandLocal "homelab-python"
          {
            nativeBuildInputs = [
              python
              pkgs.prometheus.cli
              pkgs.util-linux
              pkgs.jq
              pkgs.curl
              pkgs.openssl
            ];
          }
          (
            prepare
            + ''
              python -m compileall -q components/homelab deployments/homelab/cluster
              for folder in operations network-automation services/forge services/valheim services/home-automation services/unifi services/mail-aws services/netbird services/matrix; do
                python -m unittest discover -s "components/homelab/$folder/tests" -p 'test_*.py'
              done
              touch "$out"
            ''
          );
      format = pkgs.runCommandLocal "homelab-tofu-format" { nativeBuildInputs = [ pkgs.opentofu ]; } ''
        tofu fmt -check -recursive ${source}/components/homelab/providers
        touch "$out"
      '';
      ansible = pkgs.runCommandLocal "homelab-routeros-syntax" { nativeBuildInputs = [ python ]; } (
        prepare
        + ''
          cd components/homelab/network-automation
          ansible-inventory --graph >/dev/null
          ansible-playbook --syntax-check reconcile-routeros.yaml
          touch "$out"
        ''
      );
      shell =
        pkgs.runCommandLocal "homelab-shell"
          {
            nativeBuildInputs = [
              pkgs.findutils
              pkgs.shellcheck
            ];
          }
          ''
            find ${source}/components/homelab ${source}/deployments/homelab/cluster -type f -name '*.sh' -print0 | xargs -0 -r shellcheck
            touch "$out"
          '';
    in
    {
      checks = {
        homelab-manifests = manifests;
        homelab-python = tests;
        homelab-tofu-format = format;
        homelab-routeros-syntax = ansible;
        homelab-shell = shell;
        homelab-configuration = pkgs.linkFarm "homelab-configuration" [
          {
            name = "manifests";
            path = manifests;
          }
          {
            name = "python";
            path = tests;
          }
          {
            name = "tofu";
            path = format;
          }
          {
            name = "network";
            path = ansible;
          }
          {
            name = "shell";
            path = shell;
          }
        ];
      };
    };
}
