#!/usr/bin/env python3
"""Verify Atollion's migration evidence and restored Forgejo 15 database.

Called after archive extraction by verify-restore.py. This check is mandatory
after cutover: a missing migration directory must never silently skip Atollion.
Git object and ancestry checks are handed to verify-git.sh through validated,
newline-only SHA files. This module alone does not qualify a restore.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tarfile


REPOSITORY = "funforgiven/atollion"
SOURCE_MAIN = "6501d61d33a59bdc782f70e9e101f1a791050bad"
SOURCE_ISSUES = 59
SOURCE_PULL_REQUESTS = 57
AGENTS = {"atollion-coordinator", "atollion-worker-1", "atollion-worker-2", "atollion-worker-3"}
CONTEXTS = {f"Atollion validation / {job} (pull_request)" for job in
            ("linux-quality", "windows-build", "windows-native", "macos-native", "validation")}
REQUIRED_FILES = {
    "github-export.tar.gz", "checkpoint/manifest.json", "checkpoint/repository.bundle",
    "checkpoint/unfinished-work.tar.gz", "checkpoint/working.patch", "checkpoint/staged.patch",
    "lfs-verification.json",
}
OPTIONAL_FILES = {"import-verification.json", "checkpoint/original-goal.txt",
                  "checkpoint/original-goal-state.json", "ci-negative-probes.json"}
WIP_FILES = {
    "crates/protocol/src/lib.rs", "crates/protocol/src/logistics_frame_codec.rs",
    "crates/protocol/src/logistics_frames.rs", "fixtures/logistics-frames-v1/20.hex",
    "fixtures/logistics-frames-v1/frames.hex", "fixtures/logistics-frames-v1/initial.hex",
    "tools/logistics_frame_reference.py", "tools/test_logistics_frame_reference.py",
}
MARKERS = (".atollion-git-expectations.json", ".atollion-main-ancestors", ".atollion-required-commits")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_JSON_BYTES = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError("Atollion recovery: " + message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode_json(data):
    require(len(data) <= MAX_JSON_BYTES, "JSON evidence exceeds size limit")
    return json.loads(data, object_pairs_hook=unique_object)


def safe_name(name):
    require(isinstance(name, str) and name and "\\" not in name, "unsafe evidence path")
    parts = PurePosixPath(name).parts
    require(not name.startswith("/") and all(part not in {".", ".."} for part in name.split("/")),
            "unsafe evidence path")
    require(str(PurePosixPath(name)) == name and bool(parts), "noncanonical evidence path")
    return name


def safe_path(root, name, *, directory=False):
    path = root / safe_name(name)
    require(path.resolve() == path.absolute(), "evidence paths must not contain symbolic links")
    require(path.is_dir() if directory else path.is_file(), "required evidence file or directory is missing")
    return path


def read_json(path):
    with path.open("rb") as stream:
        return decode_json(stream.read(MAX_JSON_BYTES + 1))


def sha1(value):
    require(isinstance(value, str) and SHA1.fullmatch(value), "invalid Git commit ID")
    return value


def sha256(value):
    require(isinstance(value, str) and SHA256.fullmatch(value), "invalid file checksum")
    return value


def archive_members(archive, prefix=None):
    """Inspect archives without extracting paths, links, devices or credentials."""
    result = {}
    seen = set()
    for index, member in enumerate(archive):
        require(index < 10000, "source archive has too many entries")
        name = member.name.removeprefix("./").rstrip("/") if member.isdir() else member.name.removeprefix("./")
        safe_name(name)
        require(name not in seen, "duplicate source archive entry")
        seen.add(name)
        require(member.isfile() or member.isdir(), "source archive contains a link or special file")
        require(prefix is None or name == prefix or name.startswith(prefix + "/"), "unexpected source archive path")
        if member.isfile():
            result[name] = member
    return result


def source_items(value, expected_count):
    require(isinstance(value, list) and len(value) == expected_count, "source issue or pull request count differs")
    result = {}
    for item in value:
        require(isinstance(item, dict), "invalid source issue or pull request")
        number = item.get("number")
        require(type(number) is int and 1 <= number <= SOURCE_ISSUES + SOURCE_PULL_REQUESTS,
                "invalid source issue number")
        require(number not in result, "duplicate source issue number")
        result[number] = item
    return result


def read_export(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive_members(archive, "github-export")
        values = []
        for name in ("github-export/issues.json", "github-export/pulls.json"):
            require(name in members, "original GitHub export is incomplete")
            require(members[name].size <= MAX_JSON_BYTES, "source JSON exceeds size limit")
            with archive.extractfile(members[name]) as source:
                values.append(decode_json(source.read(MAX_JSON_BYTES + 1)))
    issues = source_items(values[0], SOURCE_ISSUES + SOURCE_PULL_REQUESTS)
    pulls = source_items(values[1], SOURCE_PULL_REQUESTS)
    require(set(issues) == set(range(1, SOURCE_ISSUES + SOURCE_PULL_REQUESTS + 1)),
            "original GitHub issue namespace is incomplete")
    require({number for number, item in issues.items() if "pull_request" in item} == set(pulls),
            "original GitHub issue kinds differ from pull request export")
    return {number: item for number, item in issues.items() if number not in pulls}, pulls


def verify_checkpoint(directory):
    checkpoint = read_json(directory / "checkpoint/manifest.json")
    require(checkpoint.get("head") == SOURCE_MAIN and checkpoint.get("branch") == "feat/116-logistics-frames",
            "unfinished work checkpoint has the wrong source revision or branch")
    files = checkpoint.get("files")
    require(isinstance(files, dict) and set(files) == WIP_FILES, "unfinished work checkpoint is incomplete")
    with tarfile.open(directory / "checkpoint/unfinished-work.tar.gz", "r:gz") as archive:
        members = archive_members(archive)
        require(set(members) == WIP_FILES, "unfinished work archive has missing or unexpected files")
        for name, expected in files.items():
            with archive.extractfile(members[name]) as source:
                require(hashlib.file_digest(source, "sha256").hexdigest() == sha256(expected),
                        "unfinished work checksum mismatch")
    with (directory / "checkpoint/repository.bundle").open("rb") as source:
        require(source.readline(64) in {b"# v2 git bundle\n", b"# v3 git bundle\n"},
                "original Git bundle header is invalid")


def unix_time(value):
    require(isinstance(value, str) and value.endswith("Z"), "invalid source creation or merge time")
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())


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


def verify_policy(db, repo_id):
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
    for name in ("enable_merge_whitelist", "enable_status_check", "enable_approvals_whitelist",
                 "block_on_rejected_reviews", "block_on_official_review_requests", "block_on_outdated_branch",
                 "dismiss_stale_approvals", "ignore_stale_approvals", "require_signed_commits", "apply_to_admins"):
        require(policy[name] == 1, "required main branch protection is disabled: " + name)
    require(policy["required_approvals"] >= 1, "main must require an independent approval")
    require(CONTEXTS <= set(stored_list(policy["status_check_contexts"])), "required CI protection is incomplete")
    for column, names in (("merge_whitelist_user_i_ds", {"funforgiven", "atollion-coordinator"}),
                          ("approvals_whitelist_user_i_ds", AGENTS | {"funforgiven"})):
        require(set(stored_list(policy[column])) == {by_name[name]["id"] for name in names},
                "main protection account whitelist differs")
    for column in ("whitelist_user_i_ds", "whitelist_team_i_ds", "merge_whitelist_team_i_ds", "approvals_whitelist_team_i_ds"):
        require(not stored_list(policy[column]), "unexpected main branch protection exception")
    require(not policy["unprotected_file_patterns"], "main must not allow unprotected file exceptions")


def verify_database(database, issues, pulls):
    commits = {SOURCE_MAIN}
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        repositories = db.execute("SELECT id, is_private, is_empty, default_branch FROM repository "
                                  "WHERE owner_name = 'funforgiven' AND name = 'atollion'").fetchall()
        require(len(repositories) == 1, "restored repository metadata is missing or ambiguous")
        repo = repositories[0]
        require(repo["is_private"] == 1 and repo["is_empty"] == 0 and repo["default_branch"] == "main",
                "restored repository privacy or default branch differs")
        verify_merge_style(db, repo["id"])
        verify_policy(db, repo["id"])
        # Titles, bodies, labels and issue states can legitimately change after
        # cutover. The hashed original export retains their initial values.
        for number, source in {**issues, **pulls}.items():
            rows = db.execute('SELECT id, is_pull, created_unix FROM issue WHERE repo_id = ? AND "index" = ?',
                              (repo["id"], number)).fetchall()
            require(len(rows) == 1, "a source issue or pull request is missing or duplicated")
            issue = rows[0]
            require(issue["is_pull"] == int(number in pulls), "source issue kind differs")
            require(issue["created_unix"] == unix_time(source["created_at"]), "source creation time differs")
            if number not in pulls:
                continue
            records = db.execute('SELECT has_merged, merged_commit_id, merged_unix FROM pull_request '
                                 'WHERE issue_id = ? AND base_repo_id = ? AND "index" = ?',
                                 (issue["id"], repo["id"], number)).fetchall()
            require(len(records) == 1, "source pull request metadata is missing or duplicated")
            pull = records[0]
            require(source.get("merged_at") and pull["has_merged"] == 1, "historical pull request merge is missing")
            merge = sha1(source["merge_commit_sha"])
            require(pull["merged_commit_id"] == merge and pull["merged_unix"] == unix_time(source["merged_at"]),
                    "historical pull request merge metadata differs")
            commits.update((sha1(source["head"]["sha"]), sha1(source["base"]["sha"]), merge))
    return commits


def verify_atollion(backup, target):
    """Raise on missing/tampered evidence; emit Git expectations only on success."""
    backup, target = Path(backup).absolute(), Path(target).absolute()
    require(target.resolve() == target, "restore target must not contain symbolic links")
    for name in MARKERS:
        (target / name).unlink(missing_ok=True)
    directory = safe_path(backup, "atollion-migration", directory=True)
    manifest = read_json(safe_path(directory, "manifest.json"))
    require(manifest.get("schema") == 1 and manifest.get("repository") == REPOSITORY,
            "invalid migration manifest")
    require(manifest.get("source_main") == SOURCE_MAIN and manifest.get("source_issues") == SOURCE_ISSUES
            and manifest.get("source_pull_requests") == SOURCE_PULL_REQUESTS,
            "migration source baseline differs")
    cutover = sha1(manifest.get("cutover_head"))
    require(manifest.get("source_lfs_objects") == 0, "migration source LFS baseline differs")
    files = manifest.get("files")
    require(isinstance(files, dict) and REQUIRED_FILES <= set(files) <= REQUIRED_FILES | OPTIONAL_FILES,
            "migration manifest has missing or unexpected artifacts")
    for name, expected in files.items():
        require(isinstance(expected, dict) and type(expected.get("size")) is int and expected["size"] >= 0,
                "invalid artifact size")
        path = safe_path(directory, name)
        require(path.stat().st_size == expected["size"], "migration artifact size mismatch")
        with path.open("rb") as source:
            require(hashlib.file_digest(source, "sha256").hexdigest() == sha256(expected.get("sha256")),
                    "migration artifact checksum mismatch")
    issues, pulls = read_export(directory / "github-export.tar.gz")
    verify_checkpoint(directory)
    lfs = read_json(directory / "lfs-verification.json")
    require(lfs.get("source") == "GitHub complete advertised refs"
            and lfs.get("small_blobs_checked") == 148 and lfs.get("lfs_pointer_blobs") == 0,
            "original GitHub LFS inventory evidence differs")
    # This is evidence for the original imported history only. It does not claim
    # to verify LFS content that may be introduced by future development.
    safe_path(target, "data/git/repositories/funforgiven/atollion.git", directory=True)
    commits = verify_database(safe_path(target, "data/data/forgejo.db"), issues, pulls)
    commits.add(cutover)
    result = {"schema": 1, "repository": REPOSITORY, "source_main": SOURCE_MAIN,
              "cutover_head": cutover, "required_commits": sorted(commits), "source_lfs_objects": 0}
    try:
        (target / MARKERS[0]).write_text(json.dumps(result, sort_keys=True) + "\n")
        (target / MARKERS[1]).write_text(SOURCE_MAIN + "\n" + cutover + "\n")
        (target / MARKERS[2]).write_text("\n".join(sorted(commits)) + "\n")
    except BaseException:
        for name in MARKERS:
            (target / name).unlink(missing_ok=True)
        raise
    print("Atollion original GitHub export, 59 issues, 57 pull requests, unfinished work, "
          "agent accounts and merge policy verified; Git ancestry and objects await Git verifier.", flush=True)
    return result
