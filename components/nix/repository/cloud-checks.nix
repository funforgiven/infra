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
              pkgs.opentofu
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

            python components/cloud/policy/validate_management_policy.py \
              deployments/homelab/cloud/declarative-ownership.yaml \
              deployments/homelab/cloud/manual-exceptions.yaml

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
            tofu fmt -check -recursive components/cloud
            kustomize build deployments/homelab/cloud/undercloud >/dev/null
            kustomize build deployments/homelab/cloud/management >/dev/null
            kustomize build deployments/homelab/cloud/services >/dev/null
            kustomize build \
              deployments/homelab/cloud/services/12-observability \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/services/15-backup-controller \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/services/16-backup-policy \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/services/25-home-automation \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/services/40-media \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/services/50-synthetic-monitoring \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/undercloud/81-services-foundation \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/undercloud/82-services-cluster \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/undercloud/83-services-hosts \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/undercloud/84-mail-edge \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/undercloud/85-service-dns \
              >/dev/null
            python - <<'PY'
            import pathlib
            import re

            import yaml

            root = pathlib.Path("deployments/homelab/cloud")
            contract_document = yaml.safe_load(
                (root / "undercloud/82-services-cluster/runtime-contract.yaml").read_text()
            )
            contract = yaml.safe_load(contract_document["data"]["required-keys.yaml"])
            if contract["schemaVersion"] != 2:
                raise SystemExit("services runtime contract must use schema version 2")
            credentials = {
                key
                for group in contract["credentials"].values()
                for key in group
            }
            post_deployment_credentials = {
                key
                for group in contract["postDeploymentCredentials"].values()
                for key in group
            }
            post_foundation_credentials = {
                key
                for group in contract["postFoundationCredentials"].values()
                for key in group
            }
            host_credentials = {
                key
                for definition in contract["hostCredentials"].values()
                for key in definition["keys"]
            }
            if host_credentials != {"OPENAI_API_KEY"}:
                raise SystemExit("Hermes must have one independently routed OpenAI key")
            reconcile_document = yaml.safe_load_all(
                (root / "undercloud/82-services-cluster/reconcile.yaml").read_text()
            )
            reconcile_config = next(
                document
                for document in reconcile_document
                if document["kind"] == "ConfigMap"
            )
            reconcile_script = reconcile_config["data"]["reconcile.sh"]
            compile(
                reconcile_config["data"]["reconcile-resend.py"],
                "reconcile-resend.py",
                "exec",
            )
            validated = set(
                re.findall(r"^\s*require_file ([A-Z0-9_]+) ", reconcile_script, re.M)
            )
            expected_validated = (
                credentials
                | post_foundation_credentials
                | post_deployment_credentials
            )
            if expected_validated != validated:
                raise SystemExit(
                    f"runtime credential contract {sorted(expected_validated)} != "
                    f"reconciler validation {sorted(validated)}"
                )
            if "OPENAI_API_KEY" in reconcile_script:
                raise SystemExit("Hermes OpenAI key must not enter cluster reconciliation")

            runtime = yaml.safe_load(
                (root / "undercloud/81-services-foundation/runtime.sops.yaml").read_text()
            )
            generated = set(contract["generatedApplicationSecrets"])
            if not generated.issubset(runtime["data"]):
                raise SystemExit("generated application secrets are missing from SOPS")
            if any(
                not str(value).startswith("ENC[")
                for value in runtime["data"].values()
            ):
                raise SystemExit("runtime Secret contains a non-SOPS data value")

            hermes_runtime_path = root / "host-runtime/hermes.sops.yaml"
            hermes_runtime = yaml.safe_load(hermes_runtime_path.read_text())
            if hermes_runtime.get("schemaVersion") != 1:
                raise SystemExit("Hermes host runtime document has the wrong schema")
            if any(
                not str(value).startswith("ENC[")
                for value in hermes_runtime["data"].values()
            ):
                raise SystemExit("Hermes host runtime contains a non-SOPS data value")
            recipients = {
                entry["recipient"] for entry in hermes_runtime["sops"]["age"]
            }
            if recipients != {
                "age14xx2n9unst4zc02lt26fxez8hg9ke44hrwefm3c9w79fap29mpuqu26eea"
            }:
                raise SystemExit("Hermes host runtime must remain admin-recipient-only")

            exceptions = yaml.safe_load((root / "manual-exceptions.yaml").read_text())
            exception_ids = {entry["id"] for entry in exceptions["exceptions"]}
            if "hermes-openai-oauth-enrollment" in exception_ids:
                raise SystemExit("obsolete Hermes OAuth exception remains declared")

            sentinel_files = [
                root / "services/40-media/importer.yaml",
                root / "services/40-media/release-watcher.yaml",
                root / "versions.yaml",
            ]
            sentinel_count = 0
            for path in sentinel_files:
                text = path.read_text()
                pins = re.findall(
                    r"ghcr\.io/funforgiven/media-importer:[^@\s]+@sha256:[0-9a-f]{64}",
                    text,
                )
                if len(pins) != 1:
                    raise SystemExit(f"{path} must contain exactly one pinned media image")
                sentinel_count += pins[0].endswith("sha256:" + "0" * 64)
            if sentinel_count not in (0, len(sentinel_files)):
                raise SystemExit("media image promotion is only partially represented")
            waves = (root / "services/waves.yaml").read_text()
            if sentinel_count and not re.search(
                r"name: services-media.*?spec:\n  suspend: true", waves, re.S
            ):
                raise SystemExit("media promotion sentinel requires a suspended media wave")

            observability = (root / "services/12-observability/kube-prometheus-stack.yaml").read_text()
            velero = (root / "services/15-backup-controller/velero.yaml").read_text()
            for name, text in (("observability", observability), ("velero", velero)):
                if "suspend: true" in text:
                    raise SystemExit(f"{name} retains an inner suspension")
            forbidden = ("backup.invalid", "replace-before-activation", "chat_id: 0")
            if any(value in observability + velero for value in forbidden):
                raise SystemExit("a runtime placeholder remains in a Helm release")
            PY
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
