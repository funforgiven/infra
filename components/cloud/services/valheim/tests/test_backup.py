"""Exercise backup failure recovery and the complete 1.0 world archive."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / "deployments/homelab/cloud/services/31-valheim"


class ValheimBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        self.world = self.data / "worlds/worlds_local/Fahrican"
        self.world.mkdir(parents=True)
        (self.world / "_main.1.ok").touch()
        (self.world / "chunk.1").write_bytes(b"committed world data")
        (self.data / "worlds/adminlist.txt").write_text("Steam_123\n")
        (self.data / "backups").mkdir()
        self.bin = self.data / "bin"
        self.bin.mkdir()
        self.executable("supervisorctl", """#!/bin/bash
set -eu
echo "$3" >> "$VALHEIM_DATA_DIR/actions"
if [[ "$3" == stop && "${FAIL_STOP:-0}" == 1 ]]; then exit 1; fi
if [[ "$3" == start && "${FAIL_START:-0}" == 1 ]]; then exit 1; fi
""")
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            POD_NAMESPACE="games",
            WORLD_NAME="Fahrican",
            VALHEIM_DATA_DIR=str(self.data),
            VALHEIM_BACKUP_LOCK=str(self.data / "lock"),
        )

    def executable(self, name, contents):
        path = self.bin / name
        path.write_text(contents.replace("#!/bin/bash", f"#!{shutil.which('bash')}"))
        path.chmod(0o755)

    def run_script(self, name):
        return subprocess.run(
            ["bash", str(SCRIPTS / name)], env=self.env,
            capture_output=True, text=True,
        )

    def actions(self):
        return (self.data / "actions").read_text().splitlines()

    def test_complete_archive_survives_changes_to_live_world(self):
        backup = self.run_script("backup.sh")
        self.assertEqual(0, backup.returncode, backup.stderr)
        self.assertEqual(["stop", "start"], self.actions())
        self.assertFalse((self.data / "lock").exists())
        (self.world / "chunk.1").write_bytes(b"later world data")
        verified = self.run_script("verify-backup.sh")
        self.assertEqual(0, verified.returncode, verified.stderr)
        with tarfile.open(self.data / "backups/recovery.tar") as archive:
            self.assertEqual(
                b"committed world data",
                archive.extractfile("./worlds_local/Fahrican/chunk.1").read(),
            )
            self.assertEqual(b"Steam_123\n", archive.extractfile("./adminlist.txt").read())

    def test_copy_failure_keeps_previous_archive_and_restarts_game(self):
        self.assertEqual(0, self.run_script("backup.sh").returncode)
        previous = (self.data / "backups/recovery.tar").read_bytes()
        self.executable("tar", "#!/bin/bash\nexit 2\n")
        self.assertNotEqual(0, self.run_script("backup.sh").returncode)
        self.assertEqual(["stop", "start", "stop", "start"], self.actions())
        self.assertEqual(previous, (self.data / "backups/recovery.tar").read_bytes())
        self.assertFalse((self.data / "lock").exists())

    def test_stop_failure_cannot_publish_a_backup(self):
        self.env["FAIL_STOP"] = "1"
        self.assertNotEqual(0, self.run_script("backup.sh").returncode)
        self.assertEqual(["stop", "start"], self.actions())
        self.assertFalse((self.data / "backups/recovery.tar").exists())

    def test_restart_failure_fails_backup_hook(self):
        self.env["FAIL_START"] = "1"
        self.assertNotEqual(0, self.run_script("backup.sh").returncode)
        self.assertFalse((self.data / "lock").exists())

    def test_uncommitted_world_is_rejected_and_game_resumes(self):
        (self.world / "_main.1.ok").unlink()
        self.assertNotEqual(0, self.run_script("backup.sh").returncode)
        self.assertEqual(["stop", "start"], self.actions())
        self.assertFalse((self.data / "backups/recovery.tar").exists())

    def test_corrupted_archive_fails_restore_verification(self):
        self.assertEqual(0, self.run_script("backup.sh").returncode)
        with (self.data / "backups/recovery.tar").open("ab") as archive:
            archive.write(b"corruption")
        self.assertNotEqual(0, self.run_script("verify-backup.sh").returncode)

    def test_restore_namespace_cannot_run_production_backup(self):
        self.env["POD_NAMESPACE"] = "games-restore"
        self.assertNotEqual(0, self.run_script("backup.sh").returncode)
        self.assertFalse((self.data / "actions").exists())
