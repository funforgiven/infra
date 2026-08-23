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

            mkdir -p \
              source/components/nix/servers \
              source/deployments/homelab \
              source/secrets
            cp -R ${inputs.self}/components/cloud source/components/cloud
            cp ${inputs.self}/components/nix/servers/image-promotion.nix \
              source/components/nix/servers/image-promotion.nix
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
              deployments/homelab/cloud/undercloud/84-mail-aws \
              >/dev/null
            kustomize build \
              deployments/homelab/cloud/undercloud/85-service-dns \
              >/dev/null
            python - <<'PY'
            import json
            import pathlib
            import re

            import yaml

            root = pathlib.Path("deployments/homelab/cloud")
            contract_document = yaml.safe_load(
                (root / "undercloud/82-services-cluster/runtime-contract.yaml").read_text()
            )
            contract = yaml.safe_load(contract_document["data"]["required-keys.yaml"])
            if contract["schemaVersion"] != 8:
                raise SystemExit("services runtime contract must use schema version 8")
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
                "aws-mail-auth": (
                    "enroll-aws-mail-auth",
                    {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"},
                ),
                "resend-mail-edge": (
                    "reconcile-services-resend",
                    {"STALWART_RESEND_API_KEY"},
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
            if "SFTPGO_USER_PASSWORD" in reconcile_script:
                raise SystemExit("SFTPGo local user password must remain retired")
            for oidc_output in ("sftpgo_client_id", "sftpgo_client_secret"):
                if oidc_output not in reconcile_script:
                    raise SystemExit("SFTPGo OIDC output is not reconciled")

            mail_tofu = yaml.safe_load(
                (root / "undercloud/84-mail-edge/tofu.yaml").read_text()
            )
            if mail_tofu["spec"].get("varsFrom") != [
                {
                    "kind": "Secret",
                    "name": "mail-edge-tofu-inputs",
                    "varsKeys": ["management_cidrs_json"],
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
                "--from-file=management_cidrs_json="
                "/runtime-bootstrap/MAIL_MANAGEMENT_CIDRS_JSON"
                not in reconcile_script
            ):
                raise SystemExit("mail-edge Terraform input is not reconciled in memory")

            aws_mail_root = pathlib.Path("components/cloud/services/mail-aws")
            aws_mail_tofu = yaml.safe_load(
                (root / "undercloud/84-mail-aws/tofu.yaml").read_text()
            )
            aws_mail_suspended = aws_mail_tofu["spec"].get("suspend")
            if not isinstance(aws_mail_suspended, bool):
                raise SystemExit("AWS mail must retain an explicit suspension gate")
            aws_source_revision = next(
                item["value"]
                for item in aws_mail_tofu["spec"]["vars"]
                if item["name"] == "source_revision"
            )
            if not re.fullmatch(r"[0-9a-f]{40}", aws_source_revision):
                raise SystemExit("AWS mail source revision must be an exact commit")
            aws_nixos_ami_id = next(
                item["value"]
                for item in aws_mail_tofu["spec"]["vars"]
                if item["name"] == "nixos_ami_id"
            )
            if not re.fullmatch(r"ami-[0-9a-f]{17}", aws_nixos_ami_id):
                raise SystemExit("AWS mail NixOS AMI must be pinned exactly")
            aws_restore_qualification = next(
                item["value"]
                for item in aws_mail_tofu["spec"]["vars"]
                if item["name"] == "enable_restore_qualification"
            )
            if aws_restore_qualification not in {"true", "false"}:
                raise SystemExit("AWS restore qualification gate must be explicit")
            if aws_mail_tofu["spec"]["runnerPodTemplate"]["spec"].get("envFrom") != [
                {"secretRef": {"name": "aws-mail-provisioning"}}
            ]:
                raise SystemExit("AWS mail provider auth bypasses its SOPS boundary")
            aws_tofu_text = "\n".join(
                path.read_text()
                for path in sorted((aws_mail_root / "tofu").glob("*"))
                if path.is_file()
            )
            required_aws_contract = (
                'region = "eu-central-1"',
                'instance_type        = "t4g.micro"',
                'values = [var.nixos_ami_id]',
                'instance_class = "db.t4g.micro"',
                'engine_version = "17.10"',
                "manage_master_user_password = true",
                'data "aws_kms_key" "rds_storage"',
                'key_id = "alias/aws/rds"',
                "kms_key_id = data.aws_kms_key.rds_storage.arn",
                "backup_retention_period = 14",
                "deletion_protection         = true",
                'versioning_configuration {\n    status = "Enabled"',
                'sse_algorithm = "AES256"',
                "prevent_destroy = true",
                'http_tokens                 = "required"',
                'policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"',
                'identifier = "stalwart-mail-restore-qualification"',
                "backup_retention_period    = 0",
                "deletion_protection        = false",
                "skip_final_snapshot        = true",
                'Ephemeral = "true"',
            )
            if any(fragment not in aws_tofu_text for fragment in required_aws_contract):
                raise SystemExit("AWS mail durability or least-cost contract drifted")
            forbidden_aws_state = (
                "aws_secretsmanager_secret_version",
                "private_key",
                "key_name",
            )
            if any(
                fragment in aws_tofu_text for fragment in forbidden_aws_state
            ) or re.search(r"^\s*password\s*=", aws_tofu_text, re.M):
                raise SystemExit("AWS mail would put credentials or SSH state in OpenTofu")
            if "most_recent = true" in aws_tofu_text:
                raise SystemExit("AWS mail appliance AMI must not drift during reconciliation")
            if "master_user_secret_kms_key_id" in aws_tofu_text:
                raise SystemExit("AWS mail bypasses the managed Secrets Manager key default")
            if "from_port   = 22" in aws_tofu_text:
                raise SystemExit("AWS mail exposes SSH instead of Session Manager")
            if 'var.source_revision != "0000000000000000000000000000000000000000"' not in (
                aws_mail_root / "tofu/variables.tf"
            ).read_text():
                raise SystemExit("AWS appliance must reject the source sentinel")
            aws_user_data = (
                aws_mail_root / "tofu/user-data.sh.tftpl"
            ).read_text()
            required_bootstrap_swap = (
                "swap_file=/swapfile",
                "swap_size_bytes=2147483648",
                'dd if=/dev/zero of="$swap_file" bs=1M count=2048 status=none',
                'mkswap "$swap_file"',
                'swapon "$swap_file"',
            )
            if any(
                fragment not in aws_user_data
                for fragment in required_bootstrap_swap
            ):
                raise SystemExit("AWS mail first boot lacks its low-memory swap boundary")
            iam_policy_text = (
                aws_mail_root / "bootstrap-iam-policy.json"
            ).read_text()
            if iam_policy_text.count("ACCOUNT_ID") != 9:
                raise SystemExit("AWS bootstrap policy account scoping drifted")
            iam_policy = json.loads(iam_policy_text.replace("ACCOUNT_ID", "123456789012"))
            policy_statements = {
                statement["Sid"]: statement
                for statement in iam_policy["Statement"]
            }
            if policy_statements["ManageFrankfurtMailServices"]["Condition"] != {
                "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
            }:
                raise SystemExit("AWS GitOps mutation policy is not Frankfurt-scoped")
            if policy_statements["DescribeAwsManagedMailKeys"] != {
                "Sid": "DescribeAwsManagedMailKeys",
                "Effect": "Allow",
                "Action": "kms:DescribeKey",
                "Resource": "arn:aws:kms:eu-central-1:123456789012:key/*",
                "Condition": {
                    "ForAnyValue:StringEquals": {
                        "kms:ResourceAliases": [
                            "alias/aws/rds",
                            "alias/aws/secretsmanager",
                        ]
                    }
                },
            }:
                raise SystemExit("AWS GitOps KMS inspection escaped managed mail keys")
            if any(
                action in iam_policy_text
                for action in (
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:UpdateSecret",
                )
            ):
                raise SystemExit("AWS GitOps identity has broad secret-value access")
            if policy_statements["ManageMailSecretContainers"]["Resource"] != (
                "arn:aws:secretsmanager:eu-central-1:123456789012:"
                "secret:fahrican/stalwart/*"
            ):
                raise SystemExit("AWS GitOps secret management escaped Stalwart")
            if set(policy_statements["ManageMailSecretContainers"]["Action"]) != {
                "secretsmanager:CreateSecret",
                "secretsmanager:DeleteSecret",
                "secretsmanager:DescribeSecret",
                "secretsmanager:GetResourcePolicy",
                "secretsmanager:PutResourcePolicy",
                "secretsmanager:RestoreSecret",
                "secretsmanager:TagResource",
                "secretsmanager:UntagResource",
            }:
                raise SystemExit("AWS GitOps secret container actions drifted")
            if policy_statements["CreateRdsManagedCredentials"] != {
                "Sid": "CreateRdsManagedCredentials",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:CreateSecret",
                    "secretsmanager:TagResource",
                ],
                "Resource": (
                    "arn:aws:secretsmanager:eu-central-1:123456789012:"
                    "secret:rds!db-*"
                ),
                "Condition": {
                    "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
                },
            }:
                raise SystemExit("AWS RDS credential creation escaped its boundary")
            if policy_statements["PublishResendRuntimeCredential"] != {
                "Sid": "PublishResendRuntimeCredential",
                "Effect": "Allow",
                "Action": "secretsmanager:PutSecretValue",
                "Resource": (
                    "arn:aws:secretsmanager:eu-central-1:123456789012:"
                    "secret:fahrican/stalwart/resend-*"
                ),
                "Condition": {
                    "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
                },
            }:
                raise SystemExit("AWS Resend publication is not independently scoped")
            if policy_statements["RunCommandsOnMailInstance"]["Condition"] != {
                "StringEquals": {
                    "aws:RequestedRegion": "eu-central-1",
                    "aws:ResourceTag/Service": "stalwart-mail",
                }
            }:
                raise SystemExit("AWS SSM commands escaped the tagged mail instance")
            if policy_statements["UseMailRunCommandDocument"]["Resource"] != (
                "arn:aws:ssm:eu-central-1::document/AWS-RunShellScript"
            ):
                raise SystemExit("AWS SSM command document is not constrained")
            if set(policy_statements) != {
                "ReadProvisionedState",
                "ManageFrankfurtMailServices",
                "ManageMailSecretContainers",
                "CreateRdsManagedCredentials",
                "PublishResendRuntimeCredential",
                "InspectMailManagedNode",
                "UseMailRunCommandDocument",
                "RunCommandsOnMailInstance",
                "ManageMailBucket",
                "DescribeAwsManagedMailKeys",
                "ManageMailRuntimeRole",
                "CreateRdsServiceRole",
            }:
                raise SystemExit("AWS GitOps IAM policy shape drifted")

            aws_sops = yaml.safe_load(
                (root / "undercloud/84-mail-aws/aws.sops.yaml").read_text()
            )
            aws_auth_keys = set(aws_sops.get("data", {}))
            expected_aws_auth_keys = {
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
            }
            if aws_auth_keys not in (
                set(),
                expected_aws_auth_keys,
            ):
                raise SystemExit("AWS provisioning SOPS document has unexpected keys")
            if not aws_mail_suspended and aws_auth_keys != expected_aws_auth_keys:
                raise SystemExit(
                    "AWS mail activation requires complete encrypted provider auth"
                )
            if any(
                not str(value).startswith("ENC[")
                for value in aws_sops.get("data", {}).values()
            ):
                raise SystemExit("AWS provisioning document contains plaintext")
            aws_recipients = {
                entry["recipient"] for entry in aws_sops["sops"]["age"]
            }
            if aws_recipients != {
                "age14xx2n9unst4zc02lt26fxez8hg9ke44hrwefm3c9w79fap29mpuqu26eea",
                "age19ep2ztjlquplkgts8kstufgcx9add4enwn2dzsy6s7euy2scvvksgwevv2",
            }:
                raise SystemExit("AWS provider auth must be admin/undercloud scoped")
            foundation = yaml.safe_load(
                (
                    root
                    / "undercloud/81-services-foundation/kustomization.yaml"
                ).read_text()
            )
            if "mail-edge-tofu-input.yaml" not in foundation["resources"]:
                raise SystemExit("mail-edge Terraform input target is not predeclared")
            if "share-quota.yaml" not in foundation["resources"]:
                raise SystemExit("Manila quota reconciliation is not predeclared")
            share_quota = yaml.safe_load(
                (
                    root / "undercloud/81-services-foundation/share-quota.yaml"
                ).read_text()
            )
            share_pod = share_quota["spec"]["jobTemplate"]["spec"]["template"]["spec"]
            share_container = share_pod["containers"][0]
            if share_pod.get("automountServiceAccountToken") is not False:
                raise SystemExit("Manila quota reconciler mounts a Kubernetes token")
            if share_container.get("envFrom") != [
                {"secretRef": {"name": "magnum-keystone-admin"}}
            ]:
                raise SystemExit("Manila quota reconciler uses the wrong credential boundary")
            if share_container["image"] != (
                "quay.io/airshipit/openstack-client:2026.1-ubuntu_noble@sha256:"
                "f38785f22b3b2c42ed28beacd927e194f4e14c2a721debe8d43e4752b7270676"
            ):
                raise SystemExit("Manila quota reconciler image is not pinned")
            quota_script = share_container["command"][2]
            for quota_fragment in (
                "gigabytes=2048",
                "openstack share quota set",
                '--per-share-gigabytes "$gigabytes"',
                'test "$(openstack share quota show',
            ):
                if quota_fragment not in quota_script:
                    raise SystemExit(
                        f"Manila quota reconciliation lacks {quota_fragment!r}"
                    )
            interface_placeholders = (
                "mail-edge-tofu-input.yaml",
                "resend-domain-output.yaml",
                "service-dns-input.yaml",
            )
            for placeholder_name in interface_placeholders:
                placeholder = yaml.safe_load(
                    (
                        root
                        / "undercloud/81-services-foundation"
                        / placeholder_name
                    ).read_text()
                )
                if placeholder["metadata"].get("annotations") != {
                    "kustomize.toolkit.fluxcd.io/ssa": "IfNotPresent"
                }:
                    raise SystemExit(
                        f"{placeholder_name} does not preserve controller-owned data"
                    )
                if "data" in placeholder or "stringData" in placeholder:
                    raise SystemExit(
                        f"{placeholder_name} declares generated runtime data"
                    )
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
                "region": backup_destination["bucket"]["region"],
                "prefix": "services/kubernetes",
            }:
                raise SystemExit("services backup destination diverges from Backblaze B2")
            if "'        checksumAlgorithm: \"\"'" not in reconcile_script:
                raise SystemExit("Velero must disable unsupported Backblaze request checksums")
            velero_documents = yaml.safe_load_all(
                (root / "services/15-backup-controller/velero.yaml").read_text()
            )
            velero_release = next(
                document
                for document in velero_documents
                if document.get("kind") == "HelmRelease"
            )
            aws_plugin = next(
                container
                for container in velero_release["spec"]["values"]["initContainers"]
                if container["name"] == "velero-plugin-for-aws"
            )
            if aws_plugin["image"] != (
                "docker.io/velero/velero-plugin-for-aws:main@sha256:"
                "0f442cf9263b3a579d9b22417501dfef75e83b300b8180b9394c86d0127ec220"
            ):
                raise SystemExit("Velero must pin the upstream Backblaze header fix")
            velero_alerts = {
                rule["alert"]: rule
                for rule in velero_release["spec"]["values"]["metrics"][
                    "prometheusRule"
                ]["spec"]
            }
            recent_backup_expression = velero_alerts["VeleroNoRecentBackup"]["expr"]
            if "bool" in recent_backup_expression:
                raise SystemExit(
                    "Velero age alert must drop false comparison series"
                )
            restore_documents = list(
                yaml.safe_load_all(
                    (
                        root
                        / "services/16-backup-policy/restore-qualification.yaml"
                    ).read_text()
                )
            )
            restore_modifiers = next(
                document
                for document in restore_documents
                if document.get("kind") == "ConfigMap"
                and document["metadata"]["name"]
                == "restore-qualification-modifiers"
            )
            modifier_policy = yaml.safe_load(
                restore_modifiers["data"]["resource-modifiers.yaml"]
            )
            if modifier_policy["resourceModifierRules"] != [
                {
                    "conditions": {
                        "groupResource": "persistentvolumeclaims",
                        "namespaces": ["backup-qualification"],
                    },
                    "patches": [
                        {
                            "operation": "remove",
                            "path": "/spec/volumeName",
                        }
                    ],
                }
            ]:
                raise SystemExit("restore qualification must clear source PVC bindings")
            restore_config = next(
                document
                for document in restore_documents
                if document.get("kind") == "ConfigMap"
                and document["metadata"]["name"] == "restore-qualification"
            )
            restore_template = yaml.safe_load(restore_config["data"]["restore.yaml"])
            if restore_template["spec"].get("resourceModifier") != {
                "kind": "ConfigMap",
                "name": "restore-qualification-modifiers",
            }:
                raise SystemExit("restore qualification does not reference its PVC modifier")
            controller_documents = yaml.safe_load_all(
                (
                    root
                    / "services/10-platform-controllers/cert-manager.yaml"
                ).read_text()
            )
            cert_manager_release = next(
                document
                for document in controller_documents
                if document.get("kind") == "HelmRelease"
            )
            if cert_manager_release["spec"]["values"].get("extraArgs") != [
                "--dns01-recursive-nameservers-only",
                "--dns01-recursive-nameservers=172.24.0.10:53",
            ]:
                raise SystemExit(
                    "cert-manager DNS-01 checks must use the private cluster resolver"
                )
            required_b2_capabilities = {
                "deleteFiles",
                "listAllBucketNames",
                "listBuckets",
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
            expected_restic_passwords = {
                "hermes": "HERMES_BACKUP_RESTIC_PASSWORD",
                "home-assistant": "HOME_ASSISTANT_BACKUP_RESTIC_PASSWORD",
                "mail-edge": "MAIL_EDGE_BACKUP_RESTIC_PASSWORD",
            }
            if {
                host["host"]: host["resticPasswordField"]
                for host in b2_services["hosts"]
            } != expected_restic_passwords:
                raise SystemExit("host Restic password routes are invalid")
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
            if "aws-mail-bootstrap-credential-issuance" not in exception_ids:
                raise SystemExit("AWS mail bootstrap ceremony is undocumented")
            if "smtp-inbound-monitoring-vantage" not in exception_ids:
                raise SystemExit("SMTP external-monitoring limitation is undocumented")
            if "hetzner-smtp-port-unblock" in exception_ids:
                raise SystemExit("completed Hetzner SMTP unblock remains open")
            synthetic_alerts = yaml.safe_load(
                (root / "services/50-synthetic-monitoring/alerts.yaml").read_text()
            )
            endpoint_alert = next(
                rule
                for group in synthetic_alerts["spec"]["groups"]
                for rule in group["rules"]
                if rule["alert"] == "ServicesEndpointDown"
            )
            endpoint_expression = endpoint_alert["expr"]
            if (
                'job="services-http"' not in endpoint_expression
                or 'job="mail-tcp"' not in endpoint_expression
                or 'instance!="mail.fahrican.com:25"' not in endpoint_expression
            ):
                raise SystemExit(
                    "synthetic paging must exclude only the inconclusive SMTP-25 vantage"
                )
            synthetic_probes = (
                root / "services/50-synthetic-monitoring/probes.yaml"
            ).read_text()
            if "mail.fahrican.com:25" not in synthetic_probes:
                raise SystemExit("SMTP-25 diagnostic probe series was removed")
            if {
                "openai-admin-key-bootstrap",
                "openai-organization-hosted-tool-policy",
            } & exception_ids:
                raise SystemExit("obsolete OpenAI administration exception remains")

            mail_directory = yaml.safe_load(
                pathlib.Path(
                    "components/cloud/services/mail-edge/directory-inventory.yaml"
                ).read_text()
            )
            if mail_directory.get("version") != 1:
                raise SystemExit("Stalwart directory inventory version is invalid")
            if mail_directory.get("domains") != [{"name": "fahrican.com"}]:
                raise SystemExit("Stalwart directory must retain the declared mail domain")
            if mail_directory.get("accounts") != [
                {
                    "address": "fahrican@fahrican.com",
                    "displayName": "Fahrican",
                }
            ]:
                raise SystemExit("Stalwart initial mailbox inventory drifted")
            if mail_directory.get("aliases") or mail_directory.get(
                "applicationPasswords"
            ):
                raise SystemExit("Stalwart contains undeclared directory objects")
            if set(mail_directory) != {
                "version",
                "domains",
                "accounts",
                "aliases",
                "applicationPasswords",
            }:
                raise SystemExit("Stalwart directory inventory schema drifted")
            if not all(
                isinstance(mail_directory[field], list)
                for field in ("accounts", "aliases", "applicationPasswords")
            ):
                raise SystemExit("Stalwart directory objects must be explicit lists")
            if any(
                forbidden in entry
                for field in ("accounts", "aliases", "applicationPasswords")
                for entry in mail_directory[field]
                if isinstance(entry, dict)
                for forbidden in ("password", "secret", "token", "credential")
            ):
                raise SystemExit("Stalwart directory inventory contains secret material")

            repository_text = "\n".join(
                path.read_text(errors="ignore")
                for path in pathlib.Path(".").rglob("*")
                if path.is_file() and ".terraform" not in path.parts
            )
            openai_intake_name = "OPENAI_API_KEY" + ".key"
            if openai_intake_name not in repository_text:
                raise SystemExit("Hermes OpenAI intake contract is undocumented")
            for aws_intake_name in (
                "AWS_BOOTSTRAP_ACCESS_KEY_ID" + ".key",
                "AWS_BOOTSTRAP_SECRET_ACCESS_KEY" + ".key",
            ):
                if aws_intake_name not in repository_text:
                    raise SystemExit("AWS bootstrap intake contract is undocumented")
            obsolete_openai_control_plane = (
                "OPENAI_" + "ADMIN_KEY",
                "reconcile-services-" + "openai",
                "79-" + "openai-control-plane",
                "openai/" + "openai",
            )
            if any(value in repository_text for value in obsolete_openai_control_plane):
                raise SystemExit("obsolete OpenAI administration machinery remains")
            retired_knowledge_stack = (
                "kara" + "keep",
                "meili" + "search",
                "sear" + "xng",
                "keep." + "fahrican.com",
                "search." + "fahrican.com",
                "HERMES_KARA" + "KEEP_API_KEY",
            )
            if any(
                value.lower() in repository_text.lower()
                for value in retired_knowledge_stack
            ):
                raise SystemExit("retired knowledge or search machinery remains")

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
            sftpgo_bootstrap = (media_root / "render-initial-data.sh").read_text()
            media_kustomization = (media_root / "kustomization.yaml").read_text()
            navidrome = (media_root / "navidrome.yaml").read_text()
            manila_csi_policy = yaml.safe_load(
                (
                    root
                    / "services/10-platform-controllers/manila-csi-policy.yaml"
                ).read_text()
            )
            if manila_csi_policy != {
                "apiVersion": "storage.k8s.io/v1",
                "kind": "CSIDriver",
                "metadata": {"name": "nfs.manila.csi.openstack.org"},
                "spec": {
                    "attachRequired": False,
                    "fsGroupPolicy": "File",
                    "podInfoOnMount": False,
                    "requiresRepublish": False,
                    "seLinuxMount": False,
                    "storageCapacity": False,
                    "volumeLifecycleModes": ["Persistent"],
                },
            }:
                raise SystemExit(
                    "Manila NFS must honor the non-root media filesystem group"
                )
            magnum_driver_values = (
                root / "undercloud/71-magnum/driver-values.yaml"
            ).read_text()
            if '"values": {"fsGroupPolicy": "File"}' not in magnum_driver_values:
                raise SystemExit(
                    "future Magnum clusters must retain the Manila filesystem-group policy"
                )
            if '"home_dir":"/srv/sftpgo/data/media/library"' not in sftpgo_bootstrap:
                raise SystemExit("SFTPGo must write directly to the Navidrome library")
            required_sftpgo_oidc = (
                '"username":"fahricanelidemir@gmail.com"',
                'SFTPGO_HTTPD__BINDINGS__0__OIDC__CLIENT_SECRET_FILE',
                'SFTPGO_HTTPD__BINDINGS__0__OIDC__USERNAME_FIELD',
                'SFTPGO_HTTPD__BINDINGS__0__DISABLED_LOGIN_METHODS',
                'value: "168"',
                'value: https://auth.cloud.fahrican.com',
                'value: https://upload.fahrican.com',
                '"password-change-disabled"',
                '"password-reset-disabled"',
                '"api-key-auth-change-disabled"',
                '"publickey-change-disabled"',
                '"tls-cert-change-disabled"',
            )
            if any(
                fragment not in sftpgo + sftpgo_bootstrap
                for fragment in required_sftpgo_oidc
            ):
                raise SystemExit("SFTPGo native ZITADEL OIDC contract drifted")
            if "SFTPGO_USER_PASSWORD" in sftpgo + sftpgo_bootstrap:
                raise SystemExit("SFTPGo upload identity must not have a local password")
            if '"denied_login_methods"' in sftpgo_bootstrap:
                raise SystemExit(
                    "SFTPGo OIDC identity must not deny every valid login method"
                )

            identity_tofu = pathlib.Path(
                "components/cloud/identity/tofu/main.tf"
            ).read_text()
            for identity_fragment in (
                'redirect_uri = "https://upload.fahrican.com/web/oidc/redirect"',
                'output "sftpgo_client_id"',
                'output "sftpgo_client_secret"',
            ):
                if identity_fragment not in identity_tofu:
                    raise SystemExit("SFTPGo ZITADEL application contract drifted")

            haos_promotion = pathlib.Path(
                "components/nix/servers/image-promotion.nix"
            ).read_text()
            haos_hosts = pathlib.Path(
                "components/cloud/services/hosts/tofu/main.tf"
            ).read_text()
            haos_activation = yaml.safe_load(
                (root / "undercloud/83-services-hosts/tofu.yaml").read_text()
            )
            haos_platform = next(
                item["value"]
                for item in haos_activation["spec"]["vars"]
                if item["name"] == "home_assistant_platform"
            )
            if haos_platform != "nixos":
                raise SystemExit("HAOS must remain behind the restore-qualified cutover")
            for haos_fragment in (
                "haos_ova-$haos_version.qcow2.xz",
                "254e53f354df0739e3afc09be5431a07df53f0df6b703885404f665c454f254e",
                "--protected",
            ):
                if haos_fragment not in haos_promotion:
                    raise SystemExit("HAOS official-image promotion contract drifted")
            if (
                "83-services-hosts/tofu.yaml" in haos_promotion
                or "activation_manifest" in haos_promotion
            ):
                raise SystemExit(
                    "image promotion must not mutate an active boot-volume revision"
                )
            if (
                'default     = "nixos"' not in haos_hosts
                or 'name        = "home-assistant-root-haos-18.2"' not in haos_hosts
                or haos_hosts.count("prevent_destroy = true") < 3
            ):
                raise SystemExit("HAOS cutover or retained-volume protection drifted")
            if (
                "IFS= read" in sftpgo_bootstrap
                or 'admin_password="$(cat ' not in sftpgo_bootstrap
            ):
                raise SystemExit(
                    "SFTPGo must accept generated Secret files without trailing newlines"
                )
            if (
                "configMapGenerator:" not in media_kustomization
                or "render.sh=render-initial-data.sh" not in media_kustomization
            ):
                raise SystemExit(
                    "SFTPGo bootstrap changes must trigger a content-hashed rollout"
                )
            if "subPath: library" not in navidrome or "mountPath: /music" not in navidrome:
                raise SystemExit("Navidrome must read the shared SFTPGo library")

            media_restore_modifiers = yaml.safe_load(
                (
                    root
                    / "services/16-backup-policy/media-restore-modifiers.yaml"
                ).read_text()
            )
            modifier_rules = yaml.safe_load(
                media_restore_modifiers["data"]["resource-modifiers.yaml"]
            )
            if modifier_rules != {
                "version": "v1",
                "resourceModifierRules": [
                    {
                        "conditions": {
                            "groupResource": "persistentvolumeclaims",
                            "namespaces": ["media"],
                        },
                        "patches": [
                            {
                                "operation": "remove",
                                "path": "/spec/volumeName",
                            }
                        ],
                    }
                ],
            }:
                raise SystemExit(
                    "isolated media restores must dynamically provision every PVC"
                )

            observability = (root / "services/12-observability/kube-prometheus-stack.yaml").read_text()
            velero = (root / "services/15-backup-controller/velero.yaml").read_text()
            for name, text in (("observability", observability), ("velero", velero)):
                if "suspend: true" in text:
                    raise SystemExit(f"{name} retains an inner suspension")
            observability_release = next(
                document
                for document in yaml.safe_load_all(observability)
                if document.get("kind") == "HelmRelease"
            )
            retry_policy = {
                "name": "RetryOnFailure",
                "retryInterval": "1m",
            }
            for action in ("install", "upgrade"):
                action_policy = observability_release["spec"][action]
                if (
                    action_policy.get("strategy") != retry_policy
                    or "remediation" in action_policy
                ):
                    raise SystemExit(
                        f"observability {action} must self-retry its admission webhook bootstrap"
                    )
            admission_policy = observability_release["spec"]["values"][
                "prometheusOperator"
            ]["admissionWebhooks"]
            if not admission_policy["certManager"]["enabled"] or admission_policy[
                "patch"
            ]["enabled"]:
                raise SystemExit(
                    "observability admission TLS must use cert-manager instead of patch jobs"
                )
            prometheus_spec = observability_release["spec"]["values"]["prometheus"][
                "prometheusSpec"
            ]
            if prometheus_spec.get("serviceDiscoveryRole") != "EndpointSlice":
                raise SystemExit(
                    "Prometheus must discover services through EndpointSlice"
                )
            operator_values = observability_release["spec"]["values"][
                "prometheusOperator"
            ]
            if (
                operator_values.get("kubeletEndpointsEnabled") is not False
                or operator_values.get("kubeletEndpointSliceEnabled") is not True
            ):
                raise SystemExit(
                    "Prometheus Operator must publish only kubelet EndpointSlices"
                )
            for resource in ("podMonitor", "probe", "rule", "serviceMonitor"):
                if (
                    prometheus_spec.get(f"{resource}SelectorNilUsesHelmValues")
                    is not False
                    or prometheus_spec.get(f"{resource}Selector") != {}
                    or prometheus_spec.get(f"{resource}NamespaceSelector") != {}
                ):
                    raise SystemExit(
                        f"Prometheus must discover every declared {resource} across namespaces"
                    )
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
