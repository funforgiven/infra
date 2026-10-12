#!/bin/bash
set -euo pipefail
umask 022

# The image creates valheim as UID 0; Kubernetes runs this workload as UID 1000.
# PlayFab dereferences getpwuid(getuid()) during native plugin initialization,
# even with the Steam backend. Preserve the image's other system accounts.
awk -F: '$1 != "valheim" && $3 != 1000' /etc/passwd > /identity/passwd
printf '%s\n' 'valheim:x:1000:1000:Valheim server:/data/home:/usr/sbin/nologin' \
  >> /identity/passwd
awk -F: '$1 != "valheim" && $3 != 1000' /etc/group > /identity/group
printf '%s\n' 'valheim:x:1000:' >> /identity/group
