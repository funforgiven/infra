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
              deployments/homelab/cloud/undercloud/79-openai-control-plane \
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
            if contract["schemaVersion"] != 5:
                raise SystemExit("services runtime contract must use schema version 5")
            credentials = {
                key
                for group in contract["credentials"].values()
                for key in group
            }
            expected_host_credentials = {
                "hermes": {
                    "HERMES_TELEGRAM_BOT_TOKEN",
                },
            }
            host_credentials = {
                consumer: set(definition["keys"])
                for consumer, definition in contract["hostCredentials"].items()
            }
            if host_credentials != expected_host_credentials:
                raise SystemExit("host credentials are not independently routed")
            controller_credentials = {
                consumer: set(definition["keys"])
                for consumer, definition in contract["controllerCredentials"].items()
            }
            if controller_credentials != {
                "openai-control-plane": {"OPENAI_ADMIN_KEY"}
            }:
                raise SystemExit("controller credentials are not independently routed")
            generated_definitions = contract["generatedSecrets"]
            provisioned_definitions = contract["provisionedSecrets"]
            expected_provisioned = {
                "openai-hermes": (
                    "reconcile-services-openai",
                    {"OPENAI_API_KEY"},
                ),
                "backblaze-services": (
                    "reconcile-services-backblaze",
                    {"B2_APPLICATION_KEY_ID", "B2_APPLICATION_KEY"},
                ),
                "backblaze-hosts": (
                    "reconcile-services-backblaze",
                    {
                        "HERMES_BACKUP_B2_APPLICATION_KEY_ID",
                        "HERMES_BACKUP_B2_APPLICATION_KEY",
                        "HOME_ASSISTANT_BACKUP_B2_APPLICATION_KEY_ID",
                        "HOME_ASSISTANT_BACKUP_B2_APPLICATION_KEY",
                        "MAIL_EDGE_BACKUP_B2_APPLICATION_KEY_ID",
                        "MAIL_EDGE_BACKUP_B2_APPLICATION_KEY",
                    },
                ),
                "telegram-infrastructure": (
                    "reconcile-services-telegram",
                    {"INFRA_TELEGRAM_CHAT_ID"},
                ),
                "telegram-media": (
                    "reconcile-services-telegram",
                    {"MEDIA_TELEGRAM_CHAT_ID"},
                ),
                "telegram-hermes": (
                    "reconcile-services-telegram",
                    {
                        "HERMES_TELEGRAM_ALLOWED_USERS",
                        "HERMES_TELEGRAM_HOME_CHANNEL",
                    },
                ),
                "operator-network": (
                    "reconcile-services-operator-network",
                    {"MAIL_MANAGEMENT_CIDRS_JSON"},
                ),
                "resend-mail-edge": (
                    "reconcile-services-resend",
                    {"STALWART_RESEND_API_KEY"},
                ),
                "karakeep-hermes": (
                    "karakeep-ui",
                    {"HERMES_KARAKEEP_API_KEY"},
                ),
                "karakeep-media": (
                    "karakeep-ui",
                    {"RELEASE_WATCHER_KARAKEEP_API_KEY"},
                ),
            }
            actual_provisioned = {
                consumer: (definition["provisioner"], set(definition["keys"]))
                for consumer, definition in provisioned_definitions.items()
            }
            if actual_provisioned != expected_provisioned:
                raise SystemExit("provider-provisioned credentials are not independently routed")
            cluster_generated = {
                key
                for definition in generated_definitions.values()
                if definition["secretFile"] == contract["secretFile"]
                for key in definition["keys"]
            }
            cluster_provisioned = {
                key
                for definition in provisioned_definitions.values()
                if definition["secretFile"] == contract["secretFile"]
                for key in definition["keys"]
            }
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
                | cluster_generated
                | cluster_provisioned
            )
            if expected_validated != validated:
                raise SystemExit(
                    f"runtime credential contract {sorted(expected_validated)} != "
                    f"reconciler validation {sorted(validated)}"
                )
            if "OPENAI_API_KEY" in reconcile_script:
                raise SystemExit("Hermes OpenAI key must not enter cluster reconciliation")

            openai_admin = yaml.safe_load(
                (root / "undercloud/79-openai-control-plane/admin.sops.yaml").read_text()
            )
            if openai_admin["metadata"] != {
                "name": "openai-admin",
                "namespace": "tofu-system",
            }:
                raise SystemExit("OpenAI Admin key has the wrong controller boundary")
            if any(
                not str(value).startswith("ENC[")
                for value in openai_admin["data"].values()
            ):
                raise SystemExit("OpenAI Admin Secret contains non-SOPS data")
            openai_admin_recipients = {
                entry["recipient"] for entry in openai_admin["sops"]["age"]
            }
            if openai_admin_recipients != {
                "age14xx2n9unst4zc02lt26fxez8hg9ke44hrwefm3c9w79fap29mpuqu26eea",
                "age19ep2ztjlquplkgts8kstufgcx9add4enwn2dzsy6s7euy2scvvksgwevv2",
            }:
                raise SystemExit("OpenAI Admin Secret has the wrong recipients")

            runtime = yaml.safe_load(
                (root / "undercloud/81-services-foundation/runtime.sops.yaml").read_text()
            )
            if not cluster_generated.issubset(runtime["data"]):
                raise SystemExit("generated cluster secrets are missing from SOPS")
            if any(
                not str(value).startswith("ENC[")
                for value in runtime["data"].values()
            ):
                raise SystemExit("runtime Secret contains a non-SOPS data value")

            host_secret_files = {
                definition["secretFile"]
                for definition in contract["hostCredentials"].values()
            } | {
                definition["secretFile"]
                for definition in generated_definitions.values()
                if definition["secretFile"].startswith(
                    "deployments/homelab/cloud/host-runtime/"
                )
            } | {
                definition["secretFile"]
                for definition in provisioned_definitions.values()
                if definition["secretFile"].startswith(
                    "deployments/homelab/cloud/host-runtime/"
                )
            }
            generated_by_file = {
                definition["secretFile"]: set(definition["keys"])
                for definition in generated_definitions.values()
            }
            for relative_path in host_secret_files:
                host_runtime = yaml.safe_load(
                    (pathlib.Path(relative_path)).read_text()
                )
                if host_runtime.get("schemaVersion") != 1:
                    raise SystemExit(
                        f"{relative_path} host runtime document has the wrong schema"
                    )
                if not generated_by_file.get(relative_path, set()).issubset(
                    host_runtime["data"]
                ):
                    raise SystemExit(
                        f"{relative_path} is missing generated host secrets"
                    )
                if any(
                    not str(value).startswith("ENC[")
                    for value in host_runtime["data"].values()
                ):
                    raise SystemExit(
                        f"{relative_path} contains a non-SOPS data value"
                    )
                recipients = {
                    entry["recipient"] for entry in host_runtime["sops"]["age"]
                }
                if recipients != {
                    "age14xx2n9unst4zc02lt26fxez8hg9ke44hrwefm3c9w79fap29mpuqu26eea"
                }:
                    raise SystemExit(
                        f"{relative_path} must remain admin-recipient-only"
                    )

            backup_destination = yaml.safe_load(
                (root / "backup-destination.yaml").read_text()
            )
            services_backup = yaml.safe_load(
                (root / "undercloud/81-services-foundation/backup.yaml").read_text()
            )
            if services_backup["data"] != {
                "bucket_name": backup_destination["bucket"]["name"],
                "endpoint": backup_destination["bucket"]["s3Endpoint"],
                "region": "us-west-004",
                "prefix": "services/kubernetes",
            }:
                raise SystemExit("services backup destination diverges from Backblaze B2")
            required_b2_capabilities = {
                "deleteFiles",
                "listAllBucketNames",
                "listFiles",
                "readFiles",
                "writeFiles",
            }
            b2_services = backup_destination["services"]
            if set(b2_services["kubernetes"]["capabilities"]) != required_b2_capabilities:
                raise SystemExit("Velero B2 key capabilities are not least privilege")
            if set(b2_services["hostCapabilities"]) != required_b2_capabilities:
                raise SystemExit("host B2 key capabilities are not least privilege")
            if backup_destination["bucket"]["operatorBootstrap"] != {
                "applicationKeyIdFile": "secrets/B2_MASTER_APPLICATION_KEY_ID.key",
                "applicationKeyFile": "secrets/B2_MASTER_APPLICATION_KEY.key",
                "clearAfterSuccess": True,
            }:
                raise SystemExit("Backblaze master bootstrap is not ephemeral")

            telegram = yaml.safe_load((root / "telegram-bots.yaml").read_text())
            if {
                definition["username"]
                for definition in telegram["bots"].values()
            } != {
                "fahrican_infra_alerts_bot",
                "fahrican_hermes_bot",
                "fahrican_media_watch_bot",
            }:
                raise SystemExit("Telegram bot identity contract drifted")

            exceptions = yaml.safe_load((root / "manual-exceptions.yaml").read_text())
            exception_ids = {entry["id"] for entry in exceptions["exceptions"]}
            if "hermes-openai-oauth-enrollment" in exception_ids:
                raise SystemExit("obsolete Hermes OAuth exception remains declared")
            if "openai-api-key-issuance" in exception_ids:
                raise SystemExit("manual Hermes OpenAI runtime-key issuance remains")
            if "openai-admin-key-bootstrap" not in exception_ids:
                raise SystemExit("OpenAI credential-zero bootstrap is undocumented")
            if "openai-organization-hosted-tool-policy" not in exception_ids:
                raise SystemExit("OpenAI organization tool-policy exception is undocumented")

            openai_tofu = pathlib.Path(
                "components/cloud/services/openai/tofu/main.tf"
            ).read_text()
            openai_contract = yaml.safe_load(
                (root / "openai-hermes.yaml").read_text()
            )
            if openai_contract.get("administrationKeyName") != (
                "fahrican-infra-openai-control-plane"
            ):
                raise SystemExit("OpenAI Admin-key retirement target drifted")
            if openai_contract.get("policy") != {
                "modelIds": ["gpt-5.6-luna"],
                "hostedTools": [
                    "code_interpreter",
                    "file_search",
                    "image_generation",
                    "mcp",
                    "web_search",
                ],
                "hardSpendLimit": {
                    "thresholdAmount": 5000,
                    "currency": "USD",
                    "interval": "month",
                },
            }:
                raise SystemExit("Hermes OpenAI retirement policy drifted")
            required_openai_declarations = (
                'source  = "openai/openai"',
                'version = "= 1.1.0"',
                'permissions = local.runtime_permissions',
                'runtime_permissions  = ["api.responses.write"]',
                'model_ids  = ["gpt-5.6-luna"]',
                'threshold_amount = 5000',
                'resource "openai_project_hosted_tool_permissions" "hermes"',
                'file_search_enabled      = false',
                'web_search_enabled       = false',
                'image_generation_enabled = false',
                'mcp_enabled              = false',
                'code_interpreter_enabled = false',
            )
            if any(value not in openai_tofu for value in required_openai_declarations):
                raise SystemExit("Hermes OpenAI control plane is not least privilege")
            if "openai_project_rate_limit" in openai_tofu:
                raise SystemExit("OpenAI rate-limit records must not be selected dynamically")

            openai_manifests = list(yaml.safe_load_all(
                (root / "undercloud/79-openai-control-plane/tofu.yaml").read_text()
            ))
            openai_source = next(
                item for item in openai_manifests if item["kind"] == "GitRepository"
            )
            openai_controller = next(
                item for item in openai_manifests if item["kind"] == "Terraform"
            )
            if openai_source["spec"].get("verify") != {
                "mode": "HEAD",
                "secretRef": {"name": "openai-tofu-signing-key"},
            }:
                raise SystemExit("OpenAI OpenTofu source does not require signed commits")
            env_sources = openai_controller["spec"]["runnerPodTemplate"]["spec"]["envFrom"]
            if env_sources != [{"secretRef": {"name": "openai-admin"}}]:
                raise SystemExit("OpenAI controller does not use its isolated Admin Secret")
            undercloud_waves = (root / "undercloud/20-gitops/waves.yaml").read_text()
            if not re.search(
                r"name: wave79-openai-control-plane.*?spec:\n  suspend: true",
                undercloud_waves,
                re.S,
            ):
                raise SystemExit("OpenAI control plane lacks an explicit activation gate")

            repository_text = "\n".join(
                path.read_text(errors="ignore")
                for path in pathlib.Path(".").rglob("*")
                if path.is_file() and ".terraform" not in path.parts
            )
            if "OPENAI_API_KEY.key" in repository_text:
                raise SystemExit("derived Hermes OpenAI key still has an intake file")

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
