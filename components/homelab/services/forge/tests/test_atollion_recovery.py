import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[5]
SPEC = importlib.util.spec_from_file_location(
    "verify_atollion", ROOT / "deployments/homelab/cluster/apps/forge/verify_atollion.py")
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


class AtollionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / "restore"
        (self.target / "data/data").mkdir(parents=True)
        (self.target / "data/git/repositories/funforgiven/atollion.git").mkdir(parents=True)
        self.database = self.target / "data/data/forgejo.db"
        self.create_database()

    def create_database(self):
        with sqlite3.connect(self.database) as db:
            db.executescript('''
                CREATE TABLE repository (id INTEGER, owner_name TEXT, name TEXT, is_private INTEGER,
                                         is_empty INTEGER, default_branch TEXT);
                CREATE TABLE repo_unit (repo_id INTEGER, type INTEGER, config TEXT);
                CREATE TABLE "user" (id INTEGER, lower_name TEXT, name TEXT, is_active INTEGER,
                                     is_admin INTEGER, prohibit_login INTEGER);
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
            contexts = [f"Atollion validation / {job} (pull_request)" for job in
                        ["linux-quality", "windows-build", "validation"]]
            db.execute("INSERT INTO protected_branch VALUES (10, 'main', 0, 0, 0, '[]', '[]', "
                       "1, '[1,2]', '[]', 1, ?, 1, '[1,2,3,4,5]', '[]', 1, 1, 1, 1, 1, 1, 1, 1, '')",
                       (json.dumps(contexts),))

    def mutate_database(self, statement, values=()):
        with sqlite3.connect(self.database) as db:
            db.execute(statement, values)

    def verify(self, **kwargs):
        return RECOVERY.verify_atollion(self.target, **kwargs)

    def assert_failure(self, **kwargs):
        with self.assertRaises((RuntimeError, ValueError)):
            self.verify(**kwargs)

    def test_restored_repository_and_policy_pass(self):
        self.verify()

    def test_missing_database_or_repository_fails(self):
        for path in [self.database, self.target / "data/git/repositories/funforgiven/atollion.git"]:
            with self.subTest(path=path.name):
                moved = path.with_name(path.name + ".temporary")
                path.rename(moved)
                try:
                    self.assert_failure()
                finally:
                    moved.rename(path)

    def test_repository_must_stay_private_with_main_default(self):
        original = self.database.read_bytes()
        for column, value in [("is_private", 0), ("is_empty", 1), ("default_branch", "master")]:
            with self.subTest(column=column):
                self.mutate_database(f"UPDATE repository SET {column} = ?", (value,))
                self.assert_failure()
                self.database.write_bytes(original)

    def test_stricter_approval_count_is_allowed(self):
        self.mutate_database("UPDATE protected_branch SET required_approvals = 2")
        self.verify()

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

    def local_policy(self):
        return json.loads((ROOT / "deployments/homelab/cluster/apps/forge/atollion-agent-policy.json").read_text())

    def enable_local_policy(self):
        self.mutate_database("UPDATE protected_branch SET enable_status_check = 0, status_check_contexts = '[]'")

    def test_local_validation_requires_explicit_operator_enrollment(self):
        self.enable_local_policy()
        self.assert_failure()
        self.verify(validation_policy=self.local_policy())

    def test_local_enrollment_preserves_historical_actions_archives(self):
        self.verify(validation_policy=self.local_policy())

    def test_local_enrollment_never_accepts_partial_actions_protection(self):
        self.mutate_database("UPDATE protected_branch SET status_check_contexts = '[]'")
        self.assert_failure(validation_policy=self.local_policy())
        self.mutate_database("UPDATE protected_branch SET enable_status_check = 0, status_check_contexts = ?",
                             (json.dumps(sorted(RECOVERY.CONTEXTS)),))
        self.assert_failure(validation_policy=self.local_policy())

    def test_local_validation_keeps_other_protections_mandatory(self):
        self.enable_local_policy()
        original = self.database.read_bytes()
        for column, value in [("can_push", 1), ("required_approvals", 0), ("apply_to_admins", 0),
                              ("dismiss_stale_approvals", 0), ("require_signed_commits", 0),
                              ("block_on_rejected_reviews", 0), ("block_on_outdated_branch", 0),
                              ("merge_whitelist_user_i_ds", "[1,2,3]")]:
            with self.subTest(protection=column):
                self.mutate_database(f"UPDATE protected_branch SET {column} = ?", (value,))
                self.assert_failure(validation_policy=self.local_policy())
                self.database.write_bytes(original)

    def test_local_enrollment_is_scoped_and_cannot_weaken_approval(self):
        self.enable_local_policy()
        for key, value in [("url", "https://example.com"), ("repository", "someone/else"),
                           ("validation_mode", "automatic"), ("validation_mode", "actions"),
                           ("workflow_id", "other.yml"), ("status_contexts", {"x": "y"}),
                           ("merge_style", "merge"), ("required_approvals", 0),
                           ("required_approvals", 2)]:
            with self.subTest(enrollment=key, value=value):
                self.assert_failure(validation_policy={**self.local_policy(), key: value})

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


if __name__ == "__main__":
    unittest.main()
