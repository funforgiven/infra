"""Never publish a completion marker for failed or skipped native backup data."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


class BackupTests(unittest.TestCase):
    def run_backup(self, message, exit_code):
        repo = Path(__file__).resolve().parents[5]
        release = list(yaml.safe_load_all((repo / "deployments/homelab/cloud/gitlab/30-application/gitlab.yaml").read_text()))[1]
        patch = yaml.safe_load(release["spec"]["postRenderers"][0]["kustomize"]["patches"][0]["patch"])
        command = next(op["value"][-1] for op in patch
                       if op["path"] == "/spec/jobTemplate/spec/template/spec/containers/0/args")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "id").write_text("1788634258_2026_09_05_19.3.1-ee\n")
            (work / "secrets.json").write_text("{}")
            for name, script in {
                "s3cmd": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$BACKUP_TEST_UPLOADS"\n',
                "backup-utility": '#!/bin/sh\nprintf "%s\\n" "$BACKUP_TEST_MESSAGE"\nexit "$BACKUP_TEST_EXIT"\n',
            }.items():
                path = work / name
                path.write_text(script)
                path.chmod(0o700)
            # Replace only mounted paths and credential installation. Exercise
            # the actual shell control flow with harmless storage/tool fixtures.
            command = command.replace('cp /etc/gitlab/.s3cfg "$HOME/.s3cfg"', ':')
            command = command.replace("/recovery/", directory + "/")
            command = command.replace("/srv/gitlab/tmp/", directory + "/")
            result = subprocess.run(["bash", "-ec", command], capture_output=True,
                                    env={**os.environ, "PATH": directory + ":" + os.environ["PATH"],
                                         "BACKUP_TEST_MESSAGE": message, "BACKUP_TEST_EXIT": str(exit_code),
                                         "BACKUP_TEST_UPLOADS": str(work / "uploads")})
            uploads = (work / "uploads").read_text()
            return result.returncode, uploads

    def test_complete_backup_publishes_secrets_before_marker(self):
        status, uploads = self.run_backup("Packing up backup tar", 0)
        self.assertEqual(status, 0)
        self.assertLess(uploads.index("_secrets.json"), uploads.index("_complete"))

    def test_native_success_with_skipped_bucket_is_not_complete(self):
        status, uploads = self.run_backup("Unable to check existence of bucket gitlab-lfs. Skipping backup of lfs ...", 0)
        self.assertNotEqual(status, 0)
        self.assertNotIn("_complete", uploads)

    def test_native_failure_never_publishes_marker(self):
        status, uploads = self.run_backup("Database backup failed", 1)
        self.assertNotEqual(status, 0)
        self.assertNotIn("_complete", uploads)


if __name__ == "__main__":
    unittest.main()
