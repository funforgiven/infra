#!/usr/bin/with-contenv bash
# shellcheck shell=bash
# s6 runs this for every agent start, including backup-driven restarts.
set -euo pipefail
test -S /run/openthread-wpan0.sock
curl --fail --silent http://127.0.0.1:8081/node/state >/dev/null
if [ "${NAT64:-0}" != "0" ]; then
  # The minimal OTBR image does not include the sysctl executable.
  printf '1\n' > /proc/sys/net/ipv4/ip_forward
  ot-ctl nat64 enable | tr -d '\r' | grep -qx Done
  ot-ctl dns server upstream enable | tr -d '\r' | grep -qx Done
fi
