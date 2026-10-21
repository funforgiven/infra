from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))
from validate import require_snapshot_support


class SnapshotDependencies(unittest.TestCase):
    def objects(self):
        result = {("VolumeSnapshotClass", "", "ceph-block-snapshot"): {"kind": "VolumeSnapshotClass"},
                  ("Deployment", "kube-system", "snapshot-controller"): {"kind": "Deployment"},
                  ("HelmRelease", "rook-ceph", "ceph-csi-drivers"): {"kind": "HelmRelease", "spec": {"values": {"drivers": {"rbd": {"snapshotPolicy": "volumeSnapshot"}}}}}}
        for kind in ["volumesnapshots", "volumesnapshotcontents", "volumesnapshotclasses"]:
            name = kind + ".snapshot.storage.k8s.io"
            result[("CustomResourceDefinition", "", name)] = {"kind": "CustomResourceDefinition", "metadata": {"name": name}}
        return result

    def test_sidecar_and_class_do_not_replace_controller_or_crds(self):
        objects = self.objects()
        require_snapshot_support(objects)
        for missing in [("Deployment", "kube-system", "snapshot-controller"),
                        ("CustomResourceDefinition", "", "volumesnapshots.snapshot.storage.k8s.io")]:
            with self.subTest(missing=missing):
                incomplete = dict(objects)
                del incomplete[missing]
                with self.assertRaises(ValueError): require_snapshot_support(incomplete)

    def test_disabled_rbd_snapshots_are_rejected(self):
        objects = self.objects()
        objects[("HelmRelease", "rook-ceph", "ceph-csi-drivers")]["spec"]["values"]["drivers"]["rbd"]["snapshotPolicy"] = "none"
        with self.assertRaises(ValueError): require_snapshot_support(objects)


if __name__ == "__main__": unittest.main()
