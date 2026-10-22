import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import require_isolated_restores, require_pinned

RELEASE = {"metadata": {"namespace": "a", "name": "b"}}


def git(commit):
    return {"kind": "GitRepository", "spec": {"url": "https://github.com/o/r.git", "ref": {"commit": commit} if commit else {"tag": "v1"}}}


class ChartPins(unittest.TestCase):
    pin = {"url": "https://codeload.github.com/o/r/tar.gz/abc", "ref": "abc"}

    def test_matching_commit_passes(self):
        require_pinned(RELEASE, git("abc"), {"chart": "./c"}, self.pin)

    def test_bump_without_pin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "differs from pins.json"):
            require_pinned(RELEASE, git("def"), {"chart": "./c"}, self.pin)

    def test_mutable_or_unpinned_sources_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "digest or commit"):
            require_pinned(RELEASE, git(None), {"chart": "./c"}, self.pin)
        with self.assertRaisesRegex(ValueError, "no entry"):
            require_pinned(RELEASE, git("abc"), {"chart": "./c"}, None)

    def test_helm_repository_version_must_match(self):
        source = {"kind": "HelmRepository", "spec": {"url": "https://example.org"}}
        pin = {"url": "https://example.org/c-1.0.0.tgz", "ref": "1.0.0"}
        require_pinned(RELEASE, source, {"chart": "c", "version": "1.0.0"}, pin)
        with self.assertRaises(ValueError):
            require_pinned(RELEASE, source, {"chart": "c", "version": "1.0.1"}, pin)


class RestoreIsolation(unittest.TestCase):
    def objects(self, spec):
        return {("Namespace", "", "x-restore"): {},
                ("CiliumNetworkPolicy", "x-restore", "p"): {"spec": spec}}

    def test_deny_all_policies_pass(self):
        require_isolated_restores(self.objects({"endpointSelector": {}, "ingressDeny": [{}], "egressDeny": [{}]}))
        require_isolated_restores(self.objects({"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}))

    def test_partial_isolation_is_rejected(self):
        for spec in ({"endpointSelector": {}, "ingressDeny": [{}]},
                     {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "egress": [{}]}):
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, "deny-all"):
                require_isolated_restores(self.objects(spec))


if __name__ == "__main__":
    unittest.main()
