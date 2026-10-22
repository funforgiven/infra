from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AUTOMATION_ROOT.parents[2]
sys.path.insert(0, str(AUTOMATION_ROOT))

import omada_reconcile as omada  # noqa: E402


DESIRED_PATH = REPOSITORY_ROOT / "deployments/homelab/network/omada-network.yaml"


def network(name: str, vlan: int) -> dict[str, object]:
    return {
        "id": f"n{vlan}", "name": name, "vlan": vlan, "purpose": 0,
        "application": 1, "allLan": True, "igmpSnoopEnable": False,
    }


def profile(
    name: str,
    profile_id: str,
    native: int,
    tagged: list[int],
    *,
    spanning_tree_enabled: bool = True,
    edge_port: bool = False,
) -> dict[str, object]:
    native_id = f"n{native}"
    return {
        "id": profile_id,
        "name": name,
        "nativeNetworkId": native_id,
        "tagNetworkIds": [f"n{vlan}" for vlan in tagged],
        "untagNetworkIds": [native_id],
        "poe": 1,
        "dot1x": 0,
        "portIsolationEnable": False,
        "lldpMedEnable": False,
        "bandWidthCtrlType": 0,
        "spanningTreeEnable": spanning_tree_enabled,
        "spanningTreeSetting": {
            "priority": 128,
            "extPathCost": 0,
            "intPathCost": 0,
            "edgePort": edge_port,
            "p2pLink": 0,
            "mcheck": False,
            "loopProtect": False,
            "rootProtect": False,
            "tcGuard": False,
            "bpduProtect": edge_port,
            "bpduFilter": False,
            "bpduForward": True,
            "instanceEnable": False,
            "instances": [],
        },
        "loopbackDetectEnable": True,
    }


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.networks = [
            network(name, vlan) for name, vlan in (
                ("Default", 1), ("TRUSTED", 10), ("SERVERS", 20),
                ("CLOUD-EXTERNAL", 40), ("IOT", 50), ("GUEST", 60),
                ("MGMT", 90),
            )
        ]
        self.profiles = [
            profile("All", "p-all", 1, []),
            profile("infra-ccr-trunk", "p-ccr", 1, [10, 20, 40, 50, 60, 90]),
            profile("infra-crs-trunk", "p-crs", 1, [10, 20, 40, 50, 90]),
            profile(
                "infra-trusted-access", "p-trusted", 10, [],
                spanning_tree_enabled=False,
            ),
            profile("infra-iot-access", "p-iot", 50, []),
            profile("infra-management-access", "p-management", 90, []),
            profile("infra-ap-trunk", "p-ap", 90, [10, 50]),
        ]
        self.ports = {
            1: {"profileId": "p-ccr", "profileName": "infra-ccr-trunk"},
            2: {"profileId": "p-trusted", "profileName": "infra-trusted-access"},
            3: {"profileId": "p-trusted", "profileName": "infra-trusted-access"},
            4: {"profileId": "p-iot", "profileName": "infra-iot-access"},
            5: {"profileId": "p-iot", "profileName": "infra-iot-access"},
            6: {"profileId": "p-ap", "profileName": "infra-ap-trunk"},
            7: {"profileId": "p-management", "profileName": "infra-management-access"},
            8: {"profileId": "p-iot", "profileName": "infra-iot-access"},
            9: {"profileId": "p-crs", "profileName": "infra-crs-trunk"},
        }
        self.devices = [
            {
                "name": "98-25-4A-CB-BF-BE", "mac": "98-25-4A-CB-BF-BE",
                "model": "SG3210XHP-M2 v3.0", "type": "switch",
            },
        ]

    def authorize(self) -> None:
        self.calls.append(("authorize", None))

    def read(self, resource: str, *values: str) -> object:
        if resource == "sites":
            return [{"siteId": "site-hark", "name": "Hark"}]
        if resource == "devices":
            return self.devices
        if resource == "networks":
            return self.networks
        if resource == "profiles":
            return self.profiles
        if resource == "ports":
            return [
                {
                    "switchMac": "98-25-4A-CB-BF-BE",
                    "switchName": "98-25-4A-CB-BF-BE", "port": number,
                    "portName": f"Port{number}", "linkSpeed": 0, "duplex": 0,
                    "tagIds": [],
                    "profileOverrideEnable": False, **state,
                }
                for number, state in self.ports.items()
            ]
        raise AssertionError(resource)

    def write(self, resource: str, values: tuple[str, ...], payload: dict[str, object]) -> None:
        if resource == "network-create":
            self.networks.append({"id": f"n{payload['vlan']}", **payload})
            self.calls.append(("create_network", payload["name"]))
        elif resource == "network-update":
            next(item for item in self.networks if item["id"] == values[1]).update(payload)
            self.calls.append(("update_network", payload["name"]))
        elif resource == "profile-create":
            created = dict(payload)
            created["id"] = f"p-{payload['name']}"
            self.profiles.append(created)
            self.calls.append(("create_profile", payload["name"]))
        elif resource == "profile-update":
            next(item for item in self.profiles if item["id"] == values[1]).update(payload)
            self.calls.append(("update_profile", payload["name"]))
        elif resource == "port-assign":
            profile_id = str(payload["profileId"])
            selected = next(item for item in self.profiles if item["id"] == profile_id)
            self.ports[int(values[2])] = {"profileId": profile_id, "profileName": selected["name"]}
            self.calls.append(("assign_profile", int(values[2])))
        else:
            raise AssertionError(resource)

def secrets() -> io.StringIO:
    document: dict[str, object] = {
        "omada": {
            "api_base": "https://controller.invalid",
            "id": "controller-id",
            "client_id": "client-id",
            "client_secret": "secret-value",
        }
    }
    return io.StringIO(json.dumps(document))


class ReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.desired = omada.load_desired(DESIRED_PATH)
        self.api = FakeApi()

    def plan(self) -> tuple[omada.Action, ...]:
        return omada.make_plan(self.desired, omada.inspect(self.api, self.desired))

    def reconcile(self) -> int:
        snapshot = omada.inspect(self.api, self.desired)
        return omada.apply(
            self.api, self.desired, snapshot, omada.make_plan(self.desired, snapshot),
            attempts=1, delay=0, sleeper=lambda _delay: None,
        )

    def test_final_plan_is_noop(self) -> None:
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_input_refuses_wireless_objects(self) -> None:
        for key in ("accessPoint", "wireless"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "omada.yaml"
                path.write_text(DESIRED_PATH.read_text() + f"{key}: {{}}\n")
                with self.assertRaisesRegex(omada.SafeError, "invalid"):
                    omada.load_desired(path)

    def test_profile_and_port_reconcile_with_one_postflight(self) -> None:
        self.api.profiles = [item for item in self.api.profiles if item["name"] != "infra-trusted-access"]
        self.api.ports[2] = {"profileId": "p-all", "profileName": "All"}
        mutations = self.reconcile()
        # Port 3 also follows the recreated profile's new identity.
        self.assertEqual(mutations, 3)
        self.assertIn(("create_profile", "infra-trusted-access"), self.api.calls)
        self.assertIn(("assign_profile", 2), self.api.calls)
        self.assertIn(("assign_profile", 3), self.api.calls)
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_domain_postflight_rereads_only_that_domain(self) -> None:
        self.api.networks = [item for item in self.api.networks if item["vlan"] != 40]
        for item in self.api.profiles:
            if item["name"] in {"infra-ccr-trunk", "infra-crs-trunk"}:
                item["tagNetworkIds"].remove("n40")
        with mock.patch.object(self.api, "read", wraps=self.api.read) as read:
            self.reconcile()
        resources = [call.args[0] for call in read.call_args_list]
        # The initial inspection and the final postflight read everything;
        # the network and profile postflights re-read only their domain.
        self.assertEqual(resources.count("devices"), 2)
        self.assertEqual(resources.count("networks"), 3)
        self.assertEqual(resources.count("profiles"), 3)

    def test_port_assignment_preserves_name_speed_duplex_and_tags(self) -> None:
        self.api.ports[4] = {
            "profileId": "p-all", "profileName": "All", "portName": "Zigbee radio",
            "linkSpeed": 2, "duplex": 2, "tagIds": ["operator-label"],
        }
        with mock.patch.object(self.api, "write", wraps=self.api.write) as write:
            self.assertEqual(self.reconcile(), 1)
        assignment = next(call for call in write.call_args_list if call.args[0] == "port-assign")
        self.assertEqual(assignment.args[2], {
            "name": "Zigbee radio", "profileId": "p-iot",
            "profileOverrideEnable": False, "profileVlanOverrideEnable": False,
            "linkSpeed": 2, "duplex": 2, "tagIds": ["operator-label"],
        })

    def test_workstation_profile_disables_stp_and_clears_subordinate_policy(self) -> None:
        trusted = next(
            item for item in self.api.profiles if item["name"] == "infra-trusted-access"
        )
        trusted["spanningTreeEnable"] = True
        spanning_tree = trusted["spanningTreeSetting"]
        spanning_tree.update(
            {"edgePort": False, "bpduProtect": False, "bpduFilter": True}
        )

        actions = self.plan()
        self.assertTrue(
            any(
                action.domain == "profile"
                and action.target == "infra-trusted-access"
                and action.operation == "update"
                for action in actions
            )
        )

        mutations = self.reconcile()
        self.assertEqual(mutations, 1)
        spanning_tree = trusted["spanningTreeSetting"]
        self.assertFalse(trusted["spanningTreeEnable"])
        self.assertFalse(spanning_tree["edgePort"])
        self.assertFalse(spanning_tree["bpduProtect"])
        self.assertFalse(spanning_tree["bpduFilter"])
        self.assertTrue(spanning_tree["bpduForward"])
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_network_is_created_before_dependent_profiles(self) -> None:
        self.api.networks = [item for item in self.api.networks if item["vlan"] != 40]
        for item in self.api.profiles:
            if item["name"] in {"infra-ccr-trunk", "infra-crs-trunk"}:
                item["tagNetworkIds"].remove("n40")
        mutations = self.reconcile()
        self.assertEqual(mutations, 3)
        self.assertEqual(self.api.calls[0], ("create_network", "CLOUD-EXTERNAL"))
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_identity_mismatch_fails_before_planning(self) -> None:
        self.api.devices = [
            {**item, "model": "wrong"} if item.get("type") == "switch" else item
            for item in self.api.devices
        ]
        with self.assertRaisesRegex(omada.SafeError, "switch identity"):
            omada.inspect(self.api, self.desired)


class CommandAndTransportTests(unittest.TestCase):
    def test_default_command_is_read_only(self) -> None:
        api = FakeApi()
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            result = omada.run(
                ["--credentials-stdin", "--desired", str(DESIRED_PATH)],
                stdin=secrets(),
                api_factory=lambda _credentials: api,
            )
        self.assertEqual(result, 0)
        self.assertIn("Read-only plan complete", output.getvalue())
        self.assertNotIn("secret-value", output.getvalue())
        self.assertEqual(api.calls, [("authorize", None)])

    def test_api_origin_requires_strict_https(self) -> None:
        for value in ("http://controller.invalid", "https://user:pass@controller.invalid", "https://controller.invalid/path"):
            with self.subTest(value=value), self.assertRaises(omada.SafeError):
                omada._https_origin(value)

    def test_http_redirect_is_rejected_and_redacted(self) -> None:
        session = mock.Mock()
        response = mock.Mock(status_code=302, content=b"secret body")
        session.request.return_value = response
        api = omada.OmadaApi(
            omada.Credentials("https://secret-controller.invalid", "id", "client", "secret"),
            session=session,
        )
        with self.assertRaises(omada.SafeError) as raised:
            api._call("test", "GET", "/private", authorized=False)
        message = str(raised.exception)
        self.assertEqual(message, "Omada test failed with HTTP status 302")
        self.assertNotIn("secret", message)
        self.assertFalse(session.request.call_args.kwargs["allow_redirects"])
        self.assertTrue(session.request.call_args.kwargs["verify"])


if __name__ == "__main__":
    unittest.main()
