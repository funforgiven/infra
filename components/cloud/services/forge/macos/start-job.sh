#!/bin/bash
# Immutable root launch daemon: reads only a one-job identity from local media,
# executes the fixed runner script as the non-administrator user, then powers off.
set -eu
umask 077
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
[ "$(id -u)" -eq 0 ]
for _attempt in $(seq 1 60); do
  # Disk Arbitration does not automatically mount removable media before a
  # console login. This sealed guest never logs in an administrator.
  /usr/local/bin/node /usr/local/libexec/forge/mount-job.js
  [ -f /Volumes/FORGEJOB/enrollment.json ] && break
  sleep 5
done
# Image maintenance boots have no enrollment ISO and must remain usable.
[ -f /Volumes/FORGEJOB/enrollment.json ] || { echo 'No enrollment media found; maintenance boot.'; exit 0; }
echo 'Found read-only enrollment media; starting the unprivileged runner.'
[ ! -e /Users/forge-job/forge-job ] || exit 1
# The sealed Node binary handles JSON without shell evaluation. All input is
# bounded and each field is a string, never a command or filesystem path.
/usr/local/bin/node /usr/local/libexec/forge/enroll-job.js
chown -R forge-job:staff /Users/forge-job/forge-job
set +e
su -l forge-job -c /usr/local/libexec/forge/run-job.sh
result=$?
set -e
printf 'Forgejo native job runner exited: %s\n' "$result"
/sbin/shutdown -h now
