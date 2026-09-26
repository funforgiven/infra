#!/usr/bin/env bash
set -euo pipefail
umask 077
readonly source=/usr/local/lib/unifi
readarray -t release < <(python3 - <<'PY'
import json
with open('/usr/local/lib/unifi/inputs.json') as stream:
    data = json.load(stream)
print(data['url'])
print(data['sha256'])
print(data['version'])
PY
)
if [[ ! -e /var/lib/unifi-bootstrap-version ]]; then
  curl --fail --show-error --silent --location --proto '=https' --tlsv1.2 \
    "${release[0]}" -o /var/tmp/unifi-installer
  printf '%s  %s\n' "${release[1]}" /var/tmp/unifi-installer | sha256sum --check --status
  chmod 0700 /var/tmp/unifi-installer
  /var/tmp/unifi-installer --non-interactive --network-mode pasta --web-port 11443
  printf '%s\n' "${release[2]}" > /var/lib/unifi-bootstrap-version
  rm /var/tmp/unifi-installer
fi
"$source/renew-tls.sh"
cat > /etc/nginx/sites-available/unifi <<'NGINX'
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
server {
    listen 8443 ssl;
    server_name unifi-origin.internal;
    ssl_certificate /var/lib/unifi-proxy/tls/server.crt;
    ssl_certificate_key /var/lib/unifi-proxy/tls/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 1g;
    # Log status/latency at the existing Envoy gateway, without credential URLs.
    access_log off;
    location / {
        proxy_pass https://127.0.0.1:11443;
        proxy_ssl_verify off;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/unifi /etc/nginx/sites-enabled/unifi
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx qemu-guest-agent
systemctl reload nginx
install -d -m 0755 /var/lib/prometheus/node-exporter
cat > /etc/default/prometheus-node-exporter <<'NODE'
ARGS="--collector.systemd --collector.textfile.directory=/var/lib/prometheus/node-exporter"
NODE
systemctl restart prometheus-node-exporter
for name in backup health renew-tls; do
  cat > "/etc/systemd/system/unifi-$name.service" <<UNIT
[Unit]
Description=UniFi $name
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
UMask=0077
ExecStart=$source/$name.sh
UNIT
done
cat > /etc/systemd/system/unifi-backup.timer <<'UNIT'
[Unit]
Description=Daily encrypted UniFi controller backup
[Timer]
OnCalendar=*-*-* 02:00:00 UTC
RandomizedDelaySec=30m
Persistent=true
[Install]
WantedBy=timers.target
UNIT
cat > /etc/systemd/system/unifi-health.timer <<'UNIT'
[Timer]
OnBootSec=2m
OnUnitActiveSec=1m
[Install]
WantedBy=timers.target
UNIT
cat > /etc/systemd/system/unifi-renew-tls.timer <<'UNIT'
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now unifi-health.timer unifi-renew-tls.timer unifi-backup.timer
# The only API credential is a local Limited Admin with Network Read Only.
# A separate enrollment step supplies its root-owned environment file.
cat > /etc/systemd/system/unifi-poller.service <<'UNIT'
[Unit]
Description=Read-only UniFi AP metrics
After=network-online.target uosserver.service
Wants=network-online.target
ConditionPathExists=/var/lib/unifi-poller/environment
[Service]
Restart=on-failure
RestartSec=15
ExecStart=/usr/bin/podman run --rm --name unifi-poller --network host --user 65534:65534 --cap-drop ALL --read-only --security-opt no-new-privileges --env-file /var/lib/unifi-poller/environment --env UP_INFLUXDB_DISABLE=true --env UP_PROMETHEUS_NAMESPACE=unifi --env UP_UNIFI_DEFAULT_URL=https://127.0.0.1:11443 --env UP_UNIFI_DEFAULT_VERIFY_SSL=false --env UP_UNIFI_DEFAULT_SAVE_DPI=false --env UP_UNIFI_DEFAULT_HASH_PII=true --env UP_PROMETHEUS_HTTP_LISTEN=0.0.0.0:9130 ghcr.io/unpoller/unpoller:v2.21.0@sha256:a08b532be181256318211b6170691e316d29ac04575bc54d59620189953f03aa
ExecStop=/usr/bin/podman stop --time 20 unifi-poller
TimeoutStartSec=180
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now unifi-poller.service
