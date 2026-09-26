#!/usr/bin/env bash
set -euo pipefail
readonly directory=/var/lib/prometheus/node-exporter
install -d -m 0755 "$directory"
service_up=0
https_up=0
systemctl is-active --quiet uosserver && service_up=1
# Only the VM's loopback hop uses UniFi's native self-signed certificate.
# All network-facing admin traffic uses the verified origin TLS endpoint.
curl --insecure --silent --fail --max-time 10 --output /dev/null \
  https://127.0.0.1:11443/ && https_up=1
expiry=$(openssl x509 -enddate -noout -in /var/lib/unifi-proxy/tls/server.crt)
expiry=$(date --date="${expiry#notAfter=}" +%s)
{
  printf 'unifi_service_up %s\n' "$service_up"
  printf 'unifi_https_up %s\n' "$https_up"
  printf 'unifi_origin_certificate_expiry_timestamp_seconds %s\n' "$expiry"
  printf 'unifi_health_last_run_timestamp_seconds %s\n' "$(date +%s)"
} > "$directory/unifi-health.prom.new"
chmod 0644 "$directory/unifi-health.prom.new"
mv "$directory/unifi-health.prom.new" "$directory/unifi-health.prom"
