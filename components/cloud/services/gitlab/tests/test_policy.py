"""Ensure CI's ordered Calico policy cannot fall through to provider-wide Allow."""

import ipaddress
from pathlib import Path
import unittest

import yaml


class PolicyTests(unittest.TestCase):
    def setUp(self):
        repo = Path(__file__).resolve().parents[5]
        path = repo / "deployments/homelab/cloud/gitlab/40-runners/network-policy.yaml"
        self.policies = list(yaml.safe_load_all(path.read_text()))
        self.ci = next(item["spec"] for item in self.policies if item["metadata"]["namespace"] == "gitlab-ci")

    def external_action(self, address, port):
        address = ipaddress.ip_address(address)
        for rule in self.ci["egress"]:
            dest = rule.get("destination", {})
            if "selector" in dest or "namespaceSelector" in dest:
                continue  # These external destinations have no workload identity.
            if rule.get("protocol", "TCP") != "TCP":
                continue
            if "ports" in dest and port not in dest["ports"]:
                continue
            if "nets" in dest and not any(address in ipaddress.ip_network(net) for net in dest["nets"]):
                continue
            if any(address in ipaddress.ip_network(net) for net in dest.get("notNets", [])):
                continue
            return rule["action"]
        return "ProviderAllow"  # CAPI's order-20 global policy is permissive.

    def test_namespace_policies_terminate_before_provider_allow(self):
        for policy in self.policies:
            self.assertEqual(policy["apiVersion"], "projectcalico.org/v3")
            self.assertGreater(policy["spec"]["order"], 10)  # Preserve metadata Deny.
            self.assertLess(policy["spec"]["order"], 20)
            self.assertEqual(policy["spec"]["egress"][-1], {"action": "Deny"})
            self.assertEqual(policy["spec"]["ingress"][-1], {"action": "Deny"})

    def test_private_services_and_unapproved_public_ports_are_denied(self):
        for address, port in [("192.168.82.10", 5432), ("192.168.82.10", 6379),
                              ("192.168.82.10", 8075), ("169.254.169.254", 80),
                              ("10.21.20.130", 443), ("10.21.20.131", 443),
                              ("10.21.40.245", 6443), ("8.8.8.8", 22)]:
            self.assertEqual(self.external_action(address, port), "Deny", (address, port))

    def test_gitlab_and_public_downloads_are_allowed(self):
        for address, port in [("10.21.40.127", 443), ("10.21.40.127", 2222),
                              ("1.1.1.1", 443), ("8.8.8.8", 80)]:
            self.assertEqual(self.external_action(address, port), "Allow", (address, port))


if __name__ == "__main__":
    unittest.main()
