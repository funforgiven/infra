#!/usr/bin/env python3
"""Bound worker logs and start kubelet image cleanup before disk-pressure eviction."""

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

KUBELET = "var/lib/kubelet/config.yaml"
RSYSLOG = "etc/logrotate.d/rsyslog"
JOURNAL = "etc/systemd/journald.conf.d/90-services-retention.conf"
TIMER = "etc/systemd/system/logrotate.timer.d/90-services-retention.conf"
STATE = "var/lib/services-node-policy"
JOURNAL_CONFIG = """[Journal]
SystemMaxUse=512M
SystemKeepFree=6G
MaxRetentionSec=7day
MaxFileSec=1day
"""
TIMER_CONFIG = """[Timer]
OnCalendar=
OnCalendar=hourly
RandomizedDelaySec=5m
Persistent=true
"""


class HostPolicyError(RuntimeError):
    def __init__(self, command, returncode, stderr=b""):
        detail = ""
        if command[0] == "/usr/sbin/logrotate":
            # Logrotate reports filenames and rotation errors, never log data.
            detail = " ".join(
                line[:400]
                for line in stderr.decode(errors="replace").splitlines()
                if line.startswith("error:")
            )[:1200]
        super().__init__(
            f"Host policy command failed ({returncode}): "
            + " ".join(command)
            + (": " + detail if detail else "")
        )
        self.returncode = returncode


def kubelet_policy(text):
    # Preserve unrelated YAML verbatim; JSON is also accepted by kubelet.
    is_json = text.lstrip().startswith("{")
    if is_json:
        data = json.loads(text)
    else:
        data = {}
        for key in (
            "kind",
            "apiVersion",
            "imageGCHighThresholdPercent",
            "imageGCLowThresholdPercent",
        ):
            matches = re.findall(r"^" + key + r":[ \t]*([^\n#]+)", text, re.MULTILINE)
            if len(matches) > 1:
                raise ValueError("Duplicate kubelet configuration field")
            if matches:
                value = matches[0].strip().strip("\"'")
                data[key] = int(value) if key.startswith("imageGC") else value
    if (
        data.get("kind") != "KubeletConfiguration"
        or data.get("apiVersion") != "kubelet.config.k8s.io/v1beta1"
    ):
        raise ValueError("Unexpected kubelet configuration schema")
    high, low = (
        data.get("imageGCHighThresholdPercent", 85),
        data.get("imageGCLowThresholdPercent", 80),
    )
    if type(high) is not int or type(low) is not int or not 0 < low < high <= 100:
        raise ValueError("Invalid image cleanup thresholds")
    # Keep an already more conservative policy; never loosen it.
    wanted = min(high, 70), min(low, 60)
    if (high, low) == wanted and all(
        key in data
        for key in ("imageGCHighThresholdPercent", "imageGCLowThresholdPercent")
    ):
        return text
    for key, value in zip(
        ("imageGCHighThresholdPercent", "imageGCLowThresholdPercent"), wanted
    ):
        if is_json:
            data[key] = value
        elif key in data:
            text = re.sub(
                r"^" + key + r":[^\n]*", f"{key}: {value}", text, flags=re.MULTILINE
            )
        else:
            text = text.rstrip("\n") + f"\n{key}: {value}\n"
    return json.dumps(data, indent=2) + "\n" if is_json else text


def rsyslog_policy(text):
    if (
        text.count("{") != 1
        or text.count("}") != 1
        or "/usr/lib/rsyslog/rsyslog-rotate" not in text
    ):
        raise ValueError("Unexpected rsyslog rotation policy")
    # Preserve the image's file list and reopen hook. Evaluate size hourly,
    # compress immediately and retain four archives instead of weekly growth.
    if len(re.findall(r"^\s*(?:weekly|daily)\s*$", text, re.MULTILINE)) != 1:
        raise ValueError("Ambiguous rsyslog rotation schedule")
    if len(re.findall(r"^\s*rotate\s+4\s*$", text, re.MULTILINE)) != 1:
        raise ValueError("Unexpected rsyslog archive retention")
    text = re.sub(
        r"^([ \t]*)(?:weekly|daily)[ \t]*$", r"\1daily", text, flags=re.MULTILINE
    )
    text = re.sub(
        r"^[ \t]*(?:delaycompress|maxsize\s+\S+|su root adm|create)[ \t]*\n",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Standalone initial rotation must retain Ubuntu's global defaults too.
    return text.replace("{", "{\n\tsu root adm\n\tcreate\n\tmaxsize 64M", 1)


def write(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    # Config files can be bind mounts: write and fsync before restarting their
    # reader, rather than replacing the mounted inode.
    with path.open("w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, mode)


def apply(root, dry_run=False):
    if (root / "etc/kubernetes/manifests/kube-apiserver.yaml").exists():
        raise ValueError("Worker policy must not run on a control plane")
    original = {
        name: (root / name).read_text() if (root / name).exists() else None
        for name in (KUBELET, RSYSLOG, JOURNAL, TIMER)
    }
    if original[KUBELET] is None or original[RSYSLOG] is None:
        raise ValueError("Expected Magnum worker configuration is missing")
    planned = {
        KUBELET: kubelet_policy(original[KUBELET]),
        RSYSLOG: rsyslog_policy(original[RSYSLOG]),
        JOURNAL: JOURNAL_CONFIG,
        TIMER: TIMER_CONFIG,
    }
    changed = [name for name, value in planned.items() if original[name] != value]
    print("Worker policy changes:", ", ".join(changed) or "none", flush=True)
    if dry_run or not changed:
        return
    state = root / STATE
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    for name in changed:
        backup = state / (name.replace("/", "_") + ".original")
        if original[name] is not None and not backup.exists():
            write(backup, original[name], 0o600)

    def host(*command, timeout=120):
        def enter():
            os.chroot(root)
            os.chdir("/")

        # Host tools and configuration stay together; diagnostics are suppressed
        # because kubelet configuration can contain private endpoint details.
        result = subprocess.run(
            command, preexec_fn=enter, capture_output=True, timeout=timeout, check=False
        )
        if result.returncode:
            raise HostPolicyError(command, result.returncode, result.stderr)
        return result.stdout

    try:
        for name in changed:
            write(root / name, planned[name])
        host("/usr/sbin/logrotate", "--debug", "/etc/logrotate.conf")
        if TIMER in changed:
            host("/usr/bin/systemctl", "daemon-reload")
            host("/usr/bin/systemctl", "restart", "logrotate.timer")
        if JOURNAL in changed:
            host("/usr/bin/systemctl", "restart", "systemd-journald.service")
            host("/usr/bin/journalctl", "--rotate")
            host("/usr/bin/journalctl", "--vacuum-size=512M", "--vacuum-time=7d")
        if RSYSLOG in changed:
            # The system timer and this initial rotation share logrotate's lock.
            for attempt in range(6):
                try:
                    host("/usr/sbin/logrotate", "--force", "/etc/logrotate.d/rsyslog")
                    break
                except HostPolicyError as error:
                    if error.returncode != 75 or attempt == 5:
                        raise
                    time.sleep(5)
        if KUBELET in changed:
            host("/usr/bin/systemctl", "restart", "kubelet.service")
            time.sleep(8)
            host("/usr/bin/systemctl", "is-active", "--quiet", "kubelet.service")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("Activation failed:", str(error), flush=True)
        for name in changed:
            if original[name] is None:
                (root / name).unlink(missing_ok=True)
            else:
                write(root / name, original[name])
        for command in (
            ("/usr/bin/systemctl", "daemon-reload"),
            (
                "/usr/bin/systemctl",
                "restart",
                "logrotate.timer",
                "systemd-journald.service",
            ),
            ("/usr/bin/systemctl", "restart", "kubelet.service"),
        ):
            try:
                host(*command)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                print(
                    "Restored configuration; a service restart needs inspection",
                    flush=True,
                )
        raise RuntimeError(
            "Worker policy failed; previous configuration restored"
        ) from None
    print("Worker log retention and image cleanup policy applied", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/host"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    apply(args.root, args.dry_run)


if __name__ == "__main__":
    main()
