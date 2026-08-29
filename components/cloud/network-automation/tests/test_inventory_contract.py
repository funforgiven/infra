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
INTERNAL_DNS = ROOT / "deployments/homelab/cloud/undercloud/37-service-network/internal-dns.yaml"
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
        cls.internal_dns = INTERNAL_DNS.read_text()
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

    def test_wireguard_is_split_tunnel_and_inventory_driven(self) -> None:
        wireguard = self.router["routeros_wireguard"]
        self.assertEqual("10.21.91.1/24", wireguard["address"])
        self.assertEqual("10.21.91.0/24", wireguard["network"])
        self.assertEqual(51820, wireguard["listen_port"])
        self.assertEqual(1420, wireguard["mtu"])
        self.assertEqual("INFRA-WAN", wireguard["wan_interface_list"])
        self.assertEqual(
            "/run/secrets/homelab-routeros-ccr2004-wireguard-private-key",
            wireguard["private_key_file"],
        )
        self.assertTrue(
            all(
                peer["allowed_address"].startswith("10.21.91.")
                and peer["allowed_address"].endswith("/32")
                and peer["preshared_key_file"].startswith("/run/secrets/")
                for peer in wireguard["peers"]
            )
        )
        self.assertNotIn("nat", wireguard)
        wireguard_rules = [
            rule
            for rule in self.router["routeros_access_rules"]
            if rule["source_interface"] == wireguard["name"]
        ]
        self.assertEqual(
            len(wireguard_rules),
            len({rule["comment"] for rule in wireguard_rules}),
        )
        self.assertTrue(wireguard_rules)
        self.assertIn(
            "tasks/reconcile-routeros-wireguard.yaml",
            self.playbook,
        )

    def test_mullvad_routes_only_ototoy_from_trusted_vlan(self) -> None:
        mullvad = self.router["routeros_mullvad"]
        routing = mullvad["routing"]
        peer = mullvad["peer"]
        provider = self.router["routeros_provider_network"]

        self.assertEqual("wg-mullvad-jp", mullvad["name"])
        self.assertEqual("10.66.16.158/32", mullvad["address"])
        self.assertEqual(51821, mullvad["listen_port"])
        self.assertEqual(1420, mullvad["mtu"])
        self.assertEqual(
            "/run/secrets/homelab-routeros-ccr2004-mullvad-private-key",
            mullvad["private_key_file"],
        )
        self.assertEqual("jp-osa-wg-102", peer["name"])
        self.assertEqual("194.127.166.81", peer["endpoint_address"])
        self.assertEqual(51820, peer["endpoint_port"])
        self.assertEqual("0.0.0.0/0", peer["allowed_address"])
        self.assertEqual("mullvad-ototoy", routing["table"])
        self.assertEqual(provider["trusted_interface"], routing["source_interface"])
        self.assertEqual("10.21.10.0/24", routing["source_network"])
        self.assertEqual("ototoy.jp", routing["destination_name"])
        self.assertEqual("210.135.96.195/32", routing["destination"])
        self.assertEqual("infra-forward", routing["forward_chain"])
        self.assertIn(
            "tasks/reconcile-routeros-mullvad.yaml",
            self.playbook,
        )

        mullvad_tasks = (
            ROOT
            / "components/cloud/network-automation/tasks/reconcile-routeros-mullvad.yaml"
        ).read_text()
        self.assertIn("action=lookup-only-in-table", mullvad_tasks)
        self.assertIn("in-interface={{ routeros_mullvad.routing.source_interface }}", mullvad_tasks)
        self.assertIn("out-interface={{ routeros_mullvad.name }}", mullvad_tasks)
        self.assertIn("action=masquerade", mullvad_tasks)
        self.assertNotIn("action=lookup table=", mullvad_tasks)

        selected = subprocess.run(
            [
                "ansible-playbook",
                "--list-tasks",
                "--tags",
                "mullvad",
                "reconcile-routeros.yaml",
            ],
            cwd=PLAYBOOK.parent,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("Reconcile the Mullvad WireGuard client interface", selected)
        self.assertIn("Activate the fail-closed OTOTOY policy rule last", selected)
        for unrelated_mutation in (
            "Reconcile the WireGuard admin interface",
            "Reconcile the external provider network",
            "Reconcile Git-owned static DHCP leases",
        ):
            self.assertNotIn(unrelated_mutation, selected)

    def test_internal_management_dns_matches_host_inventory(self) -> None:
        for host in ("pecorino", "taleggio", "asiago"):
            variables = yaml.safe_load(
                (ROOT / f"deployments/homelab/cloud/hosts/host_vars/{host}.yml").read_text()
            )
            address = variables["cloud_vlan_addresses"][20]
            self.assertIn(f"{host}.mgmt IN A {address}", self.internal_dns)
        self.assertNotIn("pecorino.mgmt IN A 10.21.20.13", self.internal_dns)

    def test_factorio_has_one_port_preserving_udp_wan_forward(self) -> None:
        factorio_forwards = [
            item
            for item in self.router["routeros_port_forwards"]
            if item["comment"] == "infra: Factorio Space Age"
        ]
        self.assertEqual(
            [
                {
                    "comment": "infra: Factorio Space Age",
                    "in_interface_list": "INFRA-WAN",
                    "protocol": "udp",
                    "destination_port": "34197",
                    "to_address": "10.21.40.123",
                    "to_port": "34197",
                }
            ],
            factorio_forwards,
        )
        self.assertIn("wan-port-forwards", self.playbook)
        self.assertIn("connection-nat-state=dstnat", self.playbook)

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
        provider_rules = [
            rule
            for rule in self.router["routeros_access_rules"]
            if rule["source_interface"] != self.router["routeros_wireguard"]["name"]
        ]
        self.assertEqual(40, provider["vlan_id"])
        self.assertEqual("10.21.40.1/24", provider["address"])
        self.assertEqual("10.21.40.0/24", provider["network"])
        self.assertEqual(
            [
                (
                    "infra: SERVERS to CAPI management API",
                    "infra-forward",
                    "vlan20-servers",
                    "10.21.40.0/24",
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
                for rule in provider_rules
            ],
        )
        self.assertIn('loop: "{{ routeros_access_rules }}"', self.playbook)
        self.assertIn("Reconcile the external provider network", self.playbook)
        self.assertIn("Reconcile routed access rules", self.playbook)
        self.assertIn("Prove the external provider network", self.playbook)
        self.assertIn("Prove routed access rules", self.playbook)

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
