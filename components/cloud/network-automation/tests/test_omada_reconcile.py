from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AUTOMATION_ROOT.parents[2]
sys.path.insert(0, str(AUTOMATION_ROOT))

import omada_reconcile as omada  # noqa: E402


DESIRED_PATH = REPOSITORY_ROOT / "deployments/homelab/cloud/omada-network.yaml"


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
        "spanningTreeEnable": True,
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


def ssid_detail(name: str, ssid_id: str, band: int, vlan: int) -> dict[str, object]:
    return {
        "ssidId": ssid_id,
        "name": name,
        "deviceType": 1,
        "band": band,
        "guestNetEnable": False,
        "security": 3,
        "broadcast": True,
        "vlanEnable": True,
        "vlanId": vlan,
        "pskSetting": {
            "versionPsk": 2,
            "encryptionPsk": 3,
            "gikRekeyPskEnable": True,
            "rekeyPskInterval": 3600,
            "intervalPskType": 0,
        },
        "mloEnable": False,
        "pmfMode": 3,
        "enable11r": False,
        "hidePwd": True,
        "greEnable": False,
        "prohibitWifiShare": False,
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
            profile("infra-crs-trunk", "p-crs", 1, [10, 20, 40, 90]),
            profile("infra-trusted-access", "p-trusted", 10, [], edge_port=True),
            profile("infra-iot-access", "p-iot", 50, []),
            profile("infra-management-access", "p-management", 90, []),
            profile("infra-ap-trunk", "p-ap", 90, [10, 50]),
        ]
        self.ports = {
            1: {"profileId": "p-ccr", "profileName": "infra-ccr-trunk"},
            2: {"profileId": "p-trusted", "profileName": "infra-trusted-access"},
            3: {"profileId": "p-management", "profileName": "infra-management-access"},
            6: {"profileId": "p-ap", "profileName": "infra-ap-trunk"},
            8: {"profileId": "p-iot", "profileName": "infra-iot-access"},
            9: {"profileId": "p-crs", "profileName": "infra-crs-trunk"},
        }
        self.ssids = {
            "Rooftrollen": ssid_detail("Rooftrollen", "s-personal", 3, 10),
            "Rooftrollen_IoT": ssid_detail("Rooftrollen_IoT", "s-iot", 1, 50),
        }
        self.ap_ip = {
            "mode": "static",
            "staticIpSetting": {
                "configIp": "10.21.90.4",
                "configMask": "255.255.255.0",
                "configGate": "10.21.90.1",
                "preferredDNS": "10.21.90.1",
            },
        }
        self.devices = [
            {
                "name": "98-25-4A-CB-BF-BE", "mac": "98-25-4A-CB-BF-BE",
                "model": "SG3210XHP-M2 v3.0", "type": "switch",
            },
            {
                "name": "9C-A2-F4-C2-ED-74", "mac": "9C-A2-F4-C2-ED-74",
                "model": "EAP670(EU) v1.0", "type": "ap", "status": 1,
                "detailStatus": 14, "ip": "10.21.90.4",
            },
        ]

    def authorize(self) -> None:
        self.calls.append(("authorize", None))

    def read(self, resource: str, *values: str) -> object:
        if resource == "sites":
            return [{"siteId": "site-hark", "name": "Hark"}]
        if resource == "devices":
            return self.devices
        if resource == "ap":
            return {
                "name": "9C-A2-F4-C2-ED-74", "mac": "9C-A2-F4-C2-ED-74",
                "type": "ap", "ip": "10.21.90.4",
            }
        if resource == "ap-ip":
            return self.ap_ip
        if resource == "ap-vlan":
            return {"mvlanSetting": {"mode": 0}}
        if resource == "networks":
            return self.networks
        if resource == "profiles":
            return self.profiles
        if resource == "ports":
            return [
                {
                    "switchMac": "98-25-4A-CB-BF-BE",
                    "switchName": "98-25-4A-CB-BF-BE", "port": number,
                    "profileOverrideEnable": False, **state,
                }
                for number, state in self.ports.items()
            ]
        if resource == "wlan-groups":
            return [{"name": "Default", "wlanId": "w-default"}]
        if resource == "ssids":
            return [
                {"name": name, "ssidId": detail["ssidId"]}
                for name, detail in self.ssids.items()
            ]
        if resource == "ssid":
            return next(detail for detail in self.ssids.values() if detail["ssidId"] == values[2])
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
        elif resource == "ssid-create":
            name = str(payload["name"])
            self.ssids[name] = self._stored_ssid(payload, f"s-{name}")
            self.calls.append(("create_ssid", name))
        elif resource == "ssid-update":
            current = next(item for item in self.ssids.values() if item["ssidId"] == values[2])
            current.update(self._stored_ssid(payload, values[2]))
            self.calls.append(("update_ssid", payload["name"]))
        else:
            raise AssertionError(resource)

    @staticmethod
    def _stored_ssid(payload: dict[str, object], ssid_id: str) -> dict[str, object]:
        stored = dict(payload)
        stored["ssidId"] = ssid_id
        psk = dict(stored["pskSetting"])
        psk.pop("securityKey")
        stored["pskSetting"] = psk
        stored.setdefault("deviceType", 1)
        return stored

def secrets(*, include_psks: bool = True) -> io.StringIO:
    document: dict[str, object] = {
        "omada": {
            "api_base": "https://controller.invalid",
            "id": "controller-id",
            "client_id": "client-id",
            "client_secret": "secret-value",
        }
    }
    if include_psks:
        document["wireless"] = {
            "psks": {"personal": "personal-password", "iot": "iot-password"}
        }
    return io.StringIO(json.dumps(document))


class ReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.desired = omada.load_desired(DESIRED_PATH)
        self.api = FakeApi()

    def plan(self, *, include_write_only: bool = False) -> tuple[omada.Action, ...]:
        return omada.make_plan(
            self.desired,
            omada.inspect(self.api, self.desired),
            include_write_only=include_write_only,
        )

    def reconcile(self, *, include_write_only: bool = False, include_psks: bool = True) -> int:
        snapshot = omada.inspect(self.api, self.desired)
        actions = omada.make_plan(
            self.desired, snapshot, include_write_only=include_write_only
        )
        return omada.apply(
            self.api, self.desired, snapshot, actions,
            json.loads(secrets(include_psks=include_psks).read()),
            include_write_only=include_write_only, attempts=1, delay=0,
            sleeper=lambda _delay: None,
        )

    def test_final_plan_is_noop_and_does_not_need_psks(self) -> None:
        actions = self.plan()
        self.assertTrue(all(action.operation == "noop" for action in actions))
        self.assertFalse(any(action.domain == "wireless" and action.mutates for action in actions))

    def test_write_only_flag_explicitly_rewrites_both_psks(self) -> None:
        mutations = self.reconcile(include_write_only=True)
        self.assertEqual(mutations, 2)
        self.assertEqual([call for call in self.api.calls if call[0] == "update_ssid"], [
            ("update_ssid", "Rooftrollen"), ("update_ssid", "Rooftrollen_IoT")
        ])

    def test_wireless_drift_requires_explicit_write_only_permission(self) -> None:
        self.api.ssids["Rooftrollen"]["vlanId"] = 50
        with self.assertRaisesRegex(omada.SafeError, "--include-write-only"):
            self.reconcile()
        self.assertFalse(any(call[0].startswith(("create_", "update_", "assign_")) for call in self.api.calls))

    def test_profile_and_port_reconcile_with_one_postflight(self) -> None:
        self.api.profiles = [item for item in self.api.profiles if item["name"] != "infra-trusted-access"]
        self.api.ports[2] = {"profileId": "p-all", "profileName": "All"}
        mutations = self.reconcile(include_psks=False)
        self.assertEqual(mutations, 2)
        self.assertIn(("create_profile", "infra-trusted-access"), self.api.calls)
        self.assertIn(("assign_profile", 2), self.api.calls)
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_workstation_profile_reconciles_edge_and_bpdu_policy(self) -> None:
        trusted = next(
            item for item in self.api.profiles if item["name"] == "infra-trusted-access"
        )
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

        mutations = self.reconcile(include_psks=False)
        self.assertEqual(mutations, 1)
        spanning_tree = trusted["spanningTreeSetting"]
        self.assertTrue(trusted["spanningTreeEnable"])
        self.assertTrue(spanning_tree["edgePort"])
        self.assertTrue(spanning_tree["bpduProtect"])
        self.assertFalse(spanning_tree["bpduFilter"])
        self.assertTrue(spanning_tree["bpduForward"])
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_network_is_created_before_dependent_profiles(self) -> None:
        self.api.networks = [item for item in self.api.networks if item["vlan"] != 40]
        for item in self.api.profiles:
            if item["name"] in {"infra-ccr-trunk", "infra-crs-trunk"}:
                item["tagNetworkIds"].remove("n40")
        mutations = self.reconcile(include_psks=False)
        self.assertEqual(mutations, 3)
        self.assertEqual(self.api.calls[0], ("create_network", "CLOUD-EXTERNAL"))
        self.assertTrue(all(action.operation == "noop" for action in self.plan()))

    def test_ap_management_drift_blocks_all_mutation(self) -> None:
        self.api.ap_ip["staticIpSetting"]["configIp"] = "10.21.90.44"
        actions = self.plan()
        self.assertTrue(any(action.domain == "access-point" and action.blocked for action in actions))
        with self.assertRaisesRegex(omada.SafeError, "blockers"):
            self.reconcile(include_psks=False)

    def test_undeclared_ssid_blocks_without_deletion(self) -> None:
        self.api.ssids["guest"] = ssid_detail("guest", "s-guest", 3, 10)
        actions = self.plan()
        self.assertTrue(any(action.target == "SSID set" and action.blocked for action in actions))
        self.assertFalse(hasattr(self.api, "delete_ssid"))

    def test_identity_mismatch_fails_before_planning(self) -> None:
        self.api.devices = [
            {**item, "model": "wrong"} if item.get("type") == "switch" else item
            for item in self.api.devices
        ]
        with self.assertRaisesRegex(omada.SafeError, "switch identity"):
            omada.inspect(self.api, self.desired)


class CommandAndTransportTests(unittest.TestCase):
    def test_default_command_is_read_only_and_does_not_require_psks(self) -> None:
        api = FakeApi()
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            result = omada.run(
                ["--credentials-stdin", "--desired", str(DESIRED_PATH)],
                stdin=secrets(include_psks=False),
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
