#!/usr/bin/env python3
"""Verify the restored Atollion repository keeps its review and merge policy.

Called by verify-restore.py after the archive is extracted. Git object checks
are in verify-git.sh.
"""

import json
from pathlib import Path
import sqlite3


REPOSITORY = "funforgiven/atollion"
AGENTS = {"atollion-coordinator", "atollion-worker-1", "atollion-worker-2", "atollion-worker-3"}
CONTEXTS = {f"Atollion validation / {job} (pull_request)" for job in
            ("linux-quality", "windows-build", "validation")}


def require(condition, message):
    if not condition:
        raise RuntimeError("Atollion recovery: " + message)


def decode_json(data):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique_object)


def stored_list(value):
    # Xorm stores nil slices as null or an empty value, and nonempty slices as JSON.
    result = [] if value in (None, "", "null") else json.loads(value)
    require(isinstance(result, list), "invalid stored protection list")
    return result


def verify_merge_style(db, repo_id):
    # Forgejo 15 models/repo/repo_unit.go stores PullRequestsConfig as JSON;
    # models/unit/unit.go assigns TypePullRequests = 3. These are database
    # field names, not the differently named repository REST API properties.
    units = db.execute("SELECT config FROM repo_unit WHERE repo_id = ? AND type = 3", (repo_id,)).fetchall()
    require(len(units) == 1, "pull request unit is missing or ambiguous")
    config = decode_json(units[0]["config"])
    require(isinstance(config, dict), "invalid stored pull request configuration")
    require(config.get("AllowFastForwardOnly") is True and config.get("DefaultMergeStyle") == "fast-forward-only",
            "repository must preserve the exact reviewed and validated commit through fast-forward merging")
    for name in ("AllowMerge", "AllowRebase", "AllowRebaseMerge", "AllowSquash", "AllowManualMerge", "AutodetectManualMerge"):
        require(config.get(name) is False, "alternate or automatic manual merge mode must remain disabled: " + name)


def local_validation_enrolled(enrollment):
    if enrollment is None:
        return False
    require(enrollment.get("url") == "https://git.fahrican.com"
            and enrollment.get("repository") == REPOSITORY
            and enrollment.get("workflow_id") == "validation.yml"
            and enrollment.get("merge_style") == "fast-forward-only"
            and type(enrollment.get("required_approvals")) is int
            and enrollment["required_approvals"] >= 1,
            "invalid operator validation enrollment")
    mode = enrollment.get("validation_mode", "actions")
    contexts = enrollment.get("status_contexts")
    require(mode in {"actions", "local"} and isinstance(contexts, dict),
            "invalid operator validation mode or contexts")
    require(contexts == {} if mode == "local" else set(contexts.values()) == CONTEXTS,
            "operator validation contexts differ from the enrolled mode")
    return mode == "local"


def verify_policy(db, repo_id, validation_policy=None):
    local_enrolled = local_validation_enrolled(validation_policy)
    users = db.execute('SELECT id, name, is_active, is_admin, prohibit_login FROM "user" '
                       'WHERE lower_name IN (?, ?, ?, ?, ?)', tuple(sorted(AGENTS | {"funforgiven"}))).fetchall()
    by_name = {row["name"]: row for row in users}
    require(set(by_name) == AGENTS | {"funforgiven"}, "an agent or repository owner account is missing")
    for name in AGENTS:
        row = by_name[name]
        require(row["is_active"] == 1 and row["is_admin"] == 0 and row["prohibit_login"] == 0,
                "agent account must be active, unsuspended and nonadmin")
    require(len({by_name[name]["id"] for name in AGENTS}) == len(AGENTS), "agent identities are not distinct")
    rows = db.execute("SELECT * FROM protected_branch WHERE repo_id = ? AND branch_name = 'main'", (repo_id,)).fetchall()
    require(len(rows) == 1, "main branch protection is missing or ambiguous")
    policy = rows[0]
    for name in ("can_push", "enable_whitelist", "whitelist_deploy_keys"):
        require(policy[name] == 0, "direct pushes to main must remain disabled")
    for name in ("enable_merge_whitelist", "enable_approvals_whitelist",
                 "block_on_rejected_reviews", "block_on_official_review_requests", "block_on_outdated_branch",
                 "dismiss_stale_approvals", "ignore_stale_approvals", "require_signed_commits", "apply_to_admins"):
        require(policy[name] == 1, "required main branch protection is disabled: " + name)
    minimum_approvals = validation_policy["required_approvals"] if validation_policy is not None else 1
    require(policy["required_approvals"] >= minimum_approvals, "main must require the enrolled independent approvals")
    contexts = set(stored_list(policy["status_check_contexts"]))
    if local_enrolled and policy["enable_status_check"] == 0:
        require(not contexts, "local validation protection must have no Actions contexts")
    else:
        # Actions-protected archives must stay recoverable; partial protection fails.
        require(policy["enable_status_check"] == 1 and CONTEXTS <= contexts,
                "required CI protection is incomplete; local validation needs operator enrollment")
    for column, names in (("merge_whitelist_user_i_ds", {"funforgiven", "atollion-coordinator"}),
                          ("approvals_whitelist_user_i_ds", AGENTS | {"funforgiven"})):
        require(set(stored_list(policy[column])) == {by_name[name]["id"] for name in names},
                "main protection account whitelist differs")
    for column in ("whitelist_user_i_ds", "whitelist_team_i_ds", "merge_whitelist_team_i_ds", "approvals_whitelist_team_i_ds"):
        require(not stored_list(policy[column]), "unexpected main branch protection exception")
    require(not policy["unprotected_file_patterns"], "main must not allow unprotected file exceptions")


def verify_atollion(target, *, validation_policy=None):
    """Raise unless the restored repository and its protection policy survived."""
    target = Path(target).absolute()
    repository = target / "data/git/repositories/funforgiven/atollion.git"
    database = target / "data/data/forgejo.db"
    require(repository.is_dir() and not repository.is_symlink(), "restored Git repository is missing")
    require(database.is_file() and not database.is_symlink(), "restored database is missing")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        repositories = db.execute("SELECT id, is_private, is_empty, default_branch FROM repository "
                                  "WHERE owner_name = 'funforgiven' AND name = 'atollion'").fetchall()
        require(len(repositories) == 1, "restored repository metadata is missing or ambiguous")
        repo = repositories[0]
        require(repo["is_private"] == 1 and repo["is_empty"] == 0 and repo["default_branch"] == "main",
                "restored repository privacy or default branch differs")
        verify_merge_style(db, repo["id"])
        verify_policy(db, repo["id"], validation_policy)
    print("Atollion repository, agent accounts, branch protection and merge policy verified.", flush=True)
