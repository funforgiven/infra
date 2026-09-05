{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      source = inputs.self;
      python = pkgs.python3.withPackages (pythonPackages: [
        pythonPackages.ansible
        pythonPackages.ansible-core
        pythonPackages.pyyaml
        pythonPackages.requests
      ]);

      gitlabChart = pkgs.fetchurl {
        url = "https://gitlab-charts.s3.amazonaws.com/gitlab-10.3.1.tgz";
        sha256 = "70f893db79d61e504a67d5cf75f64c92f5a2070b8132741105ffaf2368b848c7";
      };
      gitlabHelm =
        pkgs.runCommandLocal "gitlab-helm-check"
          {
            nativeBuildInputs = [
              python
              pkgs.kubernetes-helm
              pkgs.kustomize
              pkgs.gnutar
              pkgs.gzip
            ];
          }
          ''
            mkdir chart
            tar -xzf ${gitlabChart} -C chart
            python ${source}/components/cloud/services/gitlab/tests/check-chart.py ${source} "$PWD/chart/gitlab"
            touch "$out"
          '';

      pythonTests =
        pkgs.runCommandLocal "cloud-python-tests"
          {
            nativeBuildInputs = [ python ];
          }
          ''
            set -euo pipefail

            mkdir -p source/components source/deployments/homelab
            cp -R ${source}/components/cloud source/components/cloud
            cp -R ${source}/deployments/homelab/cloud source/deployments/homelab/cloud
            cp ${source}/deployments/homelab/ssh-host-keys.json \
              source/deployments/homelab/ssh-host-keys.json
            chmod -R u+w source
            cd source

            export ANSIBLE_HOME="$TMPDIR/ansible-home"
            export ANSIBLE_LOCAL_TEMP="$TMPDIR/ansible"
            export PYTHONPYCACHEPREFIX="$TMPDIR/pycache"
            mkdir -p "$ANSIBLE_HOME" "$ANSIBLE_LOCAL_TEMP"

            python -m unittest discover \
              -s components/cloud/network-automation/tests \
              -p 'test_*.py'
            python -m compileall -q \
              components/cloud \
              deployments/homelab/cloud/services
            python -m unittest discover \
              -s components/cloud/services/gitlab/tests -p 'test_*.py'

            touch "$out"
          '';

      ansibleChecks =
        pkgs.runCommandLocal "cloud-ansible-checks"
          {
            nativeBuildInputs = [ python ];
          }
          ''
            set -euo pipefail

            mkdir -p source/components source/deployments/homelab source/secrets
            cp -R ${source}/components/cloud source/components/cloud
            cp -R ${source}/deployments/homelab/cloud source/deployments/homelab/cloud
            cp ${source}/deployments/homelab/ssh-host-keys.json \
              source/deployments/homelab/ssh-host-keys.json
            cp ${source}/secrets/github-ssh-key.pub source/secrets/github-ssh-key.pub
            chmod -R u+w source
            cd source

            export ANSIBLE_HOME="$TMPDIR/ansible-home"
            export ANSIBLE_LOCAL_TEMP="$TMPDIR/ansible"
            export PYTHONPYCACHEPREFIX="$TMPDIR/pycache"
            mkdir -p "$ANSIBLE_HOME" "$ANSIBLE_LOCAL_TEMP"

            (
              cd components/cloud/host-automation
              ansible-inventory --graph >/dev/null
              for playbook in playbooks/*.yml; do
                ansible-playbook --syntax-check "$playbook"
              done

              umask 077
              mkdir -p "$TMPDIR/rendered-autoinstall"
              printf '%s\n' 'cloud-check-console-password' \
                > "$TMPDIR/autoinstall-password"
              ansible-playbook playbooks/render-autoinstall.yml \
                --extra-vars \
                  "autoinstall_output_directory=$TMPDIR/rendered-autoinstall" \
                --extra-vars \
                  "autoinstall_password_file=$TMPDIR/autoinstall-password"
            )
            ${pkgs.yamllint}/bin/yamllint -d relaxed \
              "$TMPDIR"/rendered-autoinstall/*.yaml

            (
              cd components/cloud/network-automation
              ansible-inventory --graph >/dev/null
              ansible-playbook --syntax-check reconcile-routeros.yaml
            )

            (
              cd components/cloud/capi-management
              ansible-inventory --graph >/dev/null
              ansible-playbook --syntax-check playbooks/bootstrap.yml
            )

            touch "$out"
          '';

      yamlChecks =
        pkgs.runCommandLocal "cloud-yaml-checks"
          {
            nativeBuildInputs = [ pkgs.yamllint ];
          }
          ''
            set -euo pipefail

            yamllint -d relaxed \
              ${source}/components/cloud \
              ${source}/deployments/homelab/cloud
            touch "$out"
          '';

      tofuFormat =
        pkgs.runCommandLocal "cloud-tofu-format"
          {
            nativeBuildInputs = [ pkgs.opentofu ];
          }
          ''
            set -euo pipefail

            tofu fmt -check -recursive ${source}/components/cloud
            touch "$out"
          '';

      kustomizeChecks =
        pkgs.runCommandLocal "cloud-kustomize-checks"
          {
            nativeBuildInputs = [
              pkgs.coreutils
              pkgs.findutils
              pkgs.kustomize
            ];
          }
          ''
            set -euo pipefail

            mkdir -p source/components/cloud source/deployments/homelab
            cp -R ${source}/components/cloud/tofu-controller-tenant \
              source/components/cloud/tofu-controller-tenant
            cp -R ${source}/deployments/homelab/cloud \
              source/deployments/homelab/cloud
            chmod -R u+w source
            cd source

            while IFS= read -r -d "" kustomization; do
              directory="$(dirname "$kustomization")"
              rendered="$TMPDIR/$(printf '%s' "$directory" | sha256sum | cut -d ' ' -f 1).yaml"
              kustomize build --load-restrictor LoadRestrictionsNone \
                "$directory" > "$rendered"
            done < <(
              find \
                components/cloud \
                deployments/homelab/cloud \
                -name kustomization.yaml \
                -print0 \
                | sort -z
            )

            touch "$out"
          '';

      shellChecks =
        pkgs.runCommandLocal "cloud-shell-checks"
          {
            nativeBuildInputs = [
              pkgs.findutils
              pkgs.shellcheck
            ];
          }
          ''
            set -euo pipefail

            find \
              ${source}/components/cloud \
              ${source}/deployments/homelab/cloud \
              -type f \
              -name '*.sh' \
              -print0 \
              | xargs -0 -r shellcheck
            touch "$out"
          '';
    in
    {
      checks = {
        gitlab-helm = gitlabHelm;
        cloud-ansible = ansibleChecks;
        cloud-kustomize = kustomizeChecks;
        cloud-python = pythonTests;
        cloud-shell = shellChecks;
        cloud-tofu-format = tofuFormat;
        cloud-yaml = yamlChecks;

        cloud-configuration = pkgs.linkFarm "cloud-configuration-check" [
          {
            name = "gitlab-helm";
            path = gitlabHelm;
          }
          {
            name = "ansible";
            path = ansibleChecks;
          }
          {
            name = "kustomize";
            path = kustomizeChecks;
          }
          {
            name = "python";
            path = pythonTests;
          }
          {
            name = "shell";
            path = shellChecks;
          }
          {
            name = "tofu-format";
            path = tofuFormat;
          }
          {
            name = "yaml";
            path = yamlChecks;
          }
        ];
      };
    };
}
