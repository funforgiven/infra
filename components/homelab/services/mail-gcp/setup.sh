#!/bin/bash
# GCE Debian 13 startup. Only non-secret inputs are stored in instance metadata.
set -euo pipefail
umask 022
metadata() {
  curl -fsS --retry 5 -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}
project=$(metadata mail-project)
instance=$(metadata mail-sql)
db_user=$(metadata mail-db-user)
bucket=$(metadata mail-bucket)

export DEBIAN_FRONTEND=noninteractive
if [[ ! -e /swapfile ]]; then
  install -m 600 /dev/null /swapfile
  fallocate -l 2G /swapfile
  mkswap /swapfile
fi
swapon --show=NAME --noheadings | grep -qx /swapfile || swapon /swapfile
apt-get -o Acquire::Retries=4 update -qq
apt-get -o Acquire::Retries=4 install -y --no-install-recommends postgresql-client-17 restic ca-certificates curl xz-utils
# The Google Debian image includes a loopback Exim listener. Stalwart needs
# exclusive ownership of port 25 on both loopback and the public interface.
systemctl mask --now exim4.service
getent passwd stalwart >/dev/null || useradd --system --user-group --create-home --home-dir /var/lib/stalwart stalwart
install -d -m 700 -o stalwart -g stalwart /var/lib/stalwart
install -d -m 700 /var/lib/mail-operations
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
binary() {
  local name=$1 url=$2 digest=$3
  if [[ -x /usr/local/bin/$name && -f /usr/local/lib/mail/"$name".digest ]] &&
     grep -Fxq "$digest" "/usr/local/lib/mail/$name.digest"; then return; fi
  curl -fsSL --retry 5 "$url" -o "$tmp/download"
  echo "$digest  $tmp/download" | sha256sum --check --status
  if [[ $name == cloud-sql-proxy ]]; then
    install -m755 "$tmp/download" "/usr/local/bin/$name"
  else
    tar -xf "$tmp/download" -C "$tmp"
    install -m755 "$(find "$tmp" -type f -name "$name" -print -quit)" "/usr/local/bin/$name"
  fi
  echo "$digest" >"/usr/local/lib/mail/$name.digest"
}

binary cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.28.0/cloud-sql-proxy.linux.amd64 c01a2dc25c5ec6441fb05fe2d23e51e5290b3c06cc56f5e9c749806f335bd82e
cat >/etc/systemd/system/mail-sql.service <<UNIT
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
DynamicUser=yes
ExecStart=/usr/local/bin/cloud-sql-proxy --private-ip --auto-iam-authn --address=127.0.0.1 --port=5432 $instance
Restart=always
RestartSec=5
NoNewPrivileges=yes
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/mail-runtime.env <<ENV
MAIL_GCP_PROJECT=$project
MAIL_DB_USER=$db_user
MAIL_BLOB_BUCKET=$bucket
ENV
systemctl daemon-reload
systemctl enable --now mail-sql.service
[[ $(metadata mail-runtime) == true ]] || exit 0

binary stalwart https://github.com/stalwartlabs/stalwart/releases/download/v0.16.24/stalwart-x86_64-unknown-linux-musl.tar.gz 00464cd689941c2988ca832ad791fd829efe4edd17422013d1077006d6aee4b4
binary stalwart-cli https://github.com/stalwartlabs/cli/releases/download/v1.0.13/stalwart-cli-x86_64-unknown-linux-musl.tar.xz 689644a491c298b4916714a93a2a249ee2ea70f2f2c054991658c3e8f0f27c13
binary vandelay https://github.com/stalwartlabs/vandelay/releases/download/v1.0.12/vandelay-x86_64-unknown-linux-musl.tar.gz 993b1cc13c7f7d9467dcded6c8131786987ac9c3ec468d2d835194c1e120d970

cat >/etc/systemd/system/mail-secrets.service <<'UNIT'
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
EnvironmentFile=/etc/mail-runtime.env
ExecStart=/usr/bin/python3 /usr/local/lib/mail/mail-configure secrets
RemainAfterExit=yes
UMask=0077
UNIT
cat >/etc/systemd/system/stalwart.service <<'UNIT'
[Unit]
After=network-online.target mail-sql.service mail-secrets.service
Requires=mail-sql.service mail-secrets.service
StartLimitIntervalSec=0
[Service]
User=stalwart
Group=stalwart
EnvironmentFile=/etc/mail-runtime.env
WorkingDirectory=/var/lib/stalwart
ExecStartPre=/usr/bin/python3 /usr/local/lib/mail/mail-configure registry
ExecStart=/usr/local/bin/stalwart --config /var/lib/stalwart/config.json
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/stalwart
PrivateTmp=yes
UMask=0077
TimeoutStartSec=4min
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/mail-operations@.service <<'UNIT'
[Unit]
After=stalwart.service
[Service]
Type=oneshot
EnvironmentFile=/etc/mail-runtime.env
Environment=XDG_CACHE_HOME=/var/lib/mail-operations/cache
ExecStart=/usr/bin/python3 /usr/local/lib/mail/mail-operations %i
UMask=0077
PrivateTmp=yes
NoNewPrivileges=yes
TimeoutStartSec=2h
UNIT
timer() {
  local action=$1 calendar=$2 delay=$3
  cat >"/etc/systemd/system/mail-$action.timer" <<UNIT
[Timer]
Unit=mail-operations@$action.service
OnCalendar=$calendar
OnActiveSec=$delay
RandomizedDelaySec=30s
Persistent=true
[Install]
WantedBy=timers.target
UNIT
}
timer backup '*-*-* 02:10:00 UTC' 6min
timer restore-check 'Sun *-*-* 04:10:00 UTC' 12min
timer canary '*:07,37' 4min
timer health '*:0/5' 2min
install -d /etc/systemd/system/mail-operations@canary.service.d
cat >/etc/systemd/system/mail-operations@canary.service.d/phase.conf <<'UNIT'
[Service]
ExecCondition=/bin/bash -o pipefail -c 'curl -fsS -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/mail-monitor | grep -qx true'
UNIT
systemctl daemon-reload
systemctl enable --now stalwart.service
systemctl enable --now mail-health.timer mail-canary.timer mail-backup.timer mail-restore-check.timer
