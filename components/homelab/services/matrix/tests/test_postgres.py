import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import postgres

class PostgresAccess(unittest.TestCase):
    def test_application_rules_are_added_once_and_operator_rules_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pg_hba.conf"
            custom = "host audit audit 10.21.10.0/24 scram-sha-256"
            path.write_text("local all all trust\nhost all all 127.0.0.1/32 scram-sha-256\n" + custom + "\n")
            postgres.ensure_hba(path)
            first = path.read_text()
            self.assertTrue(first.startswith("local all all trust\nhost all all 127.0.0.1/32 scram-sha-256\n" + custom + "\n"))
            for name in ("synapse", "mas"):
                self.assertIn(f"host {name} {name} 10.100.0.0/16 scram-sha-256\n", first)
            postgres.ensure_hba(path)
            self.assertEqual(path.read_text(), first)
