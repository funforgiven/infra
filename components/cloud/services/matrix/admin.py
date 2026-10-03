#!/usr/bin/env python3
"""Prepare, enroll, and publish the closed Matrix deployment without printing secrets."""

import argparse
import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

import yaml

DEPLOYMENT = Path("deployments/homelab/cloud/services/47-matrix")
PROVIDER_ID = "01HFVBY12TMNTYTBV8W921M5FA"


class LiteralDumper(yaml.SafeDumper):
    pass


def literal_string(dumper, value):
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    )


LiteralDumper.add_representer(str, literal_string)


def run(argv, data=None):
    return subprocess.run(argv, input=data, capture_output=True, check=True).stdout


def load_secret(path):
    return yaml.safe_load(run(["sops", "decrypt", str(path)]))


def update_runtime_rollout(name, ciphertext):
    kinds = {"matrix-relay": "StatefulSet", "matrix-mas": "Deployment"}
    patch_path = DEPLOYMENT / "runtime-rollouts.yaml"
    patches = (
        list(yaml.safe_load_all(patch_path.read_text())) if patch_path.exists() else []
    )
    patch = next((item for item in patches if item["metadata"]["name"] == name), None)
    if patch is None:
        patch = {
            "apiVersion": "apps/v1",
            "kind": kinds[name],
            "metadata": {"name": name, "namespace": "matrix"},
            "spec": {"template": {"metadata": {"annotations": {}}}},
        }
        patches.append(patch)
    # This is a digest of the already-public ciphertext, never of a credential.
    patch["spec"]["template"]["metadata"]["annotations"][
        "matrix.fahrican.com/runtime-config"
    ] = hashlib.sha256(ciphertext).hexdigest()
    temporary = patch_path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump_all(patches, sort_keys=False))
    temporary.replace(patch_path)


def save_secret(path, document, *, rollout=None):
    if rollout not in (None, "matrix-relay", "matrix-mas"):
        raise ValueError("unsupported runtime workload")
    if rollout is not None and path != DEPLOYMENT / "runtime.sops.yaml":
        raise ValueError("runtime rollouts require the Matrix runtime Secret")
    ciphertext = run(
        [
            "sops",
            "encrypt",
            "--filename-override",
            str(path),
            "--input-type",
            "yaml",
            "--output-type",
            "yaml",
            "/dev/stdin",
        ],
        yaml.safe_dump(document, sort_keys=False).encode(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(ciphertext)
    temporary.replace(path)
    if rollout is not None:
        update_runtime_rollout(rollout, ciphertext)


def secret(name, namespace, values):
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"velero.io/exclude-from-backup": "true"},
        },
        "type": "Opaque",
        "stringData": values,
    }


def initialize():
    target = DEPLOYMENT / "runtime.sops.yaml"
    if target.exists():
        return
    # Capture generated MAS keys; plaintext never leaves this process's memory.
    mas = yaml.safe_load(run(["mas-cli", "config", "generate"]))
    shared = secrets.token_hex(32)
    passwords = {
        name: secrets.token_hex(32)
        for name in ("postgres-password", "synapse-password", "mas-password")
    }
    mas["http"] = {
        "public_base": "https://matrix-auth.fahrican.com/",
        "issuer": "https://matrix-auth.fahrican.com/",
        "listeners": [
            {
                "name": "web",
                "resources": [
                    {"name": name}
                    for name in (
                        "discovery",
                        "human",
                        "oauth",
                        "compat",
                        "graphql",
                        "assets",
                    )
                ],
                "binds": [{"host": "0.0.0.0", "port": 8080}],
            },
            {
                "name": "internal",
                "resources": [{"name": "health"}],
                "binds": [{"host": "0.0.0.0", "port": 8081}],
            },
        ],
    }
    mas["database"] = {
        "host": "matrix-postgres",
        "port": 5432,
        "username": "mas",
        "password": passwords["mas-password"],
        "database": "mas",
        "ssl_mode": "disable",
    }
    mas["matrix"] = {
        "kind": "synapse",
        "homeserver": "matrix.fahrican.com",
        "endpoint": "http://matrix-synapse:8008",
        "secret": shared,
    }
    mas["passwords"]["enabled"] = False
    mas.setdefault("account", {})["password_registration_enabled"] = False
    mas["upstream_oauth2"] = {"providers": []}
    synapse = {
        "server_name": "matrix.fahrican.com",
        "public_baseurl": "https://matrix.fahrican.com/",
        "report_stats": False,
        "pid_file": "/tmp/synapse.pid",
        "media_store_path": "/var/lib/matrix/media",
        "signing_key_path": "/run/matrix/signing.key",
        "max_upload_size": "25M",
        "listeners": [
            {
                "port": 8008,
                "bind_addresses": ["0.0.0.0"],
                "type": "http",
                "tls": False,
                "x_forwarded": True,
                "resources": [{"names": ["client"], "compress": False}],
            },
            {
                "port": 9000,
                "type": "http",
                "bind_addresses": ["0.0.0.0"],
                "resources": [{"names": ["metrics"], "compress": False}],
            },
        ],
        "enable_metrics": True,
        "federation_domain_whitelist": [],
        "trusted_key_servers": [],
        "allow_profile_lookup_over_federation": False,
        "url_preview_enabled": False,
        "enable_registration": False,
        "allow_guest_access": False,
        "enable_room_list_search": False,
        "push": {"include_content": False},
        "rc_login": {
            "address": {"per_second": 0.2, "burst_count": 5},
            "account": {"per_second": 0.2, "burst_count": 5},
        },
        "matrix_authentication_service": {
            "enabled": True,
            "endpoint": "http://matrix-mas:8080/",
            "secret": shared,
        },
        "http_proxy": "http://matrix-egress:3128",
        "https_proxy": "http://matrix-egress:3128",
        "no_proxy_hosts": ["matrix-mas"],
        "database": {
            "name": "psycopg2",
            "args": {
                "host": "matrix-postgres",
                "user": "synapse",
                "password": passwords["synapse-password"],
                "database": "synapse",
                "cp_min": 5,
                "cp_max": 10,
            },
        },
    }
    relay = {
        "homeserver": "http://matrix-client:8080",
        "user_id": "@infra-alerts:matrix.fahrican.com",
        "device_id": "INFRA_ALERTS",
        "access_token": "",
        "room_id": "",
        "canary_room_id": "",
        "allowed_users": [],
        "trusted_devices": {},
        "producers": {
            "alertmanager": {
                "paths": ["/alertmanager"],
                "token": secrets.token_urlsafe(32),
            }
        },
    }
    values = dict(
        passwords,
        **{
            "synapse.yaml": yaml.safe_dump(synapse),
            "mas.yaml": yaml.safe_dump(mas),
            "signing.key": "ed25519 matrix1 "
            + base64.b64encode(secrets.token_bytes(32)).decode().rstrip("=")
            + "\n",
            "relay.json": json.dumps(relay),
            "alertmanager-token": relay["producers"]["alertmanager"]["token"],
        },
    )
    save_secret(target, secret("matrix-runtime", "matrix", values))


def sync_identity(args):
    target = DEPLOYMENT / "runtime.sops.yaml"
    document = load_secret(target)
    outputs = json.loads(
        run(
            [
                "kubectl",
                "--kubeconfig",
                args.undercloud_kubeconfig,
                "-n",
                "tofu-system",
                "get",
                "secret",
                "zitadel-identity-outputs",
                "-o",
                "json",
            ]
        )
    )["data"]
    config = yaml.safe_load(document["stringData"]["mas.yaml"])
    config["upstream_oauth2"] = {
        "providers": [
            {
                "id": PROVIDER_ID,
                "issuer": "https://auth.cloud.fahrican.com",
                "human_name": "Fahrican",
                "client_id": base64.b64decode(outputs["matrix_client_id"]).decode(),
                "client_secret": base64.b64decode(
                    outputs["matrix_client_secret"]
                ).decode(),
                "token_endpoint_auth_method": "client_secret_basic",
                "scope": "openid email profile",
                "claims_imports": {
                    "localpart": {
                        "action": "suggest",
                        "template": "{{ user.preferred_username }}",
                    },
                    "displayname": {"action": "suggest", "template": "{{ user.name }}"},
                    "email": {"action": "suggest", "template": "{{ user.email }}"},
                },
            }
        ]
    }
    document["stringData"]["mas.yaml"] = yaml.safe_dump(config)
    save_secret(target, document, rollout="matrix-mas")


async def enroll_bot(args):
    from nio import AsyncClient, AsyncClientConfig, RoomCreateResponse, RoomPreset

    if not re.fullmatch(r"@[a-z0-9._=/-]+:matrix\.fahrican\.com", args.owner):
        raise ValueError("alert-room owner must be a local Matrix user")
    target = DEPLOYMENT / "runtime.sops.yaml"
    document = load_secret(target)
    config = json.loads(document["stringData"]["relay.json"])
    # Passwords are disabled. Provision the service user and a non-admin compatibility
    # session through MAS's CLI; capture its output, including token, in memory.
    kubectl = [
        "kubectl",
        "--kubeconfig",
        args.services_kubeconfig,
        "-n",
        "matrix",
        "exec",
        "deploy/matrix-mas",
        "--",
        "mas-cli",
    ]
    if not config["access_token"]:
        # CLI may report that the account already exists after an interrupted enrollment.
        result = subprocess.run(
            kubectl
            + [
                "manage",
                "register-user",
                "--yes",
                "--no-admin",
                "infra-alerts",
                "--config",
                "/run/matrix/mas.yaml",
            ],
            capture_output=True,
        )
        if result.returncode and b"already exists" not in result.stderr + result.stdout:
            raise RuntimeError("service-account enrollment failed")
        for attempt in range(30):
            issued = subprocess.run(
                kubectl
                + [
                    "manage",
                    "issue-compatibility-token",
                    "infra-alerts",
                    config["device_id"],
                    "--config",
                    "/run/matrix/mas.yaml",
                ],
                capture_output=True,
            )
            if not issued.returncode:
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("compatibility session enrollment failed")
        token_output = (issued.stdout + issued.stderr).decode()
        token = re.search(r"mct_[A-Za-z0-9_-]+", token_output)
        if token is None:
            raise RuntimeError("could not parse compatibility token")
        config["access_token"] = token.group()
        # Persist the credential before any room creation, so retries retain identity.
        document["stringData"]["relay.json"] = json.dumps(config)
        save_secret(target, document, rollout="matrix-relay")
    client = AsyncClient(
        args.homeserver,
        config["user_id"],
        config=AsyncClientConfig(encryption_enabled=False),
    )
    client.restore_login(config["user_id"], config["device_id"], config["access_token"])
    try:
        for key, name, invite in (
            ("room_id", "Infra Alerts", [args.owner]),
            ("canary_room_id", "Infra Delivery Canary", []),
        ):
            if config[key]:
                continue
            response = await client.room_create(
                name=name,
                invite=invite,
                is_direct=False,
                preset=RoomPreset.private_chat,
                federate=False,
                initial_state=[
                    {
                        "type": "m.room.encryption",
                        "state_key": "",
                        "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                    }
                ],
            )
            if not isinstance(response, RoomCreateResponse):
                raise RuntimeError("encrypted room enrollment failed")
            config[key] = response.room_id
            config["allowed_users"] = [config["user_id"], args.owner]
            document["stringData"]["relay.json"] = json.dumps(config)
            save_secret(target, document, rollout="matrix-relay")
    finally:
        await client.close()


def approve_device(args):
    target = DEPLOYMENT / "runtime.sops.yaml"
    document = load_secret(target)
    relay = json.loads(document["stringData"]["relay.json"])
    if args.user not in relay["allowed_users"]:
        raise ValueError("device owner is not enrolled in the alert room")
    fingerprint = args.fingerprint.replace(" ", "")
    if not re.fullmatch(r"[A-Za-z0-9+/]{43}", fingerprint):
        raise ValueError("fingerprint must be the device's 43-character Ed25519 key")
    relay["trusted_devices"].setdefault(args.user, {})[args.device] = fingerprint
    document["stringData"]["relay.json"] = json.dumps(relay)
    save_secret(target, document, rollout="matrix-relay")


def configure_alerting(args):
    rollout_file = DEPLOYMENT / "rollout.json"
    rollout = json.loads(rollout_file.read_text())
    if args.phase == "matrix":
        started, qualified = rollout.get("dual_started_at"), rollout.get("qualified_at")
        if (
            not started
            or time.time() - started < 7 * 86400
            or not qualified
            or not 0 <= time.time() - qualified <= 86400
        ):
            raise ValueError(
                "cutover requires seven days of dual delivery and qualification within the last day"
            )
    target = DEPLOYMENT / "runtime.sops.yaml"
    document = load_secret(target)
    relay = json.loads(document["stringData"]["relay.json"])
    resend = load_secret(DEPLOYMENT / "email.sops.yaml")["data"]
    sending_key = base64.b64decode(resend["MATRIX_RESEND_API_KEY"]).decode()
    smtp = {
        "host": "smtp.resend.com",
        "port": 465,
        "username": "resend",
        "password": sending_key,
        "from": "alerts@fahrican.com",
        "to": "fahricanelidemir@gmail.com",
    }
    for host in args.host:
        if not re.fullmatch(r"[a-z0-9-]+", host):
            raise ValueError("invalid host producer")
        relay["producers"].setdefault(
            host, {"paths": ["/notify"], "token": secrets.token_urlsafe(32)}
        )
        host_config = {
            "url": "https://matrix-alerts.fahrican.com/notify",
            "producer_id": host,
            "token": relay["producers"][host]["token"],
            "smtp": smtp,
        }
        save_secret(
            Path("deployments/homelab/cloud/host-runtime")
            / ("matrix-" + host + ".sops.yaml"),
            secret(
                "matrix-" + host, "matrix", {"config.json": json.dumps(host_config)}
            ),
        )
    document["stringData"]["relay.json"] = json.dumps(relay)
    save_secret(target, document, rollout="matrix-relay")
    receiver = {
        "name": "infrastructure-matrix",
        "webhook_configs": [
            {
                "url": "http://matrix-relay.matrix.svc:8080/alertmanager",
                "send_resolved": True,
                "http_config": {
                    "authorization": {
                        "type": "Bearer",
                        "credentials_file": "/etc/alertmanager/secrets/matrix-alerting/alertmanager-token",
                    }
                },
            }
        ],
    }
    email_receiver = {
        "name": "independent-email",
        "email_configs": [{"to": smtp["to"], "send_resolved": True}],
    }
    routing = {
        "receiver": receiver["name"],
        "group_by": ["alertname", "namespace", "severity"],
        "group_wait": "30s",
        "group_interval": "5m",
        "repeat_interval": "6h",
        "routes": [
            {"receiver": "null", "matchers": ['alertname = "Watchdog"']},
            {"receiver": "null", "matchers": ['alertname = "InfoInhibitor"']},
            {
                "receiver": email_receiver["name"],
                "matchers": ['severity =~ "critical|error"'],
                "continue": True,
            },
            {"receiver": receiver["name"]},
        ],
    }
    receivers = [{"name": "null"}, receiver, email_receiver]
    if args.phase == "dual":
        telegram_doc = load_secret(
            Path(
                "deployments/homelab/cloud/undercloud/81-services-foundation/runtime.sops.yaml"
            )
        )["data"]
        chat_id = int(base64.b64decode(telegram_doc["INFRA_TELEGRAM_CHAT_ID"]).decode())
        receivers.append(
            {
                "name": "infrastructure-telegram",
                "telegram_configs": [
                    {
                        "bot_token_file": "/etc/alertmanager/secrets/infrastructure-telegram/bot-token",
                        "chat_id": chat_id,
                        "send_resolved": True,
                        "parse_mode": "HTML",
                    }
                ],
            }
        )
        routing["routes"].insert(
            2, {"receiver": "infrastructure-telegram", "continue": True}
        )
    config = {
        "global": {
            "resolve_timeout": "5m",
            "smtp_smarthost": "smtp.resend.com:587",
            "smtp_from": smtp["from"],
            "smtp_auth_username": "resend",
            "smtp_auth_password_file": "/etc/alertmanager/secrets/matrix-alerting/smtp-password",
            "smtp_require_tls": True,
        },
        "route": routing,
        "receivers": receivers,
    }
    # Added last to Helm valuesFrom. No change occurs until this Secret exists.
    save_secret(
        DEPLOYMENT / "alerting.sops.yaml",
        secret(
            "matrix-alertmanager-values",
            "services-observability",
            {
                "values.yaml": yaml.safe_dump(
                    {
                        "alertmanager": {
                            "config": config,
                            "alertmanagerSpec": {
                                "secrets": [
                                    "matrix-alerting",
                                    "infrastructure-telegram",
                                ]
                                if args.phase == "dual"
                                else ["matrix-alerting"]
                            },
                        }
                    }
                )
            },
        ),
    )
    save_secret(
        DEPLOYMENT / "alerting-credentials.sops.yaml",
        secret(
            "matrix-alerting",
            "services-observability",
            {
                "smtp-password": sending_key,
                "alertmanager-token": relay["producers"]["alertmanager"]["token"],
            },
        ),
    )
    kustomization = DEPLOYMENT / "kustomization.yaml"
    k = yaml.safe_load(kustomization.read_text())
    for resource in ("alerting.sops.yaml", "alerting-credentials.sops.yaml"):
        if resource not in k["resources"]:
            k["resources"].append(resource)
    kustomization.write_text(yaml.safe_dump(k, sort_keys=False))
    rollout["phase"] = args.phase
    if args.phase == "dual" and not rollout.get("dual_started_at"):
        rollout["dual_started_at"] = time.time()
    rollout_file.write_text(json.dumps(rollout, indent=2) + "\n")


def aws_client(service):
    import boto3

    source = load_secret(
        Path("deployments/homelab/cloud/undercloud/84-mail-aws/aws.sops.yaml")
    )["data"]
    return boto3.client(
        service,
        region_name="eu-central-1",
        aws_access_key_id=base64.b64decode(source["AWS_ACCESS_KEY_ID"]).decode(),
        aws_secret_access_key=base64.b64decode(
            source["AWS_SECRET_ACCESS_KEY"]
        ).decode(),
    )


def sync_monitoring_policy(args):
    import boto3
    from botocore.exceptions import ClientError
    from urllib.parse import unquote

    session = boto3.Session(profile_name=args.aws_profile)
    account = session.client("sts").get_caller_identity()["Account"]
    if account != aws_client("sts").get_caller_identity()["Account"]:
        raise ValueError("administrative session must use the enrolled AWS account")
    desired = json.loads(
        Path("components/cloud/services/mail-aws/matrix-iam-policy.json")
        .read_text()
        .replace("ACCOUNT_ID", account)
    )
    iam = session.client("iam")
    arn = f"arn:aws:iam::{account}:policy/fahrican-matrix-monitoring-gitops"
    try:
        version = iam.get_policy(PolicyArn=arn)["Policy"]["DefaultVersionId"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_policy(
            PolicyName="fahrican-matrix-monitoring-gitops",
            PolicyDocument=json.dumps(desired),
        )
        iam.attach_user_policy(UserName="fahrican-mail-gitops", PolicyArn=arn)
        print(
            "Enrolled the scoped Matrix monitoring policy; existing access keys retained."
        )
        return
    current = iam.get_policy_version(PolicyArn=arn, VersionId=version)["PolicyVersion"][
        "Document"
    ]
    if isinstance(current, str):
        current = json.loads(unquote(current))
    if current == desired:
        iam.attach_user_policy(UserName="fahrican-mail-gitops", PolicyArn=arn)
        return
    versions = iam.list_policy_versions(PolicyArn=arn)["Versions"]
    if len(versions) >= 5:
        oldest = min(
            (item for item in versions if not item["IsDefaultVersion"]),
            key=lambda item: item["CreateDate"],
        )
        iam.delete_policy_version(PolicyArn=arn, VersionId=oldest["VersionId"])
    iam.create_policy_version(
        PolicyArn=arn, PolicyDocument=json.dumps(desired), SetAsDefault=True
    )
    iam.attach_user_policy(UserName="fahrican-mail-gitops", PolicyArn=arn)
    print("Updated the scoped Matrix monitoring policy; existing access keys retained.")


def enroll_monitoring(args):
    outputs = json.loads(
        run(
            [
                "kubectl",
                "--kubeconfig",
                args.undercloud_kubeconfig,
                "-n",
                "openstack",
                "get",
                "secret",
                "mail-aws-outputs",
                "-o",
                "json",
            ]
        )
    )["data"]
    url = base64.b64decode(outputs["matrix_heartbeat_url"]).decode()
    arn = base64.b64decode(outputs["matrix_heartbeat_secret_arn"]).decode()
    if not re.fullmatch(r"https://[a-z0-9]+\.lambda-url\.eu-central-1\.on\.aws/", url):
        raise ValueError("monitoring URL is not enrolled")
    target = DEPLOYMENT / "runtime.sops.yaml"
    document = load_secret(target)
    relay = json.loads(document["stringData"]["relay.json"])
    token = relay.get("heartbeat", {}).get("token") or secrets.token_urlsafe(32)
    # Credential material stays in boto3's HTTPS request; never pass it to OpenTofu.
    aws_client("secretsmanager").put_secret_value(SecretId=arn, SecretString=token)
    relay["heartbeat"] = {"url": url + "heartbeat", "token": token}
    document["stringData"]["relay.json"] = json.dumps(relay)
    save_secret(target, document, rollout="matrix-relay")


def activate():
    document = load_secret(DEPLOYMENT / "runtime.sops.yaml")
    if not yaml.safe_load(document["stringData"]["mas.yaml"])["upstream_oauth2"][
        "providers"
    ]:
        raise ValueError("ZITADEL enrollment is incomplete")
    k = yaml.safe_load((DEPLOYMENT / "kustomization.yaml").read_text())
    if not k.get("images") or "registry.sops.yaml" not in k["resources"]:
        raise ValueError("publish and pin the image before activation")
    dns = yaml.safe_load(
        Path(
            "deployments/homelab/cloud/undercloud/85-service-dns/matrix-inputs.yaml"
        ).read_text()
    )
    if not dns["data"]["matrix_wan_ipv4_address"]:
        raise ValueError("public DNS enrollment is incomplete")
    path = DEPLOYMENT.parent / "waves.yaml"
    blocks = path.read_text().split("---\n")
    for index, block in enumerate(blocks):
        doc = yaml.safe_load(block)
        if doc and doc["metadata"]["name"] == "services-matrix":
            if doc["spec"]["suspend"]:
                blocks[index], changed = re.subn(
                    r"(?m)^([ \t]+suspend:[ \t]*)true([ \t]*(?:#[^\n]*)?)$",
                    r"\g<1>false\2",
                    block,
                    count=1,
                )
                if changed != 1:
                    raise ValueError("could not update the Matrix wave suspension")
                path.write_text("---\n".join(blocks))
            return
    raise ValueError("Matrix wave is missing")


def qualify(args):
    import urllib.request
    import urllib.error

    # Must be run from outside the LAN, after checking Element and recovery.
    for path, expected in (
        ("/_matrix/client/versions", 200),
        ("/_matrix/federation/v1/version", 404),
        ("/_synapse/admin/v1/server_version", 404),
        ("/_matrix/key/v2/server", 404),
        ("/_matrix/client/v1/media/download/matrix.org/test", 403),
        ("/_matrix/media/v3/download/matrix.org/test", 403),
    ):
        try:
            with urllib.request.urlopen(
                "https://matrix.fahrican.com" + path, timeout=10
            ) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        if status != expected:
            raise ValueError("public route qualification failed")
    cloudwatch = aws_client("cloudwatch")
    alarms = cloudwatch.describe_alarms(
        AlarmNames=[
            "stalwart-matrix-public-unavailable",
            "stalwart-matrix-delivery-stalled",
        ]
    )["MetricAlarms"]
    if len(alarms) != 2 or any(
        alarm["StateValue"] != "OK" or not alarm["ActionsEnabled"] for alarm in alarms
    ):
        raise ValueError("external availability and delivery checks are not healthy")
    jobs = json.loads(
        run(
            [
                "kubectl",
                "--kubeconfig",
                args.services_kubeconfig,
                "-n",
                "matrix-restore",
                "get",
                "jobs",
                "-o",
                "json",
            ]
        )
    )["items"]
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)

    def recent_restore(job):
        status = job.get("status", {})
        if job["metadata"].get("labels", {}).get(
            "matrix.fahrican.com/qualification"
        ) != "true" or not status.get("succeeded"):
            return False
        completed = datetime.datetime.fromisoformat(
            status["completionTime"].replace("Z", "+00:00")
        )
        return datetime.timedelta(0) <= now - completed <= datetime.timedelta(days=40)

    if not any(recent_restore(job) for job in jobs):
        raise ValueError("no successful isolated restore qualification")
    if not args.mobile_and_recovery_checked:
        raise ValueError(
            "Element decryption, push, and recovery must be checked before qualification"
        )
    path = DEPLOYMENT / "rollout.json"
    rollout = json.loads(path.read_text())
    rollout["qualified_at"] = time.time()
    path.write_text(json.dumps(rollout, indent=2) + "\n")


def retire_telegram():
    rollout = json.loads((DEPLOYMENT / "rollout.json").read_text())
    if rollout["phase"] != "matrix":
        raise ValueError("complete the qualified seven-day cutover first")
    target = Path(
        "deployments/homelab/cloud/undercloud/81-services-foundation/runtime.sops.yaml"
    )
    document = load_secret(target)
    for key in ("INFRA_TELEGRAM_BOT_TOKEN", "INFRA_TELEGRAM_CHAT_ID"):
        document["data"].pop(key, None)
    save_secret(target, document)
    contract_path = Path(
        "deployments/homelab/cloud/undercloud/82-services-cluster/runtime-contract.yaml"
    )
    cm = yaml.safe_load(contract_path.read_text())
    contract = yaml.safe_load(cm["data"]["required-keys.yaml"])
    contract["credentials"].pop("infrastructure", None)
    contract["provisionedSecrets"].pop("telegram-infrastructure", None)
    cm["data"]["required-keys.yaml"] = yaml.safe_dump(contract, sort_keys=False)
    contract_path.write_text(yaml.safe_dump(cm, sort_keys=False))
    bots_path = Path("deployments/homelab/cloud/telegram-bots.yaml")
    bots = yaml.safe_load(bots_path.read_text())
    bots["bots"].pop("infrastructure", None)
    bots_path.write_text(yaml.safe_dump(bots, sort_keys=False))
    chart_path = DEPLOYMENT.parent / "12-observability/kube-prometheus-stack.yaml"
    charts = list(yaml.safe_load_all(chart_path.read_text()))
    for chart in charts:
        if chart["kind"] == "HelmRelease":
            chart["spec"]["values"]["alertmanager"]["alertmanagerSpec"]["secrets"] = []
    chart_path.write_text(yaml.safe_dump_all(charts, sort_keys=False))
    print(
        "Retired infrastructure Telegram credentials. Revoke the bot token with BotFather and remove host token files after host rollout."
    )


def publish(args):
    credentials = load_secret(
        Path("deployments/homelab/cloud/services/46-forge/runtime.sops.yaml")
    )["stringData"]
    authentication = base64.b64encode(
        ("forge-runner:" + credentials["forgejo-runner-password"]).encode()
    ).decode()
    fd = os.memfd_create("matrix-registry", os.MFD_CLOEXEC)
    destination = "git.fahrican.com/forge-runner/matrix-runtime:1.0.0"
    try:
        auth = {"auths": {"git.fahrican.com": {"auth": authentication}}}
        os.write(fd, json.dumps(auth).encode())
        os.lseek(fd, 0, os.SEEK_SET)
        runargs = [
            "skopeo",
            "copy",
            "--quiet",
            "--dest-authfile",
            f"/proc/self/fd/{fd}",
            "docker-archive:" + str(args.image),
            "docker://" + destination,
        ]
        subprocess.run(runargs, pass_fds=(fd,), capture_output=True, check=True)
        result = subprocess.run(
            [
                "skopeo",
                "inspect",
                "--authfile",
                f"/proc/self/fd/{fd}",
                "--format",
                "{{.Digest}}",
                "docker://" + destination,
            ],
            pass_fds=(fd,),
            capture_output=True,
            check=True,
        )
        digest = result.stdout.decode().strip()
        if not re.fullmatch("sha256:[a-f0-9]{64}", digest):
            raise ValueError("invalid published image digest")
        kfile = DEPLOYMENT / "kustomization.yaml"
        k = yaml.safe_load(kfile.read_text())
        k["images"] = [
            {
                "name": destination.split(":")[0],
                "newName": destination.split(":")[0],
                "digest": digest,
            }
        ]
        kfile.write_text(yaml.safe_dump(k, sort_keys=False))
        registry_secret = secret(
            "matrix-registry", "matrix", {".dockerconfigjson": json.dumps(auth)}
        )
        registry_secret["type"] = "kubernetes.io/dockerconfigjson"
        save_secret(DEPLOYMENT / "registry.sops.yaml", registry_secret)
        restore_registry = secret(
            "matrix-registry",
            "backup-qualification",
            {".dockerconfigjson": json.dumps(auth)},
        )
        restore_registry["type"] = "kubernetes.io/dockerconfigjson"
        save_secret(DEPLOYMENT / "registry-restore.sops.yaml", restore_registry)
        if "registry.sops.yaml" not in k["resources"]:
            k["resources"].append("registry.sops.yaml")
        if "registry-restore.sops.yaml" not in k["resources"]:
            k["resources"].append("registry-restore.sops.yaml")
        restore_file = DEPLOYMENT / "restore.yaml"
        restore_docs = list(yaml.safe_load_all(restore_file.read_text()))
        for doc in restore_docs:
            if doc["kind"] == "ConfigMap":
                value = doc["data"]["resource-modifiers.yaml"]
                doc["data"]["resource-modifiers.yaml"] = re.sub(
                    re.escape(destination) + r"(?:@sha256:[a-f0-9]{64})?",
                    destination + "@" + digest,
                    value,
                )
        restore_file.write_text(
            yaml.dump_all(restore_docs, Dumper=LiteralDumper, sort_keys=False)
        )
        kfile.write_text(yaml.safe_dump(k, sort_keys=False))
        print("Published and pinned " + destination + "@" + digest)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("initialize")
    sub.add_parser("activate")
    sub.add_parser("retire-telegram")
    identity = sub.add_parser("sync-identity")
    identity.add_argument(
        "--undercloud-kubeconfig", default=os.environ.get("KUBECONFIG")
    )
    bot = sub.add_parser("enroll-bot")
    bot.add_argument("--services-kubeconfig", default=os.environ.get("KUBECONFIG"))
    bot.add_argument("--owner", required=True)
    bot.add_argument("--homeserver", default="https://matrix.fahrican.com")
    device = sub.add_parser("approve-device")
    for name in ("user", "device", "fingerprint"):
        device.add_argument("--" + name, required=True)
    alerting = sub.add_parser("configure-alerting")
    alerting.add_argument("--host", action="append", default=[])
    alerting.add_argument("--phase", choices=["dual", "matrix"], default="dual")
    publication = sub.add_parser("publish-image")
    publication.add_argument("image", type=Path)
    dns = sub.add_parser("configure-dns")
    dns.add_argument("--wan-ipv4", required=True)
    monitoring = sub.add_parser("enroll-monitoring")
    monitoring.add_argument(
        "--undercloud-kubeconfig", default=os.environ.get("KUBECONFIG")
    )
    monitoring_policy = sub.add_parser("sync-monitoring-policy")
    monitoring_policy.add_argument("--aws-profile", default="default")
    qualification = sub.add_parser("qualify")
    qualification.add_argument(
        "--services-kubeconfig", default=os.environ.get("KUBECONFIG")
    )
    qualification.add_argument("--mobile-and-recovery-checked", action="store_true")
    args = parser.parse_args()
    for name in ("undercloud_kubeconfig", "services_kubeconfig"):
        if hasattr(args, name) and not getattr(args, name):
            parser.error(
                f"provide --{name.replace('_', '-')} or run through matrix-access"
            )
    if not Path(".git").exists():
        raise ValueError("run from the infrastructure repository root")
    if args.command == "initialize":
        initialize()
    elif args.command == "sync-identity":
        sync_identity(args)
    elif args.command == "enroll-bot":
        asyncio.run(enroll_bot(args))
    elif args.command == "approve-device":
        approve_device(args)
    elif args.command == "configure-alerting":
        configure_alerting(args)
    elif args.command == "publish-image":
        publish(args)
    elif args.command == "activate":
        activate()
    elif args.command == "enroll-monitoring":
        enroll_monitoring(args)
    elif args.command == "sync-monitoring-policy":
        sync_monitoring_policy(args)
    elif args.command == "qualify":
        qualify(args)
    elif args.command == "retire-telegram":
        retire_telegram()
    elif args.command == "configure-dns":
        ip = ipaddress.IPv4Address(args.wan_ipv4)
        if not ip.is_global:
            raise ValueError("WAN address must be a globally routable IPv4 address")
        path = Path(
            "deployments/homelab/cloud/undercloud/85-service-dns/matrix-inputs.yaml"
        )
        doc = yaml.safe_load(path.read_text())
        doc["data"]["matrix_wan_ipv4_address"] = str(ip)
        path.write_text(yaml.safe_dump(doc, sort_keys=False))
    print("Matrix configuration reconciled; credentials were not displayed.")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:
        raise SystemExit(
            "Matrix enrollment failed; check configuration, SOPS, and cluster access. Secret diagnostics suppressed."
        ) from None
