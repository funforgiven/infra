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
FACTORIO_RENDER_CONFIG = (
    ROOT / "deployments/homelab/cloud/services/30-factorio/render-config.sh"
)
FACTORIO_WORKLOAD = (
    ROOT / "deployments/homelab/cloud/services/30-factorio/factorio.yaml"
)
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
        cls.factorio_render_config = FACTORIO_RENDER_CONFIG.read_text()
        factorio_documents = list(yaml.safe_load_all(FACTORIO_WORKLOAD.read_text()))
        cls.factorio_service = next(
            document
            for document in factorio_documents
            if document["kind"] == "Service"
        )
        cls.factorio_statefulset = next(
            document
            for document in factorio_documents
            if document["kind"] == "StatefulSet"
        )
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

    def test_ccr_migration_preserves_trunks_and_separates_housemate_ports(self) -> None:
        lan = self.router["routeros_lan"]
        housemate = self.router["routeros_housemate"]
        vlans = {row["id"]: row for row in lan["bridge_vlans"]}
        self.assertEqual(["ether2", "ether15"], lan["trunk_ports"])
        self.assertEqual(["ether3", "ether4"], housemate["ports"])
        self.assertEqual(70, housemate["vlan_id"])
        self.assertEqual("10.21.70.0/24", housemate["network"])
        self.assertEqual([lan["bridge"]], vlans[70]["tagged"])
        self.assertEqual(housemate["ports"], vlans[70]["untagged"])
        for vlan_id, row in vlans.items():
            self.assertFalse(set(row["tagged"]) & set(row["untagged"]))
            self.assertFalse({"ether1", "ether8"} & set(row["tagged"] + row["untagged"]))
            if vlan_id == 70:
                continue
            self.assertFalse(set(housemate["ports"]) & set(row["tagged"] + row["untagged"]))
            membership = row["untagged"] if vlan_id == 1 else row["tagged"]
            self.assertTrue(set(lan["trunk_ports"]) <= set(membership))
            # Keep the already connected legacy hybrid port exactly as observed.
            self.assertEqual(vlan_id != 40, "ether16" in membership)
        provider = self.router["routeros_provider_network"]
        self.assertEqual(
            [provider["bridge"], *lan["trunk_ports"]],
            vlans[provider["vlan_id"]]["tagged"],
        )

    def test_lan_port_tag_preserves_preflight_and_limits_writes(self) -> None:
        def selected_tasks(*arguments: str) -> str:
            return subprocess.run(
                ["ansible-playbook", "--list-tasks", "--limit", "core_router",
                 *arguments, "reconcile-routeros.yaml"],
                cwd=PLAYBOOK.parent, check=True, capture_output=True, text=True,
            ).stdout

        readonly = selected_tasks()
        selected = selected_tasks("--tags", "lan-ports")
        mutation = "Reconcile housemate routing and DHCP before enabling access ports"
        self.assertNotIn(mutation, readonly)
        self.assertIn("Read the CCR LAN ports and VLANs", readonly)
        self.assertIn(mutation, selected)
        self.assertLess(selected.index("Read the CCR LAN ports and VLANs"), selected.index(mutation))
        self.assertLess(selected.index(mutation), selected.index("Reconcile the housemate access ports"))
        self.assertIn("Prove every CCR bridge VLAN membership", selected)
        self.assertIn("Prove housemate routing and DHCP", selected)
        self.assertNotIn("Reconcile the external provider network\t", selected)
        self.assertNotIn("Reconcile Git-owned WAN port forwards\t", selected)

    def test_direct_ap_port_carries_only_management_and_wlan_vlans(self) -> None:
        lan = self.router["routeros_lan"]
        self.assertEqual(["ether5"], lan["ap_ports"])
        reserved = {"ether1", "ether8", "ether16", *lan["trunk_ports"],
                    *self.router["routeros_housemate"]["ports"]}
        self.assertFalse(reserved & set(lan["ap_ports"]))
        for row in lan["bridge_vlans"]:
            for port in lan["ap_ports"]:
                self.assertEqual(row["id"] in lan["ap_tagged_vlans"],
                                 port in row["tagged"])
                self.assertEqual(row["id"] == lan["ap_management_vlan"],
                                 port in row["untagged"])

    def test_ap_port_tag_does_not_change_housemate_or_wan_services(self) -> None:
        selected = subprocess.run(
            ["ansible-playbook", "--list-tasks", "--limit", "core_router",
             "--tags", "ap-ports", "reconcile-routeros.yaml"],
            cwd=PLAYBOOK.parent, check=True, capture_output=True, text=True,
        ).stdout
        self.assertLess(selected.index("Refuse an AP port already owned"),
                        selected.index("Reconcile the CCR bridge VLAN table"))
        self.assertLess(selected.index("Reconcile the CCR bridge VLAN table"),
                        selected.index("Reconcile the direct UniFi AP ports"))
        self.assertIn("Prove the direct UniFi AP ports", selected)
        for mutation in (
            "Reconcile housemate routing and DHCP before enabling access ports",
            "Reconcile the current and replacement Omada trunks",
            "Reconcile the housemate access ports",
            "Reconcile Git-owned WAN port forwards",
            "Reconcile Git-owned static DHCP leases",
        ):
            self.assertNotIn(mutation + "\t", selected)

    def test_second_ap_has_static_lease_and_its_own_controller_discovery(self) -> None:
        leases = self.router["routeros_static_leases"]
        ap = next(row for row in leases if row["mac_address"] == "A4:F8:FF:8E:53:5C")
        self.assertEqual("10.21.90.7", ap["address"])
        self.assertEqual("dhcp-management", ap["server"])
        option = next(row for row in self.router["routeros_dhcp_options"]
                      if row["name"] == ap["dhcp_option"])
        self.assertEqual(43, option["code"])
        encoded = bytes.fromhex(option["value"][2:])
        self.assertEqual(bytes([1, 4, 10, 21, 40, 127]), encoded)
        self.assertTrue(option["force"])
        existing = next(row for row in leases if row["address"] == "10.21.90.6")
        self.assertEqual("74:F9:2C:3C:99:F7", existing["mac_address"])
        self.assertNotIn("dhcp_option", existing)

    def test_client_vlan_access_is_mutual_and_confined_to_the_two_subnets(self) -> None:
        rules = self.router["routeros_lan_peer_rules"]
        self.assertEqual(4, len(rules))
        self.assertEqual(
            {
                ("vlan10-trusted", "10.21.10.0/24",
                 "vlan70-housemate", "10.21.70.0/24"),
                ("vlan70-housemate", "10.21.70.0/24",
                 "vlan10-trusted", "10.21.10.0/24"),
            },
            {
                (row["source_interface"], row["source_network"],
                 row["destination_interface"], row["destination_network"])
                for row in rules
            },
        )
        for source in ("vlan10-trusted", "vlan70-housemate"):
            self.assertEqual(
                {("tcp", "27040"), ("udp", "27031-27036")},
                {(row["protocol"], row["destination_port"])
                 for row in rules if row["source_interface"] == source},
            )
        selected = subprocess.run(
            ["ansible-playbook", "--list-tasks", "--limit", "core_router",
             "--tags", "lan-peers", "reconcile-routeros.yaml"],
            cwd=PLAYBOOK.parent, check=True, capture_output=True, text=True,
        ).stdout
        mutation = "Reconcile Steam access between trusted and housemate devices"
        preflight = "Require client VLAN interfaces and the final forward drop"
        self.assertLess(selected.index(preflight), selected.index(mutation))
        self.assertIn("Prove client VLAN peer rules and their ordering", selected)
        self.assertNotIn("Reconcile the CCR bridge VLAN table\t", selected)
        self.assertNotIn("Reconcile housemate internet access\t", selected)

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

    def test_unifi_dns_tag_is_scoped_and_all_conditions_are_strings(self) -> None:
        record = self.router["routeros_unifi_dns"]
        self.assertEqual("unifi", record["name"])
        self.assertEqual("10.21.40.127", record["address"])
        task_path = PLAYBOOK.parent / "tasks/reconcile-routeros-unifi-dns.yaml"
        tasks = yaml.safe_load(task_path.read_text())
        for task in tasks:
            for condition in task.get("ansible.builtin.assert", {}).get("that", []):
                self.assertIsInstance(condition, str)
            command = task.get("community.routeros.command")
            if command:
                self.assertEqual(1, command["retries"])
                self.assertIn("__infra_unifi_dns_ok__", command["wait_for"][0])
        selected = subprocess.run(
            ["ansible-playbook", "--list-tasks", "--limit", "core_router",
             "--tags", "unifi-dns", "reconcile-routeros.yaml"],
            cwd=PLAYBOOK.parent, check=True, capture_output=True, text=True,
        ).stdout
        self.assertLess(selected.index("Refuse a conflicting UniFi inform DNS record"),
                        selected.index("Reconcile the UniFi inform DNS record\t"))
        self.assertIn("Prove the UniFi inform DNS record and resolution", selected)
        for mutation in (
            "Reconcile the CCR bridge VLAN table", "Reconcile the direct UniFi AP ports",
            "Reconcile Git-owned static DHCP leases", "Reconcile Git-owned WAN port forwards",
        ):
            self.assertNotIn(mutation + "\t", selected)

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

    def test_mail_backend_peer_is_isolated_and_gateway_allows_trusted_lan_and_vpn(self) -> None:
        vpn = json.loads((ROOT / "deployments/homelab/cloud/mail-admin-vpn.json").read_text())
        peers = self.router["routeros_wireguard"]["peers"]
        peer = next(peer for peer in peers if peer["name"] == "mail-aws")
        self.assertTrue(peer["isolated_backend"])
        self.assertEqual(vpn["address"], peer["allowed_address"])
        self.assertEqual(vpn["publicKey"], peer["public_key"])
        rule = next(rule for rule in self.router["routeros_access_rules"]
                    if rule["comment"] == "infra: services gateway to mail administration")
        self.assertEqual(rule["destination"], vpn["address"])
        self.assertEqual(rule["source_address"], vpn["gatewaySource"])
        self.assertEqual(rule["destination_port"], "8080")
        resources = list(yaml.safe_load_all((ROOT / "deployments/homelab/cloud/services/20-platform-gateway/mail-admin.yaml").read_text()))
        policy = next(obj for obj in resources if obj["kind"] == "SecurityPolicy")["spec"]["authorization"]
        self.assertEqual(policy["defaultAction"], "Deny")
        self.assertEqual(policy["rules"], [{"action": "Allow", "principal": {"clientCIDRs": ["10.21.10.0/24", "10.21.91.0/24"]}}])
        endpoint = next(obj for obj in resources if obj["kind"] == "EndpointSlice")
        self.assertEqual(endpoint["endpoints"][0]["addresses"], [vpn["backendAddress"]])
        wireguard_tasks = (ROOT / "components/cloud/network-automation/tasks/reconcile-routeros-wireguard.yaml").read_text()
        self.assertIn("connection-state=new", wireguard_tasks)
        self.assertIn("place-before=0", wireguard_tasks)
        self.assertIn("selectattr('isolated_backend')", wireguard_tasks)

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

    def test_valheim_forwarding_matches_service_ports_and_address(self) -> None:
        documents = list(yaml.safe_load_all(
            (ROOT / "deployments/homelab/cloud/services/31-valheim/valheim.yaml").read_text()
        ))
        service = next(item for item in documents if item["kind"] == "Service")
        self.assertEqual("Cluster", service["spec"]["externalTrafficPolicy"])
        ports = {item["port"] for item in service["spec"]["ports"]}
        self.assertEqual({2456, 2457}, ports)
        self.assertTrue(all(item["protocol"] == "UDP" for item in service["spec"]["ports"]))
        for section, comment in (
            ("routeros_port_forwards", "infra: Valheim"),
            ("routeros_nat_reflections", "infra: Valheim LAN reflection"),
        ):
            rows = [row for row in self.router[section] if row["comment"] == comment]
            self.assertEqual(1, len(rows))
            row = rows[0]
            self.assertEqual(service["spec"]["loadBalancerIP"], row["to_address"])
            self.assertEqual("udp", row["protocol"])
            self.assertEqual("2456-2457", row["destination_port"])
            self.assertEqual(row["destination_port"], row["to_port"])

    def test_factorio_has_port_preserving_wan_and_lan_reflection(self) -> None:
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
        self.assertEqual(
            [
                {
                    "comment": "infra: Factorio Space Age LAN reflection",
                    "source_interface_list": "INFRA-LAN",
                    "destination_address_type": "local",
                    "excluded_destination_address_list": "INFRA-LAN-NAT",
                    "protocol": "udp",
                    "destination_port": "34197",
                    "to_address": "10.21.40.123",
                    "to_port": "34197",
                }
            ],
            [item for item in self.router["routeros_nat_reflections"]
             if item["comment"] == "infra: Factorio Space Age LAN reflection"],
        )
        self.assertEqual(
            [
                {
                    "comment": "infra: Factorio Space Age egress port",
                    "source_interface": "vlan40-external",
                    "out_interface_list": "INFRA-WAN",
                    "protocol": "udp",
                    "destination_port": "34197",
                    "to_port": "34197",
                }
            ],
            self.router["routeros_source_port_pins"],
        )
        self.assertEqual("10.21.40.123", self.factorio_service["spec"]["loadBalancerIP"])
        self.assertEqual(
            "Cluster", self.factorio_service["spec"]["externalTrafficPolicy"]
        )
        self.assertNotIn("annotations", self.factorio_service["metadata"])
        save_integrity = next(
            container
            for container in self.factorio_statefulset["spec"]["template"]["spec"][
                "containers"
            ]
            if container["name"] == "save-integrity"
        )
        self.assertNotIn("readinessProbe", save_integrity)
        self.assertEqual(
            {
                "name": "POD_NAMESPACE",
                "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}},
            },
            save_integrity["env"][0],
        )
        self.assertIn("wan-port-forwards", self.playbook)
        self.assertIn("connection-nat-state=dstnat", self.playbook)
        self.assertIn("Reconcile Git-owned WAN forward filters", self.playbook)
        self.assertIn("Reconcile Git-owned NAT reflections", self.playbook)
        self.assertIn(
            "Reconcile Git-owned NAT-reflection forward filters", self.playbook
        )
        self.assertIn("dst-address-type={{ item.destination_address_type }}", self.playbook)
        self.assertIn(
            "dst-address-list=!{{ item.excluded_destination_address_list }}",
            self.playbook,
        )
        self.assertRegex(
            self.playbook,
            r"/interface list member find where\s+"
            r'list="{{ routeros_provider_network.lan_interface_list }}" and\s+'
            r'interface="{{ routeros_provider_network.interface }}"',
        )
        for required_setting in (
            "public: true",
            "lan: true",
            "username: $username",
            "token: $token",
            "game_password: $game_password",
            "require_user_verification: true",
        ):
            self.assertIn(required_setting, self.factorio_render_config)
        self.assertNotIn(
            "require_user_verification: false", self.factorio_render_config
        )
        selected = subprocess.run(
            [
                "ansible-playbook",
                "--list-tasks",
                "--tags",
                "wan-port-forwards",
                "reconcile-routeros.yaml",
            ],
            cwd=PLAYBOOK.parent,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("Reconcile Git-owned WAN port forwards", selected)
        self.assertIn("Reconcile Git-owned WAN forward filters", selected)
        self.assertIn("Reconcile Git-owned source-port pins", selected)
        self.assertIn("Reconcile Git-owned NAT reflections", selected)
        self.assertIn("Reconcile Git-owned NAT-reflection forward filters", selected)

    def test_external_provider_vlan_is_reconciled_end_to_end(self) -> None:
        self.assertEqual(
            [20, 30, 31, 32, 33, 40, 50],
            list(self.host_defaults["cloud_vlan_mtu"]),
        )
        self.assertNotIn("cloud_provider_vlans", self.host_defaults)
        self.assertEqual(
            [20, 30, 31, 32, 33, 40, 50],
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
        self.assertEqual("INFRA-LAN", provider["lan_interface_list"])
        self.assertEqual("infra: PPPoE masquerade", provider["wan_masquerade_comment"])
        self.assertEqual(
            [
                (
                    "infra: IOT to Home Assistant HTTPS",
                    "infra-forward",
                    "vlan50-iot",
                    "10.21.40.122",
                    "tcp",
                    "443",
                ),
                (
                    "infra: SERVERS to Forgejo registry",
                    "infra-forward",
                    "vlan20-servers",
                    "10.21.40.122",
                    "tcp",
                    "443",
                ),
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
                (
                    "infra: CLOUD-EXTERNAL to OIDC",
                    "infra-forward",
                    "vlan40-external",
                    "10.21.20.131",
                    "tcp",
                    "443",
                ),
                (
                    "infra: services gateway to mail administration",
                    "infra-forward",
                    "vlan40-external",
                    "10.21.91.3/32",
                    "tcp",
                    "8080",
                ),
                (
                    "infra: UniFi AP inform", "infra-forward", "vlan90-mgmt",
                    "10.21.40.127", "tcp", "8080",
                ),
                (
                    "infra: UniFi AP STUN", "infra-forward", "vlan90-mgmt",
                    "10.21.40.127", "udp", "3478",
                ),
                (
                    "infra: UniFi trusted bootstrap", "infra-forward", "vlan10-trusted",
                    "10.21.40.127", "tcp", "22,11443",
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
