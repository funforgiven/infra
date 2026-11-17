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


class AlertingConfigurationTests(unittest.TestCase):
    def test_regeneration_removes_other_channels_and_preserves_producer_tokens(self):
        relay = {"producers": {
            "alertmanager": {"token": "alert-token", "paths": ["/alertmanager"]},
            "pecorino": {"token": "host-token", "paths": ["/notify"]},
        }}
        with tempfile.TemporaryDirectory() as directory:
            deployment = Path(directory)
            rollout = deployment / "rollout.json"
            rollout.write_text(json.dumps({"phase": "dual", "qualified_at": None}))
            saved = {}
            with (
                patch.object(admin, "DEPLOYMENT", deployment),
                patch.object(admin, "load_secret", return_value={"stringData": {"relay.json": json.dumps(relay)}}) as decrypt,
                patch.object(admin, "save_secret", side_effect=lambda path, doc: saved.update({path: doc})),
                patch.object(admin, "configure_alertmanager_mounts"),
            ):
                admin.configure_alerting(argparse.Namespace(phase="matrix", host=["pecorino"]))
                decrypt.assert_called_once_with(deployment / "runtime.sops.yaml")
                values = yaml.safe_load(saved[admin.OBSERVABILITY / "alerting.sops.yaml"]["stringData"]["values.yaml"])["alertmanager"]
                config = values["config"]
                self.assertEqual(config["route"]["receiver"], "infrastructure-matrix")
                self.assertTrue(all(r["receiver"] == "null" for r in config["route"]["routes"]))
                self.assertEqual({r["name"] for r in config["receivers"]}, {"null", "infrastructure-matrix"})
                matrix = next(r for r in config["receivers"] if r["name"] == "infrastructure-matrix")
                self.assertTrue(matrix["webhook_configs"][0]["send_resolved"])
                self.assertEqual(config["global"], {"resolve_timeout": "5m"})
                self.assertEqual(values["alertmanagerSpec"]["secrets"], ["matrix-alerting"])
                credentials = saved[admin.OBSERVABILITY / "alerting-credentials.sops.yaml"]["stringData"]
                self.assertEqual(credentials, {"alertmanager-token": "alert-token"})
                host = json.loads(saved[Path("deployments/homelab/credentials/host-runtime/matrix-pecorino.sops.yaml")]["stringData"]["config.json"])
                self.assertEqual(host["token"], "host-token")
                self.assertNotIn("smtp", host)
                self.assertEqual(json.loads(rollout.read_text()), {"phase": "matrix", "qualified_at": None})
                saved.clear()
                admin.configure_alerting(argparse.Namespace(phase="matrix", host=[]))
                self.assertNotIn(deployment / "runtime.sops.yaml", saved)

    def test_dual_delivery_is_rejected_before_changes(self):
        with patch.object(admin, "load_secret") as decrypt, patch.object(admin, "save_secret") as save:
            with self.assertRaises(ValueError):
                admin.configure_alerting(argparse.Namespace(phase="dual", host=[]))
            decrypt.assert_not_called()
            save.assert_not_called()
        with self.assertRaises(ValueError):
            admin.configure_alertmanager_mounts("dual")

    def test_alertmanager_mounts_remove_legacy_telegram(self):
        source = ROOT / admin.OBSERVABILITY / "kube-prometheus-stack.yaml"
        with tempfile.TemporaryDirectory() as directory:
            observability = Path(directory)
            (observability / source.name).write_text(source.read_text().replace(
                "        - matrix-alerting\n", "        - matrix-alerting\n        - infrastructure-telegram\n        - extra-credentials\n"))
            with patch.object(admin, "OBSERVABILITY", observability):
                admin.configure_alertmanager_mounts("matrix")
                text = (observability / source.name).read_text()
                self.assertIn("        secrets:\n        - matrix-alerting\n", text)
                self.assertNotIn("- infrastructure-telegram", text)
                self.assertIn("        - extra-credentials\n", text)

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
