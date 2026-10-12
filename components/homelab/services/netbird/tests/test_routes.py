import copy
import importlib.util
import unittest
from pathlib import Path

import yaml

SOURCE = Path(__file__).resolve().parents[1] / "render_routes.py"
SPEC = importlib.util.spec_from_file_location("netbird_routes", SOURCE)
routes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routes)


class RouteBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.documents = [
            doc for source in routes.SOURCES
            for doc in yaml.safe_load_all((routes.SERVICES / source).read_text()) if doc
        ]
        self.rendered = routes.transform(self.documents)

    def test_application_rules_survive_without_broadening_lan_access(self):
        original = copy.deepcopy(self.documents)
        by_name = {(doc["kind"], doc["metadata"]["namespace"], doc["metadata"]["name"]): doc for doc in self.documents}
        for document in self.rendered:
            if document["kind"] != "HTTPRoute":
                continue
            meta = document["metadata"]
            source = by_name[("HTTPRoute", meta["namespace"], meta["name"].removeprefix("netbird-"))]
            self.assertEqual(document["spec"]["rules"], source["spec"]["rules"])
            self.assertEqual(document["spec"]["hostnames"], source["spec"]["hostnames"])
            self.assertEqual(document["spec"]["parentRefs"][0]["name"], "netbird-services")
        self.assertEqual(self.documents, original)

    def test_wallos_database_remains_denied(self):
        policy = next(doc for doc in self.rendered if doc["metadata"]["name"] == "netbird-wallos-database-deny")
        self.assertEqual(policy["spec"]["authorization"], {"defaultAction": "Deny"})

    def test_new_authorization_conditions_fail_closed(self):
        policy = next(doc for doc in self.documents if doc["metadata"]["name"] == "mail-admin-vpn")
        policy["spec"]["authorization"]["rules"][0]["principal"]["jwt"] = {"provider": "example"}
        with self.assertRaisesRegex(ValueError, "explicit NetBird review"):
            routes.transform(self.documents)

    def test_unapproved_hostname_requires_review(self):
        route = next(doc for doc in self.documents if doc["kind"] == "HTTPRoute")
        route["spec"]["hostnames"].append("unapproved.fahrican.com")
        with self.assertRaisesRegex(ValueError, "Unexpected hostname"):
            routes.transform(self.documents)

    def test_generated_routes_are_current(self):
        self.assertEqual(routes.TARGET.read_text(), routes.render())

    def test_public_endpoint_does_not_publish_administration(self):
        documents = yaml.safe_load_all((routes.SERVICES / "apps/netbird/server/routes.yaml").read_text())
        public = next(doc for doc in documents if doc["metadata"]["name"] == "netbird-public")
        for path in ("/api/setup", "/api/users", "/api/policies", "/", "/dashboard"):
            for rule in public["spec"]["rules"]:
                for match in rule["matches"]:
                    pattern = match["path"]
                    matched = path == pattern["value"] or (
                        pattern["type"] == "PathPrefix"
                        and path.startswith(pattern["value"].rstrip("/") + "/")
                    )
                    self.assertFalse(matched, path)


class NetworkBoundaryTests(unittest.TestCase):
    def test_server_and_router_default_deny_and_identity_gateway_access(self):
        policies = policies_from("server/network-policy.yaml")
        self.assertTrue(any(d["spec"].get("podSelector") == {} and
                            "Egress" in d["spec"]["policyTypes"] and
                            not d["spec"].get("egress") for d in policies))
        router = next(d for d in policies_from("access/routing.yaml") if d["metadata"]["name"] == "routing-peers")
        self.assertEqual(router["spec"]["podSelector"]["matchLabels"], {"access.fahrican.com/netbird-router": "services"})
        self.assertIn("Egress", router["spec"]["policyTypes"])
        self.assertFalse(any(rule == {} for rule in router["spec"]["egress"]))
        server = next(d for d in policies_from("server/network-policy.yaml") if d["metadata"]["name"] == "server")
        gateway = [rule for rule in server["spec"]["egress"] if any(
            peer.get("podSelector", {}).get("matchLabels", {}).get("gateway.envoyproxy.io/owning-gateway-name") == "management"
            for peer in rule.get("to", []))]
        self.assertEqual(len(gateway), 1)
        self.assertEqual(gateway[0]["ports"], [{"protocol": "TCP", "port": 10443}])


def policies_from(relative):
    path = routes.SERVICES / "apps/netbird" / relative
    return [d for d in yaml.safe_load_all(path.read_text()) if d and d["kind"] == "NetworkPolicy"]


if __name__ == "__main__":
    unittest.main()
