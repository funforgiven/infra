import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate import require_bounded_postgres_wal


class PostgresStorageTests(unittest.TestCase):
    def cluster(self, limit="2GB", disk="16Gi", instances=3):
        parameters = {} if limit is None else {"max_slot_wal_keep_size": limit}
        return {"cluster": {
            "apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster",
            "metadata": {"name": "database"},
            "spec": {"instances": instances, "storage": {"size": disk},
                     "postgresql": {"parameters": parameters}},
        }}

    def test_rejects_unbounded_replica_retention(self):
        for limit in (None, "-1", -1, "0", "unlimited"):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "finite WAL budget"):
                require_bounded_postgres_wal(self.cluster(limit))

    def test_rejects_wal_budget_that_consumes_data_headroom(self):
        with self.assertRaisesRegex(ValueError, "exceeds half"):
            require_bounded_postgres_wal(self.cluster("16GB", "16Gi"))

    def test_accepts_bounded_production_budgets(self):
        for limit, disk in (("2GB", "16Gi"), ("16GB", "32Gi"), ("2048MB", "16Gi")):
            with self.subTest(limit=limit, disk=disk):
                require_bounded_postgres_wal(self.cluster(limit, disk))

    def test_single_instance_restore_needs_no_replica_budget(self):
        require_bounded_postgres_wal(self.cluster(None, instances=1))

    def test_separate_wal_volume_limits_the_budget(self):
        objects = self.cluster("2GB", "32Gi")
        objects["cluster"]["spec"]["walStorage"] = {"size": "1Gi"}
        with self.assertRaisesRegex(ValueError, "exceeds half"):
            require_bounded_postgres_wal(objects)


if __name__ == "__main__":
    unittest.main()
