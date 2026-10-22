{ config, lib, ... }:
let
  inventory = lib.importJSON ../../../deployments/homelab/hosts/inventory.json;
  host = config.flake.nixosConfigurations.${lib.head (lib.attrNames inventory.hosts)};
in
{
  perSystem =
    { pkgs, ... }:
    let
      pins = lib.importJSON ../../../deployments/homelab/validation/pins.json;
      # The store name follows url and ref, so bumping either one without the
      # hash fails instead of silently reusing the previous download.
      fetchPin =
        pin:
        let
          name =
            "pin-" + builtins.substring 0 32 (builtins.hashString "sha256" "${pin.url}@${pin.ref or ""}");
          reference =
            if lib.hasPrefix "sha256:" pin.ref then
              "${pin.url}@${pin.ref}"
            else
              "${pin.url} --version ${pin.ref}";
        in
        if lib.hasPrefix "oci://" pin.url then
          pkgs.runCommand name
            {
              nativeBuildInputs = [ pkgs.kubernetes-helm ];
              outputHashAlgo = "sha256";
              outputHashMode = "flat";
              outputHash = pin.sha256;
              SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
            }
            ''
              export HOME="$TMPDIR"
              mkdir pulled
              helm pull ${reference} --destination pulled
              mv pulled/*.tgz "$out"
            ''
        else
          pkgs.fetchurl {
            inherit name;
            inherit (pin) url sha256;
          };
      validationInputs = pkgs.writeText "homelab-validation-inputs.json" (
        builtins.toJSON {
          kubeVersion = lib.head (lib.splitString "+" host.config.services.k3s.package.version);
          kubernetes = fetchPin pins.kubernetes;
          kubevirt = fetchPin pins.kubevirt;
          charts = lib.mapAttrs (_: pin: {
            archive = fetchPin pin;
            dependencies = map fetchPin (pin.dependencies or [ ]);
          }) pins.charts;
        }
      );
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
              pkgs.kubernetes-helm
              pkgs.kustomize
            ];
            passthru.inputs = validationInputs;
          }
          (
            prepare
            + ''
              export HOME="$TMPDIR"
              python components/homelab/validation/validate.py --inputs ${validationInputs}
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
              for folder in $(find components/homelab deployments/homelab -type d -name tests); do
                python -m unittest discover -s "$folder" -p 'test_*.py'
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
