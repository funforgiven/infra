import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import sys

import yaml

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "components/homelab/operations"))
import admin
import outside_check


class MonitoringPolicyTests(unittest.TestCase):
    def reconcile(self, *, account="123456789012", current=None):
        session, sts, provisioner, iam = (MagicMock() for _ in range(4))
        sts.get_caller_identity.return_value = {"Account": account}
        provisioner.get_caller_identity.return_value = {"Account": "123456789012"}
        session.client.side_effect = lambda name: sts if name == "sts" else iam
        iam.get_policy.return_value = {"Policy": {"DefaultVersionId": "v5"}}
        iam.get_policy_version.return_value = {
            "PolicyVersion": {"Document": current or {}}
        }
        iam.list_policy_versions.return_value = {
            "Versions": [
                {"VersionId": f"v{i}", "CreateDate": i, "IsDefaultVersion": i == 5}
                for i in range(1, 6)
            ]
        }
        with (
            patch("boto3.Session", return_value=session),
            patch.object(admin, "aws_client", return_value=provisioner),
            patch.object(Path, "read_text", return_value='{"account": "ACCOUNT_ID"}'),
        ):
            if account != "123456789012":
                with self.assertRaises(ValueError):
                    admin.sync_monitoring_policy(
                        argparse.Namespace(aws_profile="default")
                    )
            else:
                admin.sync_monitoring_policy(argparse.Namespace(aws_profile="default"))
        return iam

    def test_different_aws_account_prevents_policy_changes(self):
        iam = self.reconcile(account="999999999999")
        iam.get_policy.assert_not_called()
        iam.create_policy_version.assert_not_called()

    def test_current_policy_is_idempotent(self):
        iam = self.reconcile(current={"account": "123456789012"})
        iam.list_policy_versions.assert_not_called()
        iam.create_policy_version.assert_not_called()

    def test_full_version_inventory_retains_current_rollback_version(self):
        iam = self.reconcile()
        arn = "arn:aws:iam::123456789012:policy/fahrican-matrix-monitoring-gitops"
        iam.delete_policy_version.assert_called_once_with(PolicyArn=arn, VersionId="v1")
        iam.create_policy_version.assert_called_once_with(
            PolicyArn=arn,
            PolicyDocument='{"account": "123456789012"}',
            SetAsDefault=True,
        )


class CutoverTests(unittest.TestCase):
    def test_matrix_cutover_requires_seven_days_and_recent_qualification(self):
        now = 2_000_000
        for started, qualified in (
            (now - 6 * 86400, now),
            (now - 8 * 86400, None),
            (now - 8 * 86400, now - 86401),
            (None, now),
        ):
            with (
                self.subTest(started=started, qualified=qualified),
                tempfile.TemporaryDirectory() as directory,
            ):
                deployment = Path(directory)
                (deployment / "rollout.json").write_text(
                    json.dumps(
                        {
                            "phase": "dual",
                            "dual_started_at": started,
                            "qualified_at": qualified,
                        }
                    )
                )
                with (
                    patch.object(admin, "DEPLOYMENT", deployment),
                    patch("admin.time.time", return_value=now),
                    patch.object(admin, "load_secret") as decrypt,
                ):
                    with self.assertRaises(ValueError):
                        admin.configure_alerting(
                            argparse.Namespace(phase="matrix", host=[])
                        )
                    decrypt.assert_not_called()


class AlertingConfigurationTests(unittest.TestCase):
    def test_alertmanager_mounts_follow_phase(self):
        source = ROOT / admin.OBSERVABILITY / "kube-prometheus-stack.yaml"
        with tempfile.TemporaryDirectory() as directory:
            observability = Path(directory)
            (observability / source.name).write_text(source.read_text())
            with patch.object(admin, "OBSERVABILITY", observability):
                admin.configure_alertmanager_mounts("matrix")
                text = (observability / source.name).read_text()
                self.assertIn("        secrets:\n        - matrix-alerting\n", text)
                self.assertNotIn("- infrastructure-telegram", text)
                admin.configure_alertmanager_mounts("dual")
                self.assertIn("        - matrix-alerting\n        - infrastructure-telegram\n",
                              (observability / source.name).read_text())

    def test_runtime_save_restarts_only_consumers_of_changed_keys(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(admin.Path, "cwd", return_value=Path(directory)):
            deployment = Path(directory) / "deployments/homelab/cluster/apps/matrix"
            deployment.mkdir(parents=True)
            (deployment / "workloads.yaml").write_text(
                (ROOT / admin.DEPLOYMENT / "workloads.yaml").read_text()
            )
            stored = {}

            def save(root, relative, documents):
                if stored.get(relative) == documents[0]:
                    return False
                stored[relative] = documents[0]
                (root / relative).write_bytes(json.dumps(documents[0]).encode())
                return True

            with patch.object(admin, "DEPLOYMENT", deployment), \
                    patch.object(admin, "load_secret", side_effect=lambda path: stored[path]), \
                    patch.object(admin.encrypted_inputs, "save", side_effect=save):
                target = admin.DEPLOYMENT / "runtime.sops.yaml"
                rollouts = admin.DEPLOYMENT / "runtime-rollouts.yaml"
                values = {"relay.json": "{}", "mas.yaml": "a", "synapse.yaml": "b", "signing.key": "c"}
                admin.save_secret(target, {"stringData": dict(values)})
                self.assertEqual(
                    {(p["kind"], p["metadata"]["name"]) for p in yaml.safe_load_all(rollouts.read_text())},
                    {("StatefulSet", "matrix-relay"), ("Deployment", "matrix-mas"), ("StatefulSet", "matrix-synapse")},
                )
                before = {p["metadata"]["name"]: p for p in yaml.safe_load_all(rollouts.read_text())}
                admin.save_secret(target, {"stringData": dict(values, **{"relay.json": "[]"})})
                after = {p["metadata"]["name"]: p for p in yaml.safe_load_all(rollouts.read_text())}
                self.assertNotEqual(after["matrix-relay"], before["matrix-relay"])
                self.assertIn(hashlib.sha256(target.read_bytes()).hexdigest(), str(after["matrix-relay"]))
                self.assertEqual(after["matrix-mas"], before["matrix-mas"])
                self.assertEqual(after["matrix-synapse"], before["matrix-synapse"])
                admin.save_secret(admin.DEPLOYMENT / "email.sops.yaml", {"stringData": {"relay.json": "x"}})
                self.assertEqual({p["metadata"]["name"]: p for p in yaml.safe_load_all(rollouts.read_text())}, after)


class EnrollmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_alert_rooms_are_private_encrypted_and_non_federated(self):
        from nio import AsyncClient, RoomCreateResponse, RoomPreset

        relay = {
            "user_id": "@infra-alerts:matrix.fahrican.com",
            "device_id": "INFRA_ALERTS",
            "access_token": "synthetic-token",
            "room_id": "",
            "canary_room_id": "",
        }
        document = {"stringData": {"relay.json": json.dumps(relay)}}
        with (
            patch("nio.AsyncClient", autospec=AsyncClient) as client_type,
            patch.object(admin, "load_secret", return_value=document),
            patch.object(admin, "save_secret"),
        ):
            client = client_type.return_value
            client.room_create.side_effect = [
                RoomCreateResponse("!alerts:local"),
                RoomCreateResponse("!canary:local"),
            ]
            await admin.enroll_bot(
                argparse.Namespace(
                    owner="@owner:matrix.fahrican.com",
                    homeserver="https://matrix.fahrican.com",
                    cluster_kubeconfig="synthetic-config",
                )
            )
            self.assertEqual(client.room_create.await_count, 2)
            for call in client.room_create.await_args_list:
                self.assertFalse(call.kwargs["federate"])
                self.assertEqual(call.kwargs["preset"], RoomPreset.private_chat)
                self.assertIn(
                    {
                        "type": "m.room.encryption",
                        "state_key": "",
                        "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                    },
                    call.kwargs["initial_state"],
                )
            self.assertEqual(
                client.room_create.await_args_list[0].kwargs["invite"],
                ["@owner:matrix.fahrican.com"],
            )
            self.assertEqual(client.room_create.await_args_list[1].kwargs["invite"], [])


class OutsideCheckTests(unittest.TestCase):
    def event(self, token, path="/heartbeat", method="POST"):
        return {
            "requestContext": {"http": {"method": method}},
            "rawPath": path,
            "headers": {"authorization": "Bearer " + token},
        }

    def test_unauthorized_requests_cannot_report_healthy_or_run_probes(self):
        secret, metrics = MagicMock(), MagicMock()
        secret.get_secret_value.return_value = {"SecretString": "correct"}
        with (
            patch.dict("os.environ", {"HEARTBEAT_SECRET_ARN": "test"}),
            patch(
                "outside_check.boto3.client",
                side_effect=lambda service: (
                    secret if service == "secretsmanager" else metrics
                ),
            ),
            patch("urllib.request.urlopen") as urlopen,
        ):
            self.assertEqual(
                outside_check.handler(self.event("wrong"), None)["statusCode"], 401
            )
            self.assertEqual(
                outside_check.handler(self.event("correct", "/", "GET"), None)[
                    "statusCode"
                ],
                404,
            )
            metrics.put_metric_data.assert_not_called()
            urlopen.assert_not_called()
            self.assertEqual(
                outside_check.handler(self.event("correct"), None)["statusCode"], 202
            )
            metrics.put_metric_data.assert_called_once()

    def test_external_probe_failure_is_unhealthy(self):
        metrics = MagicMock()
        with (
            patch("outside_check.boto3.client", return_value=metrics),
            patch("urllib.request.urlopen", side_effect=OSError),
        ):
            self.assertFalse(
                outside_check.handler({"source": "aws.events"}, None)["healthy"]
            )
            metric = metrics.put_metric_data.call_args.kwargs["MetricData"][0]
            self.assertEqual(metric["Value"], 0)
