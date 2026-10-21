import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import require_recovery_hold


def stage(name, held=False, suspend=False):
    labels = {"homelab.fahrican.com/recovery": "hold"} if held else {}
    spec = {"suspend": True} if suspend else {}
    return {"kind": "Kustomization", "metadata": {"name": name, "labels": labels}, "spec": spec}


class RecoveryHold(unittest.TestCase):
    def test_labelled_stages_must_be_suspended(self):
        waves = [stage("ceph", True), stage("matrix", True), stage("gateway")]
        require_recovery_hold(waves, [stage("ceph", True, True), stage("matrix", True, True), stage("gateway")])
        with self.assertRaisesRegex(ValueError, "prematurely"):
            require_recovery_hold(waves, [stage("ceph", True, True), stage("matrix", True), stage("gateway")])

    def test_ceph_cannot_lose_its_label(self):
        with self.assertRaisesRegex(ValueError, "Ceph"):
            require_recovery_hold([stage("ceph"), stage("matrix", True)], [stage("matrix", True, True)])

    def test_unlabelled_suspension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "without the hold label"):
            require_recovery_hold([stage("ceph", True), stage("gateway")],
                                  [stage("ceph", True, True), stage("gateway", suspend=True)])


if __name__ == "__main__":
    unittest.main()
