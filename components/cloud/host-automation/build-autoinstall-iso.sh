#!/usr/bin/env bash
set -euo pipefail

umask 077

if [[ $# -lt 3 || $# -gt 4 ]]; then
  printf 'usage: %s HOST SOURCE_ISO OUTPUT_ISO [PASSWORD_FILE]\n' "$0" >&2
  exit 2
fi

readonly host="$1"
source_iso="$(realpath --canonicalize-existing "$2")"
readonly source_iso
output_iso="$(realpath --canonicalize-missing "$3")"
readonly output_iso
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
repository="$(git -C "$script_dir" rev-parse --show-toplevel)"
readonly repository
readonly versions="$repository/deployments/homelab/cloud/versions.yaml"
password_file=""

[[ "$host" =~ ^[a-z0-9-]+$ ]] || {
  printf 'invalid host name: %s\n' "$host" >&2
  exit 2
}
if [[ $# -eq 4 ]]; then
  password_file="$(realpath --canonicalize-existing "$4")"
  [[ -r "$password_file" ]] || {
    printf 'password file is not readable: %s\n' "$password_file" >&2
    exit 1
  }
fi
readonly password_file
[[ ! -e "$output_iso" ]] || {
  printf 'refusing to overwrite: %s\n' "$output_iso" >&2
  exit 1
}
case "$output_iso" in
  "$repository" | "$repository"/*)
    printf 'refusing to put a generated ISO in the repository\n' >&2
    exit 1
    ;;
esac

readarray -t iso_contract < <(
  python3 - "$versions" <<'PY'
import sys
import yaml

ubuntu = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))["host"]["ubuntu"]
print(ubuntu["iso"])
print(ubuntu["sha256"])
PY
)
readonly expected_name="${iso_contract[0]}"
readonly expected_sha256="${iso_contract[1]}"

[[ "$(basename -- "$source_iso")" == "$expected_name" ]] || {
  printf 'source ISO name must be %s\n' "$expected_name" >&2
  exit 1
}
actual_sha256="$(sha256sum "$source_iso" | cut -d ' ' -f 1)"
readonly actual_sha256
[[ "$actual_sha256" == "$expected_sha256" ]] || {
  printf 'source ISO checksum does not match versions.yaml\n' >&2
  exit 1
}

work_dir="$(mktemp -d)"
readonly work_dir
trap 'rm -rf -- "$work_dir"' EXIT
readonly rendered="$work_dir/$host-user-data.yaml"
readonly render_vars="$work_dir/render-vars.json"
readonly grub="$work_dir/grub.cfg"
readonly checksums="$work_dir/md5sum.txt"

python3 - "$work_dir" "$password_file" "$render_vars" <<'PY'
import json
import pathlib
import sys

output_directory, password_file, destination = sys.argv[1:]
variables = {"autoinstall_output_directory": output_directory}
if password_file:
    variables["autoinstall_password_file"] = password_file
pathlib.Path(destination).write_text(
    json.dumps(variables, sort_keys=True),
    encoding="utf-8",
)
PY

(
  cd "$script_dir"
  ansible-playbook playbooks/render-autoinstall.yml \
    --limit "$host" \
    --extra-vars "@$render_vars"
)
[[ -f "$rendered" ]] || {
  printf 'inventory host did not render an autoinstall profile: %s\n' "$host" >&2
  exit 1
}

xorriso -osirrox on -indev "$source_iso" \
  -extract /boot/grub/grub.cfg "$grub" \
  -extract /md5sum.txt "$checksums"
chmod 0600 "$grub" "$checksums"

python3 - "$rendered" "$grub" "$checksums" <<'PY'
import hashlib
import pathlib
import re
import sys
import yaml

rendered, grub_file, checksums_file = map(pathlib.Path, sys.argv[1:])
text = rendered.read_text(encoding="utf-8")
if any(
    token in text
    for token in (
        "{{", "}}", "{%", "%}", "__PASSWORD_HASH__", "__SSH_PUBLIC_KEY__"
    )
):
    raise SystemExit("rendered autoinstall data contains an unresolved template token")
document = yaml.safe_load(text)
autoinstall = document["autoinstall"]
password_hash = autoinstall["identity"]["password"]
authorized_keys = autoinstall["ssh"]["authorized-keys"]
if not password_hash.startswith("$6$"):
    raise SystemExit("rendered autoinstall data has an invalid password hash")
if len(authorized_keys) != 1 or not authorized_keys[0].startswith("ssh-ed25519 "):
    raise SystemExit("rendered autoinstall data has an invalid SSH public key")

grub = grub_file.read_text(encoding="utf-8")
grub, timeout_changes = re.subn(r"(?m)^set timeout=30$", "set timeout=3", grub)
grub, kernel_changes = re.subn(
    r"(?m)^(\s*linux\s+/casper/vmlinuz\s+)---\s*$",
    r"\1autoinstall ---",
    grub,
)
if timeout_changes != 1 or kernel_changes != 1:
    raise SystemExit("unexpected source ISO GRUB configuration")
grub_file.write_text(grub, encoding="utf-8")

checksums = [
    line
    for line in checksums_file.read_text(encoding="utf-8").splitlines()
    if not line.endswith("  ./boot/grub/grub.cfg")
    and not line.endswith("  ./autoinstall.yaml")
]
for path, destination in (
    (grub_file, "./boot/grub/grub.cfg"),
    (rendered, "./autoinstall.yaml"),
):
    checksums.append(f"{hashlib.md5(path.read_bytes()).hexdigest()}  {destination}")
checksums_file.write_text("\n".join(checksums) + "\n", encoding="utf-8")
PY

xorriso -indev "$source_iso" -outdev "$output_iso" \
  -map "$rendered" /autoinstall.yaml \
  -map "$grub" /boot/grub/grub.cfg \
  -map "$checksums" /md5sum.txt \
  -boot_image any replay
chmod 0600 "$output_iso"

mkdir "$work_dir/verify"
xorriso -osirrox on -indev "$output_iso" \
  -extract /autoinstall.yaml "$work_dir/verify/autoinstall.yaml" \
  -extract /boot/grub/grub.cfg "$work_dir/verify/grub.cfg" \
  -extract /md5sum.txt "$work_dir/verify/md5sum.txt"
cmp "$rendered" "$work_dir/verify/autoinstall.yaml"
cmp "$grub" "$work_dir/verify/grub.cfg"
cmp "$checksums" "$work_dir/verify/md5sum.txt"
xorriso -indev "$output_iso" -report_el_torito plain > "$work_dir/boot-report" 2>&1
grep -Eq 'El Torito boot img.*BIOS' "$work_dir/boot-report"
grep -Eq 'El Torito boot img.*UEFI' "$work_dir/boot-report"

printf '%s  %s\n' "$(sha256sum "$output_iso" | cut -d ' ' -f 1)" "$output_iso"
