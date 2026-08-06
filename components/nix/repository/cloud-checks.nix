{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (pythonPackages: [
        pythonPackages.ansible
        pythonPackages.ansible-core
        pythonPackages.pyyaml
        pythonPackages.requests
      ]);
    in
    {
      checks.cloud-configuration =
        pkgs.runCommandLocal "cloud-configuration-check"
          {
            nativeBuildInputs = [
              python
              pkgs.kustomize
              pkgs.ripgrep
              pkgs.shellcheck
              pkgs.yamllint
            ];
          }
          ''
            set -euo pipefail

            mkdir -p source/components source/deployments/homelab source/secrets
            cp -R ${inputs.self}/components/cloud source/components/cloud
            cp -R ${inputs.self}/deployments/homelab/cloud source/deployments/homelab/cloud
            cp ${inputs.self}/deployments/homelab/ssh-host-keys.json \
              source/deployments/homelab/ssh-host-keys.json
            cp ${inputs.self}/secrets/github-ssh-key.pub \
              source/secrets/github-ssh-key.pub
            chmod -R u+w source
            cd source

            export ANSIBLE_HOME="$TMPDIR/ansible-home"
            export ANSIBLE_LOCAL_TEMP="$TMPDIR/ansible"
            export PYTHONPYCACHEPREFIX="$TMPDIR/pycache"
            export XDG_CACHE_HOME="$TMPDIR/cache"
            mkdir -p "$ANSIBLE_HOME" "$ANSIBLE_LOCAL_TEMP" "$XDG_CACHE_HOME"

            python -m unittest discover \
              -s components/cloud/network-automation/tests -p 'test_*.py'

            (
              cd components/cloud/host-automation
              ansible-inventory --graph >/dev/null
              ansible-inventory --list > "$TMPDIR/cloud-inventory.json"
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

            yamllint -d relaxed "$TMPDIR"/rendered-autoinstall/*.yaml
            python - \
              "$TMPDIR/cloud-inventory.json" \
              "$TMPDIR/rendered-autoinstall" <<'PY'
            import json
            import pathlib
            import sys

            import yaml

            inventory = json.loads(pathlib.Path(sys.argv[1]).read_text())
            rendered_directory = pathlib.Path(sys.argv[2])
            expected = set(inventory["cloud_hosts"]["hosts"])
            rendered = {
                path.name.removesuffix("-user-data.yaml"): path
                for path in rendered_directory.glob("*-user-data.yaml")
            }
            if set(rendered) != expected:
                raise SystemExit(
                    f"rendered host set {sorted(rendered)} != inventory {sorted(expected)}"
                )

            hostvars = inventory["_meta"]["hostvars"]
            forbidden = ("{{", "}}", "{%", "%}", "__PASSWORD_HASH__", "__SSH_PUBLIC_KEY__")
            for host, path in sorted(rendered.items()):
                text = path.read_text(encoding="utf-8")
                if any(token in text for token in forbidden):
                    raise SystemExit(f"{path.name} contains an unresolved template token")
                document = yaml.safe_load(text)["autoinstall"]
                if document["identity"]["hostname"] != host:
                    raise SystemExit(f"{path.name} has the wrong hostname")
                variables = hostvars[host]
                vlans = document["network"]["vlans"]
                management = vlans[f'{variables["cloud_bond_name"]}.20']
                address = variables["cloud_vlan_addresses"].get(
                    "20", variables["cloud_vlan_addresses"].get(20)
                )
                expected_address = f'{address}/{variables["cloud_host_prefix_length"]}'
                if expected_address not in management["addresses"]:
                    raise SystemExit(f"{path.name} has the wrong management address")
            PY
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

            yamllint -d relaxed components/cloud deployments/homelab/cloud
            kustomize build deployments/homelab/cloud/undercloud >/dev/null
            kustomize build deployments/homelab/cloud/management >/dev/null
            for bootstrap_phase in components sync; do
              kustomize build --load-restrictor LoadRestrictionsNone \
                "deployments/homelab/cloud/management/bootstrap/$bootstrap_phase" \
                >/dev/null
            done
            shellcheck components/cloud/host-automation/build-autoinstall-iso.sh

            touch "$out"
          '';
    };
}
