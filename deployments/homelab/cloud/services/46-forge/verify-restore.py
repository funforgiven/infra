#!/usr/bin/env python3
"""Validate an offsite-restored archive before the Git verifier can mark it ready."""

import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile
import time
from native_backup import verify_index

backup = Path("/backups")
target = Path("/restore")
# A failed/restarted verifier must never reuse a readiness marker.
for marker in [".qualified", ".database-verified"]:
    (target / marker).unlink(missing_ok=True)
markers = sorted(backup.glob("forgejo-*.tar.gz.json"))
if not markers:
    raise RuntimeError("No completed Forgejo recovery archive was restored")
manifest = json.loads(markers[-1].read_text())
archive = backup / manifest["archive"]
if archive.parent != backup or not manifest["quiesced"]:
    raise RuntimeError("Invalid recovery manifest")
if manifest["database"] != "data/forgejo.db":
    raise RuntimeError("Unexpected recovery database path")
with archive.open("rb") as source:
    if hashlib.file_digest(source, "sha256").hexdigest() != manifest["sha256"]:
        raise RuntimeError("Restored archive checksum mismatch")
with tarfile.open(archive) as source:
    source.extractall(target, filter="data")
database = target / "data" / manifest["database"]
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RuntimeError("Restored SQLite integrity check failed")
    if not db.execute("SELECT 1 FROM login_source WHERE name = 'ZITADEL' AND is_active = 1").fetchone():
        raise RuntimeError("Restored identity provider is missing or disabled")
    repo = db.execute("SELECT id FROM repository WHERE owner_name = 'forge-runner' AND name = 'runner-qualification'").fetchone()
    if not repo:
        raise RuntimeError("Restored qualification repository is missing")
    artifact = db.execute("SELECT storage_path FROM action_artifact WHERE repo_id = ? AND artifact_name = 'qualification' ORDER BY id DESC LIMIT 1", repo).fetchone()
    if not artifact:
        raise RuntimeError("Restored qualification artifact metadata is missing")
    contents = target / "data/data/actions_artifacts" / artifact[0]
    if contents.read_bytes() != b"forgejo-recovery-qualification-v1\n":
        raise RuntimeError("Restored Actions artifact differs from its verified job output")
    if db.execute("SELECT COUNT(*) FROM action_task WHERE repo_id = ? AND status = 1", repo).fetchone()[0] < 2:
        raise RuntimeError("Restored successful Actions history is incomplete")
legacy_marker = backup / "legacy-gitlab.json"
if legacy_marker.exists():
    legacy = json.loads(legacy_marker.read_text())
    legacy_archive = backup / legacy["archive"]
    if legacy_archive.parent != backup:
        raise RuntimeError("Invalid legacy archive path")
    with legacy_archive.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != legacy["sha256"]:
            raise RuntimeError("Retained GitLab archive checksum mismatch")
    with tarfile.open(legacy_archive) as source:
        checksums = source.extractfile("current/SHA256SUMS").read().decode()
        for line in checksums.splitlines():
            expected, filename = line.split(maxsplit=1)
            filename = filename.removeprefix("./")
            with source.extractfile("current/" + filename) as member:
                if hashlib.file_digest(member, "sha256").hexdigest() != expected:
                    raise RuntimeError("Native GitLab backup or recovery secrets failed verification")
    print("Retained native GitLab archive and recovery secrets verified.", flush=True)
verify_index(backup)
(target / ".database-verified").write_text(manifest["sha256"] + "\n")
print("Offsite archive checksum, SQLite, OIDC, repository metadata, Actions history and artifact bytes verified.", flush=True)
while True:
    time.sleep(3600)
