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

            role = pathlib.Path("components/cloud/host-automation/roles/cloud_host")
            defaults = yaml.safe_load((role / "defaults/main.yml").read_text())
            if defaults["cloud_libvirt_qemu_uid"] != 42424:
                raise SystemExit("containerized QEMU UID contract changed")
            if "acl" not in defaults["cloud_packages"]:
                raise SystemExit("KVM access policy requires the acl package")
            kvm_rule = (role / "templates/cloud-kvm.rules.j2").read_text()
            expected_acl = "setfacl -m u:{{ cloud_libvirt_qemu_uid }}:rw /dev/kvm"
            if expected_acl not in kvm_rule or 'MODE="0660"' not in kvm_rule:
                raise SystemExit("KVM udev policy is not least privilege")
            kernel_tasks = yaml.safe_load((role / "tasks/kernel.yml").read_text())
            task_names = {task.get("name") for task in kernel_tasks}
            required_tasks = {
                "Check that the containerized QEMU UID is host-local unused",
                "Persist least-privilege KVM access for containerized QEMU",
                "Reconcile the active KVM device policy",
                "Require containerized QEMU access without world-writable KVM",
            }
            if not required_tasks <= task_names:
                raise SystemExit("KVM access reconciliation contract is incomplete")
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
            if contract["schemaVersion"] != 7:
                raise SystemExit("services runtime contract must use schema version 7")
            credentials = {
                key
                for group in contract["credentials"].values()
                for key in group
            }
            expected_host_credentials = {
                "hermes": {
                    "HERMES_TELEGRAM_BOT_TOKEN",
                    "OPENAI_API_KEY",
                },
            }
            host_credentials = {
                consumer: set(definition["keys"])
                for consumer, definition in contract["hostCredentials"].items()
            }
            if host_credentials != expected_host_credentials:
                raise SystemExit("host credentials are not independently routed")
            generated_definitions = contract["generatedSecrets"]
            provisioned_definitions = contract["provisionedSecrets"]
            expected_provisioned = {
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
            reconcile_cronjob = next(
                document
                for document in yaml.safe_load_all(
                    (root / "undercloud/82-services-cluster/reconcile.yaml").read_text()
                )
                if document["kind"] == "CronJob"
            )
            reconcile_pod = reconcile_cronjob["spec"]["jobTemplate"]["spec"][
                "template"
            ]["spec"]
            reconcile_container = next(
                container
                for container in reconcile_pod["containers"]
                if container["name"] == "reconcile"
            )
            reconcile_environment = {
                item["name"]: item.get("value")
                for item in reconcile_container["env"]
            }
            if reconcile_environment.get("HOME") != "/tmp":
                raise SystemExit("services reconciler needs a writable home")
            if reconcile_environment.get("SHELL") != "/bin/sh":
                raise SystemExit(
                    "Magnum kubeconfig export needs an explicit shell"
                )
            pod_security = reconcile_pod["securityContext"]
            if pod_security.get("runAsUser") != 65532 or not pod_security.get(
                "runAsNonRoot"
            ):
                raise SystemExit("services reconciler must remain non-root")
            if pod_security.get("fsGroup") != 65532:
                raise SystemExit(
                    "services reconciler needs an explicit filesystem group"
                )
            secret_volumes = {
                volume["name"]: volume["secret"]
                for volume in reconcile_pod["volumes"]
                if "secret" in volume
            }
            for volume_name in ("bootstrap", "runtime-bootstrap"):
                if secret_volumes[volume_name].get("defaultMode") != 0o440:
                    raise SystemExit(
                        f"{volume_name} must be group-readable by the non-root reconciler"
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

            mail_tofu = yaml.safe_load(
                (root / "undercloud/84-mail-edge/tofu.yaml").read_text()
            )
            if mail_tofu["spec"].get("varsFrom") != [
                {
                    "kind": "Secret",
                    "name": "mail-edge-tofu-inputs",
                    "varsKeys": ["management_cidrs"],
                }
            ]:
                raise SystemExit("mail-edge Terraform input is not interface-scoped")
            mail_runner_environment = {
                item["name"]
                for item in mail_tofu["spec"]["runnerPodTemplate"]["spec"]["env"]
            }
            if any(name.startswith("TF_VAR_") for name in mail_runner_environment):
                raise SystemExit("mail-edge Terraform bypasses the varsFrom interface")
            if (
                "--from-file=management_cidrs="
                "/runtime-bootstrap/MAIL_MANAGEMENT_CIDRS_JSON"
                not in reconcile_script
            ):
                raise SystemExit("mail-edge Terraform input is not reconciled in memory")
            foundation = yaml.safe_load(
                (
                    root
                    / "undercloud/81-services-foundation/kustomization.yaml"
                ).read_text()
            )
            if "mail-edge-tofu-input.yaml" not in foundation["resources"]:
                raise SystemExit("mail-edge Terraform input target is not predeclared")
            reconcile_rbac = list(
                yaml.safe_load_all(
                    (root / "undercloud/82-services-cluster/rbac.yaml").read_text()
                )
            )
            mail_input_role = next(
                document
                for document in reconcile_rbac
                if document["kind"] == "Role"
                and document["metadata"]["name"] == "mail-edge-tofu-input-writer"
            )
            if mail_input_role["rules"] != [
                {
                    "apiGroups": [""],
                    "resources": ["secrets"],
                    "resourceNames": ["mail-edge-tofu-inputs"],
                    "verbs": ["get", "patch", "update"],
                }
            ]:
                raise SystemExit("mail-edge Terraform input writer is over-privileged")

            runtime = yaml.safe_load(
                (root / "undercloud/81-services-foundation/runtime.sops.yaml").read_text()
            )
            expected_runtime_keys = (
                credentials | cluster_generated | cluster_provisioned
            )
            if set(runtime["data"]) != expected_runtime_keys:
                raise SystemExit("cluster SOPS keys diverge from the runtime contract")
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
                "readBuckets",
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
            }:
                raise SystemExit("Telegram bot identity contract drifted")

            exceptions = yaml.safe_load((root / "manual-exceptions.yaml").read_text())
            exception_ids = {entry["id"] for entry in exceptions["exceptions"]}
            if "hermes-openai-oauth-enrollment" in exception_ids:
                raise SystemExit("obsolete Hermes OAuth exception remains declared")
            if "openai-api-key-issuance" not in exception_ids:
                raise SystemExit("operator-issued OpenAI runtime key is undocumented")
            if {
                "openai-admin-key-bootstrap",
                "openai-organization-hosted-tool-policy",
            } & exception_ids:
                raise SystemExit("obsolete OpenAI administration exception remains")

            repository_text = "\n".join(
                path.read_text(errors="ignore")
                for path in pathlib.Path(".").rglob("*")
                if path.is_file() and ".terraform" not in path.parts
            )
            openai_intake_name = "OPENAI_API_KEY" + ".key"
            if openai_intake_name not in repository_text:
                raise SystemExit("Hermes OpenAI intake contract is undocumented")
            obsolete_openai_control_plane = (
                "OPENAI_" + "ADMIN_KEY",
                "reconcile-services-" + "openai",
                "79-" + "openai-control-plane",
                "openai/" + "openai",
            )
            if any(value in repository_text for value in obsolete_openai_control_plane):
                raise SystemExit("obsolete OpenAI administration machinery remains")

            primary_controller_documents = yaml.safe_load_all(
                (
                    root
                    / "undercloud/32-identity-controllers/tofu-controller.yaml"
                ).read_text()
            )
            primary_controller = next(
                document
                for document in primary_controller_documents
                if document.get("kind") == "HelmRelease"
                and document.get("metadata", {}).get("name") == "tofu-controller"
            )
            primary_values = primary_controller["spec"]["values"]
            tenant_controller = yaml.safe_load(
                pathlib.Path(
                    "components/cloud/tofu-controller-tenant/controller.yaml"
                ).read_text()
            )
            tenant_values = tenant_controller["spec"]["values"]
            if primary_values["watchAllNamespaces"] or tenant_values["watchAllNamespaces"]:
                raise SystemExit("tofu-controller instances must remain namespace scoped")
            if tenant_values["rbac"]["create"]:
                raise SystemExit("tenant tofu-controller must use explicit namespaced RBAC")
            tenant_rbac = list(
                yaml.safe_load_all(
                    pathlib.Path(
                        "components/cloud/tofu-controller-tenant/rbac.yaml"
                    ).read_text()
                )
            )
            if {document["kind"] for document in tenant_rbac} - {"Role", "RoleBinding"}:
                raise SystemExit("tenant tofu-controller RBAC must not be cluster scoped")

            terraform_namespaces = set()
            for path in (root / "undercloud").rglob("*.yaml"):
                for document in yaml.safe_load_all(path.read_text()):
                    if isinstance(document, dict) and document.get("kind") == "Terraform":
                        terraform_namespaces.add(document["metadata"]["namespace"])
            tenant_overlays = {
                yaml.safe_load(path.read_text())["namespace"]
                for path in (root / "undercloud").glob(
                    "*/tofu-controller/kustomization.yaml"
                )
            }
            controller_namespaces = {"tofu-system"} | tenant_overlays
            if controller_namespaces != terraform_namespaces:
                raise SystemExit(
                    "namespace-scoped tofu-controller coverage "
                    f"{sorted(controller_namespaces)} != Terraform namespaces "
                    f"{sorted(terraform_namespaces)}"
                )

            for path in (root / "undercloud").rglob("*.yaml"):
                for document in yaml.safe_load_all(path.read_text()):
                    if not isinstance(document, dict) or document.get("kind") != "Kustomization":
                        continue
                    spec = document.get("spec", {})
                    source_path = spec.get("path")
                    if not isinstance(source_path, str) or not source_path.startswith("./"):
                        continue
                    managed_path = pathlib.Path(source_path.removeprefix("./"))
                    if not managed_path.is_dir() or not any(
                        managed_path.rglob("*.sops.yaml")
                    ):
                        continue
                    if spec.get("decryption") != {
                        "provider": "sops",
                        "secretRef": {"name": "sops-age"},
                    }:
                        name = document.get("metadata", {}).get("name", "<unknown>")
                        raise SystemExit(
                            f"Flux Kustomization {name} owns SOPS resources without decryption"
                        )

            media_root = root / "services/40-media"
            media_kustomization = yaml.safe_load(
                (media_root / "kustomization.yaml").read_text()
            )
            if set(media_kustomization["resources"]) != {
                "storage.yaml",
                "sftpgo.yaml",
                "navidrome.yaml",
                "routes.yaml",
                "monitoring.yaml",
                "network-policy.yaml",
            }:
                raise SystemExit("media service set must remain the direct upload workflow")
            sftpgo = (media_root / "sftpgo.yaml").read_text()
            navidrome = (media_root / "navidrome.yaml").read_text()
            if '"home_dir":"/srv/sftpgo/data/media/library"' not in sftpgo:
                raise SystemExit("SFTPGo must write directly to the Navidrome library")
            if "subPath: library" not in navidrome or "mountPath: /music" not in navidrome:
                raise SystemExit("Navidrome must read the shared SFTPGo library")

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
