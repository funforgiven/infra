"""Cross-file consistency and safety checks for the network automation inputs."""

from __future__ import annotations

import ipaddress
import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
AUTOMATION = ROOT / "components/homelab/network-automation"
NETWORK = ROOT / "deployments/homelab/network"
CLUSTER = ROOT / "deployments/homelab/cluster"


def load_all(path: Path) -> list[dict]:
    return [document for document in yaml.safe_load_all(path.read_text()) if document]


def routeros_tasks() -> list[tuple[Path, dict]]:
    """Every task of the playbook and the task files it imports."""
    tasks = []
    for play in yaml.safe_load((AUTOMATION / "reconcile-routeros.yaml").read_text()):
        for task in play.get("pre_tasks", []) + play.get("tasks", []):
            tasks.append((AUTOMATION / "reconcile-routeros.yaml", task))
    for path in sorted((AUTOMATION / "tasks").glob("*.yaml")):
        tasks.extend((path, task) for task in yaml.safe_load(path.read_text()))
    return tasks


class NetworkInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        inventory = yaml.safe_load((NETWORK / "network-inventory.yaml").read_text())["all"]
        cls.root = inventory
        cls.switch = inventory["children"]["core_switch"]["hosts"]["crs510"]
        cls.router = inventory["children"]["core_router"]["hosts"]["ccr2004"]
        cls.hosts = json.loads((ROOT / "deployments/homelab/hosts/inventory.json").read_text())["hosts"]
        cls.host_keys = json.loads((ROOT / "deployments/homelab/ssh-host-keys.json").read_text())
        zone = "\n".join(
            value
            for document in load_all(CLUSTER / "infrastructure/dns/dns.yaml")
            if document["kind"] == "ConfigMap"
            for value in document.get("data", {}).values()
        )
        cls.mgmt_records = {
            fields[0]: fields[3]
            for fields in (line.split() for line in zone.splitlines())
            if len(fields) == 4 and fields[1:3] == ["IN", "A"] and fields[0].endswith(".mgmt")
        }

    def test_routeros_connections_use_pinned_host_keys(self) -> None:
        for name, host in {"crs510": self.switch, "ccr2004": self.router}.items():
            self.assertEqual(
                f"/run/secrets/homelab-routeros-{name}-login-password",
                host["routeros_login_password_file"],
            )
            self.assertEqual([host["ansible_host"]], self.host_keys[name]["hostNames"])
        config = (AUTOMATION / "ansible.cfg").read_text()
        self.assertIn("host_key_checking = True", config)
        self.assertIn("host_key_auto_add = False", config)

    def test_physical_host_keys_match_the_host_inventory(self) -> None:
        for name, host in self.hosts.items():
            self.assertEqual([host["management"], name], self.host_keys[name]["hostNames"])

    def test_identities_are_unique(self) -> None:
        ports = [
            member["switch_port"]
            for bond in self.switch["crs_cloud_fabric"]["server_bonds"]
            for member in bond["members"]
        ]
        self.assertEqual(len(ports), len(set(ports)))
        leases = self.router["routeros_static_leases"]
        for field in ("comment", "mac_address", "address"):
            values = [lease[field] for lease in leases]
            self.assertEqual(len(values), len(set(values)), field)
        comments = [
            row["comment"]
            for section in (
                "routeros_access_rules", "routeros_port_forwards",
                "routeros_nat_reflections", "routeros_source_port_pins",
                "routeros_lan_peer_rules",
            )
            for row in self.router[section]
        ]
        self.assertEqual(len(comments), len(set(comments)))

    def test_management_dns_lists_exactly_the_managed_devices(self) -> None:
        management = ipaddress.ip_network(self.router["routeros_management_dhcp"]["network"])
        expected = {
            lease["address"]
            for lease in self.router["routeros_static_leases"]
            if lease["server"] == self.router["routeros_management_dhcp"]["name"]
        } | {self.switch["ansible_host"], self.router["routeros_management_dhcp"]["gateway"]}
        self.assertEqual(
            expected,
            {
                address for address in self.mgmt_records.values()
                if ipaddress.ip_address(address) in management
            },
        )
        for name, host in self.hosts.items():
            self.assertEqual(host["management"], self.mgmt_records[f"{name}.mgmt"])

    def test_host_scoped_access_rules_use_inventory_addresses(self) -> None:
        rules = [rule for rule in self.router["routeros_access_rules"] if "host" in rule]
        self.assertTrue(rules)
        for rule in rules:
            self.assertEqual(f"{self.hosts[rule['host']]['management']}/32", rule["source_address"])

    def test_ap_controller_discovery_points_at_the_unifi_record(self) -> None:
        options = {row["name"]: row for row in self.router["routeros_dhcp_options"]}
        controller = ipaddress.ip_address(self.router["routeros_unifi_dns"]["address"])
        for lease in self.router["routeros_static_leases"]:
            if "dhcp_option" not in lease:
                continue
            option = options[lease["dhcp_option"]]
            self.assertEqual(43, option["code"])
            self.assertEqual(bytes([1, 4]) + controller.packed, bytes.fromhex(option["value"][2:]))

    def test_wan_forwards_target_declared_load_balancer_ports(self) -> None:
        services = {}
        for path in CLUSTER.rglob("*.yaml"):
            if "vendor" in path.parts:
                continue
            try:
                documents = load_all(path)
            except yaml.YAMLError:
                continue
            for document in documents:
                if not isinstance(document, dict) or document.get("kind") != "Service":
                    continue
                address = document["metadata"].get("annotations", {}).get("metallb.io/loadBalancerIPs")
                if address:
                    services[address] = {
                        (port.get("protocol", "TCP").lower(), port["port"]) for port in document["spec"]["ports"]
                    }
        provider = ipaddress.ip_network(self.router["routeros_provider_network"]["network"])
        checked = 0
        for row in self.router["routeros_port_forwards"] + self.router["routeros_nat_reflections"]:
            if row["to_address"] not in services:
                continue
            self.assertIn(ipaddress.ip_address(row["to_address"]), provider)
            first, _, last = row["to_port"].partition("-")
            for port in range(int(first), int(last or first) + 1):
                self.assertIn((row["protocol"], port), services[row["to_address"]], row["comment"])
            checked += 1
        self.assertGreaterEqual(checked, 4)

    def test_mail_peer_matches_its_vpn_document_and_gateway(self) -> None:
        vpn = json.loads((NETWORK / "mail-admin-vpn.json").read_text())
        wireguard = self.router["routeros_wireguard"]
        peer = next(peer for peer in wireguard["peers"] if peer["name"] == "mail-aws")
        self.assertTrue(peer["isolated_backend"])
        self.assertEqual(vpn["address"], peer["allowed_address"])
        self.assertEqual(vpn["publicKey"], peer["public_key"])
        self.assertEqual(vpn["routerPublicKey"], wireguard["public_key"])
        self.assertTrue(vpn["endpoint"].endswith(f":{wireguard['listen_port']}"))
        rules = [
            rule for rule in self.router["routeros_access_rules"]
            if rule.get("destination") == vpn["address"]
        ]
        self.assertEqual(set(vpn["gatewaySources"]), {rule["source_address"] for rule in rules})
        resources = load_all(CLUSTER / "infrastructure/gateway/mail-admin.yaml")
        endpoint = next(obj for obj in resources if obj["kind"] == "EndpointSlice")
        self.assertEqual([vpn["backendAddress"]], endpoint["endpoints"][0]["addresses"])
        policy = next(obj for obj in resources if obj["kind"] == "SecurityPolicy")
        self.assertIn(
            wireguard["network"],
            policy["spec"]["authorization"]["rules"][0]["principal"]["clientCIDRs"],
        )


class PlaybookSafetyTests(unittest.TestCase):
    """Properties that keep inspection read-only and RouterOS failures fatal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = routeros_tasks()

    def test_default_run_cannot_mutate(self) -> None:
        for path, task in self.tasks:
            if "community.routeros.command" in task and "never" not in task.get("tags", []):
                self.assertIs(False, task.get("changed_when"), f"{path.name}: {task['name']}")

    def test_routeros_scripts_must_reach_a_completion_marker(self) -> None:
        # RouterOS prints script errors without failing the SSH command, so a
        # script counts as successful only when its runtime-built marker
        # appears. A single attempt prevents blind retries of a mutation.
        for path, task in self.tasks:
            command = task.get("community.routeros.command")
            if not command:
                continue
            script = "\n".join(command["commands"])
            if ":error" in script or "never" in task.get("tags", []):
                with self.subTest(task=task["name"]):
                    self.assertIn('("__infra_" .', script)
                    self.assertEqual(1, command.get("retries"))
                    self.assertTrue(any("__infra_" in check for check in command["wait_for"]))

    def test_secret_bearing_tasks_are_not_logged(self) -> None:
        markers = (
            "lookup('ansible.builtin.file'", "ansible_password",
            "routeros_wireguard_private_key", "routeros_mullvad_private_key",
        )
        for path, task in self.tasks:
            text = json.dumps(task)
            if any(marker in text for marker in markers):
                self.assertTrue(task.get("no_log"), f"{path.name}: {task['name']}")

    def test_ansible_assertions_are_string_expressions(self) -> None:
        def visit(value, source: Path) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "that":
                        expressions = child if isinstance(child, list) else [child]
                        self.assertTrue(
                            all(isinstance(expression, str) for expression in expressions),
                            f"non-string assertion in {source}",
                        )
                    visit(child, source)
            elif isinstance(value, list):
                for child in value:
                    visit(child, source)

        for path, task in self.tasks:
            visit(task, path)


if __name__ == "__main__":
    unittest.main()
