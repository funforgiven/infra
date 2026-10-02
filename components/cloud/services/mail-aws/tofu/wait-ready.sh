#!/bin/sh
set -eu

# Check the replacement's temporary address before moving the retained EIP.
# This unauthenticated probe uses the IP, so hostname validation is not possible.
# The application probes validate the public hostname and TLS after cutover.
case "$MAIL_READY_IP" in
  ''|*[!0-9.]*) echo 'Invalid mail readiness address' >&2; exit 1 ;;
esac
payload="$(mktemp)"
headers="$(mktemp)"
trap 'rm -f "$payload" "$headers"' EXIT
attempt=0
while [ "$attempt" -lt 120 ]; do
  if wget -q -T 10 --no-check-certificate \
      --header='Host: mta-sts.fahrican.com' -O "$payload" \
      "https://$MAIL_READY_IP/.well-known/mta-sts.txt" 2>/dev/null \
      && grep -q '^version: STSv1' "$payload" \
      && grep -q '^mx: mail.fahrican.com' "$payload" \
      && wget -q -T 10 --no-check-certificate \
        --header='Host: mail.fahrican.com' -O "$payload" \
        "https://$MAIL_READY_IP/jmap/session" 2>/dev/null \
      && grep -q '"apiUrl":[[:space:]]*"https://mail.fahrican.com/jmap/"' "$payload"; then
    # Do not promote a registry restored without its private-admin policy.
    # wget exits nonzero on the expected 404, so inspect its status separately.
    wget -q -S -T 10 --no-check-certificate \
      --header='Host: mail.fahrican.com' -O /dev/null \
      "https://$MAIL_READY_IP/admin/" 2> "$headers" || true
    if grep -Eq '^[[:space:]]*HTTP/[0-9.]+ 404([[:space:]]|$)' "$headers"; then
      echo 'Replacement mail policy, public JMAP, and private admin boundary are ready for address cutover.'
      exit 0
    fi
  fi
  attempt=$((attempt + 1))
  sleep 10
done
echo 'Replacement mail server did not become ready; retained address stays on the previous host.' >&2
exit 1
