import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import require_inventory_copies

INVENTORY = {
    "cluster": {"apiVip": "10.0.0.128", "apiName": "cluster-api.mgmt.cloud.fahrican.com"},
    "hosts": {"a": {"management": "10.0.0.10", "ceph": "10.0.1.10"}},
}


def objects(vip="10.0.0.128", record="10.0.0.10", mon="10.0.1.10"):
    zone = f"a.mgmt IN A {record}\ncluster-api.mgmt IN A 10.0.0.128\n"
    return {
        ("ConfigMap", "kube-system", "cilium-values"): {"kind": "ConfigMap", "data": {"values.yaml": f"k8sServiceHost: {vip}\n"}},
        ("ConfigMap", "network-services", "internal-coredns"): {"kind": "ConfigMap", "data": {"cloud.fahrican.com.zone": zone}},
        ("Node", "", "a"): {"kind": "Node", "metadata": {"name": "a", "annotations": {"network.rook.io/mon-ip": mon}}},
    }


class InventoryCopies(unittest.TestCase):
    def test_matching_copies_pass(self):
        require_inventory_copies(INVENTORY, objects())

    def test_drift_is_rejected(self):
        for drift, message in [({"vip": "10.0.0.1"}, "Cilium"), ({"record": "10.0.0.9"}, "DNS"), ({"mon": "10.0.1.9"}, "Ceph")]:
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                require_inventory_copies(copy.deepcopy(INVENTORY), objects(**drift))


if __name__ == "__main__":
    unittest.main()
