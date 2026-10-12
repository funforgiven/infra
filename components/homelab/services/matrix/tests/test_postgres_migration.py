import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import postgres

class PostgresMigration(unittest.TestCase):
    def test_restored_rules_move_without_changing_operator_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pg_hba.conf"
            custom = "host audit audit 10.21.10.0/24 scram-sha-256"
            path.write_text("local all all trust\nhost synapse synapse 172.16.0.0/12 scram-sha-256\nhost mas mas 172.16.0.0/12 scram-sha-256\n" + custom + "\n")
            postgres.migrate_hba(path)
            first = path.read_bytes()
            self.assertNotIn(b"172.16.0.0/12", first)
            self.assertIn(custom.encode(), first)
            for name in ("synapse", "mas"):
                self.assertIn(f"host {name} {name} 10.100.0.0/16 scram-sha-256".encode(), first)
            postgres.migrate_hba(path)
            self.assertEqual(path.read_bytes(), first)

    def test_fresh_database_keeps_local_authentication(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pg_hba.conf"
            path.write_text("local all all trust\nhost all all 127.0.0.1/32 scram-sha-256\n")
            postgres.migrate_hba(path)
            self.assertTrue(path.read_text().startswith("local all all trust\nhost all all 127.0.0.1/32 scram-sha-256\n"))
