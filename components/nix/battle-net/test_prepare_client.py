import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_client as client


class ClientSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.prefix = Path(temporary.name)
        self.path = self.prefix / "drive_c/users/steamuser/AppData/Roaming/Battle.net/Battle.net.config"
        self.path.parent.mkdir(parents=True)
        self.original = {
            "Client": {"HardwareAcceleration": "true", "Language": "enUS"},
            "Authentication": {"preserve": "private-fixture"},
            "Games": {"WoW": {"InstallPath": "C:/Games/World of Warcraft"}},
        }
        self.path.write_text(json.dumps(self.original))
        self.settings = {"HardwareAcceleration": "false"}

    def test_only_declared_setting_changes_and_output_is_private(self):
        with patch.object(client, "client_running", return_value=False):
            self.assertTrue(client.prepare_client(self.prefix, self.settings))
        expected = self.original | {"Client": self.original["Client"] | self.settings}
        self.assertEqual(json.loads(self.path.read_bytes()), expected)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_repeated_launch_does_not_rewrite_private_state(self):
        with patch.object(client, "client_running", return_value=False):
            client.prepare_client(self.prefix, self.settings)
        original = self.path.read_bytes()
        modified = self.path.stat().st_mtime_ns
        with patch.object(client, "client_running", return_value=True):
            self.assertFalse(client.prepare_client(self.prefix, self.settings))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_mtime_ns, modified)

    def test_active_launcher_prevents_overwriting_runtime_settings(self):
        original = self.path.read_bytes()
        with patch.object(client, "client_running", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Close Battle.net"):
                client.prepare_client(self.prefix, self.settings)
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_config_is_seeded_for_first_install(self):
        self.path.unlink()
        with patch.object(client, "client_running", return_value=False):
            client.prepare_client(self.prefix, self.settings)
        self.assertEqual(json.loads(self.path.read_bytes()), {"Client": self.settings})

    def test_invalid_json_is_preserved(self):
        self.path.write_text('{"incomplete":')
        with self.assertRaises(ValueError):
            client.prepare_client(self.prefix, self.settings)
        self.assertEqual(self.path.read_text(), '{"incomplete":')

    def test_running_client_is_detected_through_protons_prefix_alias(self):
        (self.prefix / "pfx").symlink_to(".")
        proc = self.prefix / "proc"
        process = proc / "123"
        process.mkdir(parents=True)
        (process / "cmdline").write_bytes(b"C:\\Battle.net\\Battle.net.exe\0")
        (process / "environ").write_bytes(f"WINEPREFIX={self.prefix}/pfx/\0".encode())
        self.assertTrue(client.client_running(self.prefix, proc))

    def test_compatibility_data_path_distinguishes_prefixes(self):
        proc = self.prefix / "proc"
        process = proc / "123"
        process.mkdir(parents=True)
        (process / "cmdline").write_bytes(b"C:\\Battle.net\\BlizzardBrowser.exe\0")
        environment = f"WINEPREFIX={self.prefix}/separate-pfx\0STEAM_COMPAT_DATA_PATH={self.prefix}/\0"
        (process / "environ").write_bytes(environment.encode())
        self.assertTrue(client.client_running(self.prefix, proc))
        self.assertFalse(client.client_running(self.prefix / "another-prefix", proc))
        (process / "cmdline").write_bytes(b"C:\\World of Warcraft\\Wow.exe\0")
        self.assertFalse(client.client_running(self.prefix, proc))


if __name__ == "__main__":
    unittest.main()
