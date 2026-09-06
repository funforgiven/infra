import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location(
    "verify_atollion", ROOT / "deployments/homelab/cloud/services/46-forge/verify_atollion.py")
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


class AtollionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backup = self.root / "backups"
        self.evidence = self.backup / "atollion-migration"
        self.target = self.root / "restore"
        (self.evidence / "checkpoint").mkdir(parents=True)
        (self.target / "data/data").mkdir(parents=True)
        (self.target / "data/git/repositories/funforgiven/atollion.git").mkdir(parents=True)
        self.database = self.target / "data/data/forgejo.db"
        self.cutover = "f" * 40
        created = "2026-09-06T13:00:00Z"
        merged = "2026-09-06T14:00:00Z"
        self.issues = [{"number": number, "created_at": created, "title": "Original issue",
                        "body": "Original body", "state": "closed"} for number in range(1, 117)]
        self.pulls = []
        for item in self.issues[59:]:
            item["pull_request"] = {"url": "https://api.github.com/repos/funforgiven/atollion/pulls/" + str(item["number"])}
            self.pulls.append({**item, "merged_at": merged, "merge_commit_sha": f"{item['number']:040x}",
                               "head": {"sha": f"{item['number'] + 200:040x}"},
                               "base": {"sha": f"{item['number'] + 400:040x}"}})
        self.write_export()
        self.wip = {name: ("unfinished: " + name + "\n").encode() for name in RECOVERY.WIP_FILES}
        self.checkpoint = {"head": RECOVERY.SOURCE_MAIN, "branch": "feat/116-logistics-frames",
                           "files": {name: hashlib.sha256(data).hexdigest() for name, data in self.wip.items()}}
        self.write_json("checkpoint/manifest.json", self.checkpoint)
        self.write_tar("checkpoint/unfinished-work.tar.gz", self.wip)
        (self.evidence / "checkpoint/repository.bundle").write_bytes(b"# v2 git bundle\nfixture\n")
        (self.evidence / "checkpoint/working.patch").write_text("unfinished tracked changes\n")
        (self.evidence / "checkpoint/staged.patch").write_bytes(b"")
        self.write_json("lfs-verification.json", {"source": "GitHub complete advertised refs",
                                                "small_blobs_checked": 148, "lfs_pointer_blobs": 0})
        self.manifest = {"schema": 1, "repository": "funforgiven/atollion", "source_main": RECOVERY.SOURCE_MAIN,
                         "cutover_head": self.cutover, "source_issues": 59, "source_pull_requests": 57,
                         "source_lfs_objects": 0, "files": {}}
        for name in RECOVERY.REQUIRED_FILES:
            self.rehash(name)
        self.create_database(created, merged)

    def write_json(self, name, value):
        (self.evidence / name).write_text(json.dumps(value))

    def rehash(self, name):
        content = (self.evidence / name).read_bytes()
        self.manifest["files"][name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        self.write_json("manifest.json", self.manifest)

    def write_tar(self, name, contents, extra=None):
        with tarfile.open(self.evidence / name, "w:gz") as archive:
            for filename, content in contents.items():
                member = tarfile.TarInfo(filename)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            if extra is not None:
                archive.addfile(extra)

    def write_export(self, extra=None):
        self.write_tar("github-export.tar.gz", {
            "github-export/issues.json": json.dumps(self.issues).encode(),
            "github-export/pulls.json": json.dumps(self.pulls).encode(),
        }, extra)

    def create_database(self, created, merged):
        with sqlite3.connect(self.database) as db:
            db.executescript('''
                CREATE TABLE repository (id INTEGER, owner_name TEXT, name TEXT, is_private INTEGER,
                                         is_empty INTEGER, default_branch TEXT);
                CREATE TABLE repo_unit (repo_id INTEGER, type INTEGER, config TEXT);
                CREATE TABLE "user" (id INTEGER, lower_name TEXT, name TEXT, is_active INTEGER,
                                     is_admin INTEGER, prohibit_login INTEGER);
                CREATE TABLE issue (id INTEGER, repo_id INTEGER, "index" INTEGER, is_pull INTEGER,
                                    created_unix INTEGER, name TEXT, content TEXT, is_closed INTEGER);
                CREATE TABLE pull_request (issue_id INTEGER, base_repo_id INTEGER, "index" INTEGER,
                                           has_merged INTEGER, merged_commit_id TEXT, merged_unix INTEGER);
                CREATE TABLE protected_branch (
                    repo_id INTEGER, branch_name TEXT, can_push INTEGER, enable_whitelist INTEGER,
                    whitelist_deploy_keys INTEGER, whitelist_user_i_ds TEXT, whitelist_team_i_ds TEXT,
                    enable_merge_whitelist INTEGER, merge_whitelist_user_i_ds TEXT, merge_whitelist_team_i_ds TEXT,
                    enable_status_check INTEGER, status_check_contexts TEXT,
                    enable_approvals_whitelist INTEGER, approvals_whitelist_user_i_ds TEXT,
                    approvals_whitelist_team_i_ds TEXT, required_approvals INTEGER,
                    block_on_rejected_reviews INTEGER, block_on_official_review_requests INTEGER,
                    block_on_outdated_branch INTEGER, dismiss_stale_approvals INTEGER,
                    ignore_stale_approvals INTEGER, require_signed_commits INTEGER, apply_to_admins INTEGER,
                    unprotected_file_patterns TEXT);
            ''')
            db.execute("INSERT INTO repository VALUES (10, 'funforgiven', 'atollion', 1, 0, 'main')")
            self.pull_config = {"AllowFastForwardOnly": True, "DefaultMergeStyle": "fast-forward-only",
                                "AllowMerge": False, "AllowRebase": False, "AllowRebaseMerge": False,
                                "AllowSquash": False, "AllowManualMerge": False, "AutodetectManualMerge": False}
            db.execute("INSERT INTO repo_unit VALUES (10, 3, ?)", (json.dumps(self.pull_config),))
            names = ["funforgiven", "atollion-coordinator", "atollion-worker-1", "atollion-worker-2", "atollion-worker-3"]
            for identity, name in enumerate(names, 1):
                db.execute('INSERT INTO "user" VALUES (?, ?, ?, 1, 0, 0)', (identity, name, name))
            for item in self.issues:
                number = item["number"]
                db.execute("INSERT INTO issue VALUES (?, 10, ?, ?, ?, ?, ?, 1)",
                           (number, number, int(number > 59), RECOVERY.unix_time(created), item["title"], item["body"]))
            for item in self.pulls:
                db.execute("INSERT INTO pull_request VALUES (?, 10, ?, 1, ?, ?)",
                           (item["number"], item["number"], item["merge_commit_sha"], RECOVERY.unix_time(merged)))
            contexts = [f"Atollion validation / {job} (pull_request)" for job in
                        ["linux-quality", "windows-build", "windows-native", "macos-native", "validation"]]
            db.execute("INSERT INTO protected_branch VALUES (10, 'main', 0, 0, 0, '[]', '[]', "
                       "1, '[1,2]', '[]', 1, ?, 1, '[1,2,3,4,5]', '[]', 1, 1, 1, 1, 1, 1, 1, 1, '')",
                       (json.dumps(contexts),))

    def mutate_database(self, statement, values=()):
        with sqlite3.connect(self.database) as db:
            db.execute(statement, values)

    def verify(self):
        return RECOVERY.verify_atollion(self.backup, self.target)

    def assert_failure(self):
        with self.assertRaises((RuntimeError, ValueError, FileNotFoundError)):
            self.verify()
        for name in RECOVERY.MARKERS:
            self.assertFalse((self.target / name).exists(), name)

    def test_complete_restore_emits_only_valid_git_expectations(self):
        result = self.verify()
        self.assertEqual(result["repository"], "funforgiven/atollion")
        self.assertEqual((self.target / ".atollion-main-ancestors").read_text().splitlines(),
                         [RECOVERY.SOURCE_MAIN, self.cutover])
        commits = (self.target / ".atollion-required-commits").read_text().splitlines()
        self.assertEqual(commits, result["required_commits"])
        self.assertEqual(len(commits), 57 * 3 + 2)
        self.assertTrue(all(RECOVERY.SHA1.fullmatch(commit) for commit in commits))
        self.assertFalse((self.target / ".qualified").exists())

    def test_missing_manifest_clears_all_stale_git_markers(self):
        self.verify()
        (self.evidence / "manifest.json").unlink()
        self.assert_failure()

    def test_missing_artifact_or_database_or_repository_fails(self):
        paths = [self.evidence / "checkpoint/staged.patch", self.database,
                 self.target / "data/git/repositories/funforgiven/atollion.git"]
        for path in paths:
            with self.subTest(path=path.name):
                moved = path.with_name(path.name + ".temporary")
                path.rename(moved)
                try:
                    self.assert_failure()
                finally:
                    moved.rename(path)

    def test_monthly_issue_edits_and_new_work_are_allowed(self):
        self.mutate_database("UPDATE issue SET name = 'Edited title', content = 'New details', is_closed = 0")
        self.mutate_database("INSERT INTO issue VALUES (117, 10, 117, 0, 999, 'New issue', 'Future work', 0)")
        self.mutate_database("UPDATE protected_branch SET required_approvals = 2")
        self.verify()

    def test_pull_creation_uses_pulls_export_not_issue_list_timestamp(self):
        self.issues[59]["created_at"] = "2026-09-06T13:00:01Z"
        self.write_export()
        self.rehash("github-export.tar.gz")
        self.verify()

    def test_original_export_and_checkpoint_bytes_are_checked(self):
        for name in ["github-export.tar.gz", "checkpoint/working.patch", "checkpoint/repository.bundle"]:
            with self.subTest(artifact=name):
                path = self.evidence / name
                original = path.read_bytes()
                path.write_bytes(b"X" + original[1:])
                try:
                    self.assert_failure()
                finally:
                    path.write_bytes(original)

    def test_manifest_cannot_reference_outside_files_or_credentials(self):
        for name in ["../outside", "/etc/passwd", "credentials.json", "checkpoint/../credentials.json"]:
            with self.subTest(path=name):
                self.manifest["files"][name] = {"size": 0, "sha256": "0" * 64}
                self.write_json("manifest.json", self.manifest)
                self.assert_failure()
                del self.manifest["files"][name]

    def test_symbolic_link_evidence_is_rejected(self):
        path = self.evidence / "checkpoint/staged.patch"
        outside = self.root / "outside"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        self.assert_failure()

    def test_source_archive_rejects_links_and_path_traversal(self):
        for name, kind in [("github-export/link", tarfile.SYMTYPE), ("../escape", tarfile.REGTYPE)]:
            with self.subTest(path=name):
                extra = tarfile.TarInfo(name)
                extra.type = kind
                extra.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
                self.write_export(extra)
                self.rehash("github-export.tar.gz")
                self.assert_failure()

    def test_source_issue_number_and_kind_must_survive(self):
        self.mutate_database('UPDATE issue SET is_pull = 1 WHERE "index" = 1')
        self.assert_failure()
        self.mutate_database('UPDATE issue SET is_pull = 0 WHERE "index" = 1')
        self.mutate_database('DELETE FROM issue WHERE "index" = 116')
        self.assert_failure()

    def test_historic_creation_and_merge_identity_must_survive(self):
        changes = [
            ('UPDATE issue SET created_unix = created_unix + 1 WHERE "index" = 1',),
            ('UPDATE issue SET created_unix = created_unix + 1 WHERE "index" = 60',),
            ('UPDATE pull_request SET merged_commit_id = ? WHERE "index" = 60', "a" * 40),
            ('UPDATE pull_request SET merged_unix = merged_unix + 1 WHERE "index" = 60',),
            ('UPDATE pull_request SET has_merged = 0 WHERE "index" = 60',),
        ]
        original = self.database.read_bytes()
        for statement, *values in changes:
            with self.subTest(statement=statement):
                self.mutate_database(statement, values)
                self.assert_failure()
                self.database.write_bytes(original)

    def test_wip_files_are_checked_against_original_checkpoint_hashes(self):
        self.wip["crates/protocol/src/lib.rs"] = b"truncated unfinished work\n"
        self.write_tar("checkpoint/unfinished-work.tar.gz", self.wip)
        self.rehash("checkpoint/unfinished-work.tar.gz")
        self.assert_failure()

    def test_unfinished_work_file_cannot_disappear_from_both_manifests(self):
        del self.wip["crates/protocol/src/lib.rs"]
        del self.checkpoint["files"]["crates/protocol/src/lib.rs"]
        self.write_json("checkpoint/manifest.json", self.checkpoint)
        self.write_tar("checkpoint/unfinished-work.tar.gz", self.wip)
        self.rehash("checkpoint/manifest.json")
        self.rehash("checkpoint/unfinished-work.tar.gz")
        self.assert_failure()

    def test_each_agent_must_be_active_and_nonadmin(self):
        for name in sorted(RECOVERY.AGENTS):
            for column, value in [("is_active", 0), ("is_admin", 1), ("prohibit_login", 1)]:
                with self.subTest(agent=name, column=column):
                    self.mutate_database(f'UPDATE "user" SET {column} = ? WHERE name = ?', (value, name))
                    self.assert_failure()
                    self.mutate_database(f'UPDATE "user" SET {column} = ? WHERE name = ?', (1 - value, name))

    def test_policy_cannot_drop_ci_approval_or_allow_pushes(self):
        original = self.database.read_bytes()
        for column, value in [("can_push", 1), ("required_approvals", 0), ("enable_status_check", 0),
                              ("status_check_contexts", "[]"), ("apply_to_admins", 0),
                              ("dismiss_stale_approvals", 0), ("require_signed_commits", 0),
                              ("merge_whitelist_user_i_ds", "[1,2,3]"),
                              ("approvals_whitelist_user_i_ds", "[1,2,3,4,5,6]"),
                              ("unprotected_file_patterns", "README.md")]:
            with self.subTest(protection=column):
                self.mutate_database(f"UPDATE protected_branch SET {column} = ?", (value,))
                self.assert_failure()
                self.database.write_bytes(original)

    def test_cutover_head_cannot_inject_git_arguments(self):
        self.manifest["cutover_head"] = "--all\n" + "a" * 40
        self.write_json("manifest.json", self.manifest)
        self.assert_failure()

    def test_repository_must_preserve_fast_forward_only_merging(self):
        changes = [("AllowFastForwardOnly", False), ("DefaultMergeStyle", "merge"),
                   ("AllowMerge", True), ("AllowRebase", True), ("AllowRebaseMerge", True),
                   ("AllowSquash", True), ("AllowManualMerge", True), ("AutodetectManualMerge", True)]
        for name, value in changes:
            with self.subTest(setting=name):
                config = {**self.pull_config, name: value}
                self.mutate_database("UPDATE repo_unit SET config = ?", (json.dumps(config),))
                self.assert_failure()

    def test_missing_or_incomplete_pull_request_configuration_fails(self):
        for config in [{}, {"AllowFastForwardOnly": True, "DefaultMergeStyle": "fast-forward-only"}, []]:
            with self.subTest(config=config):
                self.mutate_database("UPDATE repo_unit SET config = ?", (json.dumps(config),))
                self.assert_failure()
        self.mutate_database("DELETE FROM repo_unit")
        self.assert_failure()

    def test_original_lfs_inventory_is_required_and_scoped_to_source(self):
        self.write_json("lfs-verification.json", {"source": "current checkout only",
                                                "small_blobs_checked": 148, "lfs_pointer_blobs": 0})
        self.rehash("lfs-verification.json")
        self.assert_failure()

    def test_optional_goal_evidence_is_checksummed(self):
        self.write_json("checkpoint/original-goal-state.json", {"status": "paused"})
        self.rehash("checkpoint/original-goal-state.json")
        self.verify()
        self.write_json("checkpoint/original-goal-state.json", {"status": "changed"})
        self.assert_failure()


if __name__ == "__main__":
    unittest.main()
