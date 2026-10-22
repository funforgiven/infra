#!/usr/bin/env python3
"""Enroll, cut over and publish the closed Matrix deployment without printing secrets."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import yaml

import encrypted_inputs

DEPLOYMENT = Path("deployments/homelab/cluster/apps/matrix")
OBSERVABILITY = Path("deployments/homelab/cluster/infrastructure/observability")


def run(argv, data=None):
    return subprocess.run(argv, input=data, capture_output=True, check=True).stdout


def load_secret(path):
    return encrypted_inputs.decrypt(path)[0]


def runtime_consumers():
    """Map each workload that mounts the runtime Secret to the keys it reads."""
    consumers = {}
    for document in yaml.safe_load_all((DEPLOYMENT / "workloads.yaml").read_text()):
        if document and document["kind"] in ("Deployment", "StatefulSet"):
            for volume in document["spec"]["template"]["spec"].get("volumes", []):
                if volume.get("secret", {}).get("secretName") == "matrix-runtime":
                    consumers[(document["kind"], document["metadata"]["name"])] = {
                        item["key"] for item in volume["secret"]["items"]
                    }
    return consumers


def update_runtime_rollouts(workloads, ciphertext):
    patch_path = DEPLOYMENT / "runtime-rollouts.yaml"
    patches = (
        list(yaml.safe_load_all(patch_path.read_text())) if patch_path.exists() else []
    )
    for kind, name in workloads:
        patch = next(
            (item for item in patches if item["metadata"]["name"] == name), None
        )
        if patch is None:
            patch = {
                "apiVersion": "apps/v1",
                "kind": kind,
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


def save_secret(path, document):
    runtime = path == DEPLOYMENT / "runtime.sops.yaml"
    previous = (
        encrypted_inputs.values(load_secret(path))
        if runtime and (Path.cwd() / path).exists()
        else {}
    )
    if not encrypted_inputs.save(Path.cwd(), path, [document]) or not runtime:
        return
    # Secret volume updates do not restart processes that read config at start.
    current = encrypted_inputs.values(document)
    changed = [
        workload
        for workload, keys in runtime_consumers().items()
        if any(previous.get(key) != current.get(key) for key in keys)
    ]
    if changed:
        update_runtime_rollouts(changed, (Path.cwd() / path).read_bytes())


def secret(name, namespace, values, *, watch=False):
    document = encrypted_inputs.secret(name, namespace, values)
    document["metadata"]["labels"] = {"velero.io/exclude-from-backup": "true"}
    if watch:
        document["metadata"]["labels"]["reconcile.fluxcd.io/watch"] = "Enabled"
    return document


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
        args.cluster_kubeconfig,
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
        save_secret(target, document)
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
            save_secret(target, document)
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
    save_secret(target, document)


def configure_alertmanager_mounts(phase):
    if phase not in ("dual", "matrix"):
        raise ValueError("invalid alerting phase")
    path = OBSERVABILITY / "kube-prometheus-stack.yaml"
    text = path.read_text()
    pattern = r"(?m)^        secrets:\n(?:        - [^\n]+\n)+"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError("expected one inline Alertmanager credential mount list")
    existing = yaml.safe_load(matches[0].group())["secrets"]
    names = ["matrix-alerting"]
    if phase == "dual":
        names.append("infrastructure-telegram")
    names.extend(
        name
        for name in existing
        if name not in ("matrix-alerting", "infrastructure-telegram")
    )
    # Inline Helm values take precedence over valuesFrom, including its arrays.
    # Keep this list aligned with the selected encrypted alert values.
    replacement = "        secrets:\n" + "".join(
        "        - " + name + "\n" for name in names
    )
    path.write_text(text[: matches[0].start()] + replacement + text[matches[0].end() :])


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
    sending_key = encrypted_inputs.values(load_secret(DEPLOYMENT / "email.sops.yaml"))[
        "MATRIX_RESEND_API_KEY"
    ]
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
            Path("deployments/homelab/credentials/host-runtime")
            / ("matrix-" + host + ".sops.yaml"),
            secret(
                "matrix-" + host, "matrix", {"config.json": json.dumps(host_config)}
            ),
        )
    document["stringData"]["relay.json"] = json.dumps(relay)
    save_secret(target, document)
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
        chat_id = telegram_receiver(
            load_secret_documents(OBSERVABILITY / "runtime.sops.yaml")
        )["telegram_configs"][0]["chat_id"]
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
        OBSERVABILITY / "alerting.sops.yaml",
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
            watch=True,
        ),
    )
    save_secret(
        OBSERVABILITY / "alerting-credentials.sops.yaml",
        secret(
            "matrix-alerting",
            "services-observability",
            {
                "smtp-password": sending_key,
                "alertmanager-token": relay["producers"]["alertmanager"]["token"],
            },
        ),
    )
    configure_alertmanager_mounts(args.phase)
    rollout["phase"] = args.phase
    if args.phase == "dual" and not rollout.get("dual_started_at"):
        rollout["dual_started_at"] = time.time()
    rollout_file.write_text(json.dumps(rollout, indent=2) + "\n")


def aws_client(service):
    import boto3

    source = encrypted_inputs.values(
        load_secret(Path("deployments/homelab/credentials/mail-aws/aws.sops.yaml"))
    )
    return boto3.client(
        service,
        region_name="eu-central-1",
        aws_access_key_id=source["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=source["AWS_SECRET_ACCESS_KEY"],
    )


def enroll_monitoring(outputs):
    """Read `tofu output -json` of the mail-aws root, piped to stdin."""
    url = outputs["matrix_heartbeat_url"]["value"]
    arn = outputs["matrix_heartbeat_secret_arn"]["value"]
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
    save_secret(target, document)


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
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    for namespace, name in (
        ("backup-qualification", "restore-drill"),
        ("matrix-restore", "postgres-restore-test"),
    ):
        cronjob = json.loads(
            run(
                [
                    "kubectl",
                    "--kubeconfig",
                    args.cluster_kubeconfig,
                    "-n",
                    namespace,
                    "get",
                    "cronjob",
                    name,
                    "-o",
                    "json",
                ]
            )
        )
        succeeded = cronjob.get("status", {}).get("lastSuccessfulTime")
        if not succeeded or now - datetime.datetime.fromisoformat(
            succeeded.replace("Z", "+00:00")
        ) > datetime.timedelta(days=40):
            raise ValueError("no successful isolated restore within 40 days")
    if not args.mobile_and_recovery_checked:
        raise ValueError(
            "Element decryption, push, and recovery must be checked before qualification"
        )
    path = DEPLOYMENT / "rollout.json"
    rollout = json.loads(path.read_text())
    rollout["qualified_at"] = time.time()
    path.write_text(json.dumps(rollout, indent=2) + "\n")


def load_secret_documents(path):
    return encrypted_inputs.decrypt(path)


def telegram_receiver(documents):
    values = next(
        d for d in documents if d["metadata"]["name"] == "alertmanager-runtime-values"
    )
    config = yaml.safe_load(encrypted_inputs.values(values)["values.yaml"])
    return next(
        r
        for r in config["alertmanager"]["config"]["receivers"]
        if r["name"] == "infrastructure-telegram"
    )


def retire_telegram():
    rollout = json.loads((DEPLOYMENT / "rollout.json").read_text())
    if rollout["phase"] != "matrix":
        raise ValueError("complete the qualified seven-day cutover first")
    path = OBSERVABILITY / "runtime.sops.yaml"
    documents = [
        d
        for d in load_secret_documents(path)
        if d["metadata"]["name"] != "infrastructure-telegram"
    ]
    values = next(
        d for d in documents if d["metadata"]["name"] == "alertmanager-runtime-values"
    )
    config = yaml.safe_load(encrypted_inputs.values(values)["values.yaml"])
    config["alertmanager"]["config"]["receivers"] = [
        r
        for r in config["alertmanager"]["config"]["receivers"]
        if r["name"] != "infrastructure-telegram"
    ]
    values.pop("data", None)
    values["stringData"] = {"values.yaml": yaml.safe_dump(config, sort_keys=False)}
    encrypted_inputs.save(Path.cwd(), path, documents)
    configure_alertmanager_mounts("matrix")
    print(
        "Removed the infrastructure Telegram receiver and bot token. Revoke the bot token with BotFather."
    )


def publish(args):
    credentials = load_secret(
        Path("deployments/homelab/cluster/apps/forge/runtime.sops.yaml")
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
            "matrix-restore",
            {".dockerconfigjson": json.dumps(auth)},
        )
        restore_registry["type"] = "kubernetes.io/dockerconfigjson"
        save_secret(DEPLOYMENT / "registry-restore.sops.yaml", restore_registry)
        if "registry.sops.yaml" not in k["resources"]:
            k["resources"].append("registry.sops.yaml")
        if "registry-restore.sops.yaml" not in k["resources"]:
            k["resources"].append("registry-restore.sops.yaml")
        kfile.write_text(yaml.safe_dump(k, sort_keys=False))
        print("Published and pinned " + destination + "@" + digest)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("retire-telegram")
    bot = sub.add_parser("enroll-bot")
    bot.add_argument("--kubeconfig", dest="cluster_kubeconfig", default=os.environ.get("KUBECONFIG"))
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
    sub.add_parser(
        "enroll-monitoring",
        help="pipe `nix run .#tofu -- mail-aws output -json` to stdin",
    )
    qualification = sub.add_parser("qualify")
    qualification.add_argument(
        "--kubeconfig", dest="cluster_kubeconfig", default=os.environ.get("KUBECONFIG")
    )
    qualification.add_argument("--mobile-and-recovery-checked", action="store_true")
    args = parser.parse_args()
    for name in ("cluster_kubeconfig",):
        if hasattr(args, name) and not getattr(args, name):
            parser.error(
                f"provide --{name.replace('_', '-')} or run through cluster-access"
            )
    if not Path(".git").exists():
        raise ValueError("run from the infrastructure repository root")
    if args.command == "enroll-bot":
        asyncio.run(enroll_bot(args))
    elif args.command == "approve-device":
        approve_device(args)
    elif args.command == "configure-alerting":
        configure_alerting(args)
    elif args.command == "publish-image":
        publish(args)
    elif args.command == "enroll-monitoring":
        enroll_monitoring(json.load(sys.stdin))
    elif args.command == "qualify":
        qualify(args)
    elif args.command == "retire-telegram":
        retire_telegram()
    print("Matrix configuration reconciled; credentials were not displayed.")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception:
        raise SystemExit(
            "Matrix enrollment failed; check configuration, SOPS, and cluster access. Secret diagnostics suppressed."
        ) from None
