from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
INVENTORY = ROOT / "deployments/homelab/cloud/network-inventory.yaml"
HOST_DEFAULTS = ROOT / "deployments/homelab/cloud/hosts/group_vars/all.yml"
HOST_KEYS = ROOT / "deployments/homelab/ssh-host-keys.json"
PLAYBOOK = ROOT / "components/cloud/network-automation/reconcile-routeros.yaml"
ANSIBLE_CONFIG = ROOT / "components/cloud/network-automation/ansible.cfg"
CLOUD_COMPONENTS = ROOT / "components/cloud"


class NetworkInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        inventory = yaml.safe_load(INVENTORY.read_text())
        cls.root = inventory["all"]
        cls.switch = cls.root["children"]["core_switch"]["hosts"]["crs510"]
        cls.router = cls.root["children"]["core_router"]["hosts"]["ccr2004"]
        cls.host_defaults = yaml.safe_load(HOST_DEFAULTS.read_text())
        cls.host_keys = json.loads(HOST_KEYS.read_text())
        cls.playbook = PLAYBOOK.read_text()
        cls.ansible_config = ANSIBLE_CONFIG.read_text()

    def test_routeros_connections_use_standard_pinned_host_keys(self) -> None:
        self.assertEqual("admin", self.root["vars"]["ansible_user"])
        for name, host in {"crs510": self.switch, "ccr2004": self.router}.items():
            self.assertEqual(
                f"/run/secrets/homelab-routeros-{name}-login-password",
                host["routeros_login_password_file"],
            )
            self.assertEqual(
                [host["ansible_host"]], self.host_keys[name]["hostNames"]
            )
            self.assertTrue(self.host_keys[name]["publicKey"].startswith("ssh-"))
        self.assertIn("host_key_checking = True", self.ansible_config)
        self.assertIn("host_key_auto_add = False", self.ansible_config)

    def test_cloud_fabric_has_unique_two_member_bonds(self) -> None:
        fabric = self.switch["crs_cloud_fabric"]
        bonds = fabric["server_bonds"]
        self.assertEqual(3, len(bonds))
        self.assertEqual("802.3ad", fabric["bond_policy"]["mode"])
        self.assertEqual(9000, fabric["bond_policy"]["mtu"])
        self.assertEqual(9216, fabric["bond_policy"]["l2_mtu"])
        ports = [member["switch_port"] for bond in bonds for member in bond["members"]]
        self.assertTrue(all(len(bond["members"]) == 2 for bond in bonds))
        self.assertEqual(len(ports), len(set(ports)))

    def test_server_link_policy_matches_the_physical_map(self) -> None:
        bonds = self.switch["crs_cloud_fabric"]["server_bonds"]
        self.assertEqual(
            {
                "taleggio": ["sfp28-3", "sfp28-4"],
                "asiago": ["sfp28-5", "sfp28-6"],
                "pecorino": ["sfp28-7", "sfp28-8"],
            },
            {
                bond["host"]: [member["switch_port"] for member in bond["members"]]
                for bond in bonds
            },
        )
        expected_policy = {
            "auto_negotiation": False,
            "speed": "25G-baseCR",
            "fec_mode": "fec91",
        }
        self.assertTrue(
            all(
                member["phy_policy"] == expected_policy
                for bond in bonds
                for member in bond["members"]
            )
        )

    def test_server_ports_are_safe_edges_with_real_jumbo_frames(self) -> None:
        l2_task = "Reconcile the server-member L2 frame ceiling"
        bond_task = "Create or reconcile the inventory-defined physical server bonds"
        self.assertIn("edge=auto frame-types=admit-only-vlan-tagged", self.playbook)
        self.assertNotIn("edge=no frame-types=admit-only-vlan-tagged", self.playbook)
        self.assertLess(self.playbook.index(l2_task), self.playbook.index(bond_task))
        self.assertIn("Assert every server-member L2 frame ceiling", self.playbook)

    def test_physical_hosts_use_standard_pinned_host_keys(self) -> None:
        for name, address in {
            "asiago": "10.21.20.12",
            "pecorino": "10.21.20.10",
            "taleggio": "10.21.20.11",
        }.items():
            self.assertEqual(
                [address, name], self.host_keys[name]["hostNames"]
            )
            self.assertTrue(
                self.host_keys[name]["publicKey"].startswith("ssh-ed25519 ")
            )

    def test_static_leases_are_unique_and_data_driven(self) -> None:
        leases = self.router["routeros_static_leases"]
        for field in ("comment", "mac_address", "address"):
            values = [lease[field] for lease in leases]
            self.assertEqual(len(values), len(set(values)))
        self.assertIn('loop: "{{ routeros_static_leases }}"', self.playbook)

    def test_private_split_dns_is_one_exact_data_driven_forwarder(self) -> None:
        self.assertEqual(
            {
                "name": "cloud.fahrican.com",
                "type": "FWD",
                "forward_to": "10.21.20.129",
                "match_subdomain": True,
                "comment": "infra: private cloud split DNS",
            },
            self.router["routeros_private_dns_forward"],
        )
        self.assertIn("/ip dns get allow-remote-requests", self.playbook)
        self.assertNotIn("/ip dns set allow-remote-requests", self.playbook)
        self.assertIn("Reconcile Git-owned private DNS forwarders", self.playbook)
        self.assertIn("Prove every Git-owned private DNS forwarder", self.playbook)
        for field in (
            "comment",
            "disabled",
            "forward-to",
            "match-subdomain",
            "name",
            "type",
        ):
            self.assertIn(field, self.playbook)

    def test_external_provider_vlan_is_reconciled_end_to_end(self) -> None:
        self.assertEqual(
            [20, 30, 31, 32, 33, 40],
            list(self.host_defaults["cloud_vlan_mtu"]),
        )
        self.assertNotIn("cloud_provider_vlans", self.host_defaults)
        self.assertEqual(
            [20, 30, 31, 32, 33, 40],
            [row["id"] for row in self.switch["crs_cloud_fabric"]["bridge_vlans"]],
        )
        provider = self.router["routeros_provider_network"]
        self.assertEqual(40, provider["vlan_id"])
        self.assertEqual("10.21.40.1/24", provider["address"])
        self.assertEqual("10.21.40.0/24", provider["network"])
        self.assertEqual(
            [
                (
                    "infra: SERVERS to CAPI management API",
                    "infra-forward",
                    "vlan20-servers",
                    "10.21.40.100",
                    "tcp",
                    "6443",
                ),
                (
                    "infra: CLOUD-EXTERNAL DNS UDP",
                    "infra-input",
                    "vlan40-external",
                    None,
                    "udp",
                    "53",
                ),
                (
                    "infra: CLOUD-EXTERNAL DNS TCP",
                    "infra-input",
                    "vlan40-external",
                    None,
                    "tcp",
                    "53",
                ),
                (
                    "infra: CLOUD-EXTERNAL to private cloud APIs",
                    "infra-forward",
                    "vlan40-external",
                    "10.21.20.130",
                    "tcp",
                    "80,443",
                ),
            ],
            [
                (
                    rule["comment"],
                    rule["chain"],
                    rule["source_interface"],
                    rule.get("destination"),
                    rule["protocol"],
                    rule["destination_port"],
                )
                for rule in provider["access_rules"]
            ],
        )
        self.assertIn('loop: "{{ routeros_provider_network.access_rules }}"', self.playbook)
        self.assertIn("Reconcile the external provider network", self.playbook)
        self.assertIn("Reconcile provider access rules", self.playbook)
        self.assertIn("Prove the external provider network", self.playbook)
        self.assertIn("Prove provider access rules", self.playbook)

    def test_apply_tag_keeps_credentials_and_preflight_before_mutations(self) -> None:
        result = subprocess.run(
            [
                "ansible-playbook",
                "--list-tasks",
                "--tags",
                "apply",
                "reconcile-routeros.yaml",
            ],
            cwd=PLAYBOOK.parent,
            check=True,
            capture_output=True,
            text=True,
        )
        output = result.stdout
        sections = output.split("play #")[1:]
        self.assertEqual(2, len(sections))
        for section, preflight, mutation in (
            (
                sections[0],
                "Read current bridge VLAN state",
                "Create or reconcile the inventory-defined physical server bonds",
            ),
            (
                sections[1],
                "Read current CCR2004 static leases",
                "Reconcile Git-owned static DHCP leases",
            ),
        ):
            credential = "Load the RouterOS login password from its sops-nix runtime file"
            self.assertIn(credential, section)
            self.assertIn(preflight, section)
            self.assertIn(mutation, section)
            self.assertLess(section.index(credential), section.index(preflight))
            self.assertLess(section.index(preflight), section.index(mutation))

        router_section = sections[1]
        dns_mutation = "Reconcile Git-owned private DNS forwarders"
        dns_postflight = "Prove every Git-owned private DNS forwarder"
        self.assertIn(dns_mutation, router_section)
        self.assertIn(dns_postflight, router_section)
        self.assertLess(
            router_section.index("Read current CCR2004 static leases"),
            router_section.index(dns_mutation),
        )
        self.assertLess(
            router_section.index(dns_mutation),
            router_section.index(dns_postflight),
        )

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

        for pattern in ("*.yml", "*.yaml"):
            for source in CLOUD_COMPONENTS.rglob(pattern):
                for document in yaml.safe_load_all(source.read_text()):
                    visit(document, source)


if __name__ == "__main__":
    unittest.main()
