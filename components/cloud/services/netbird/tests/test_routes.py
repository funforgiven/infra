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
        documents = yaml.safe_load_all((routes.SERVICES / "48-netbird/server/routes.yaml").read_text())
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
    def test_generated_calico_enforces_before_the_global_allow(self):
        spec = importlib.util.spec_from_file_location("netbird_network", SOURCE.with_name("render_network.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.render(check=True)
        for directory in ("server", "access"):
            policy = yaml.safe_load((module.DEPLOYMENT / directory / "calico.generated.yaml").read_text())
            self.assertLess(policy["spec"]["order"], 20)
            self.assertEqual(policy["spec"]["egress"][-1], {"action": "Deny"})
            self.assertEqual(policy["spec"]["types"], ["Egress"])
            self.assertIn("netbird", policy["spec"]["namespaceSelector"])


if __name__ == "__main__":
    unittest.main()
