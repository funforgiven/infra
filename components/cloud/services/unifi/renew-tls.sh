#!/usr/bin/env bash
set -euo pipefail
umask 077
readonly tls=/var/lib/unifi-proxy/tls
install -d -m 0700 "$tls"
# A VM-local CA signs only this origin. Its PUBLIC certificate is enrolled in
# Git over verified SSH; CA and leaf keys never enter user-data or Terraform.
if [[ ! -s "$tls/ca.key" ]]; then
  openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 3650 \
    -subj '/CN=Homelab UniFi origin CA' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -keyout "$tls/ca.key" -out "$tls/ca.crt"
fi
if [[ -s "$tls/server.crt" ]] && openssl x509 -checkend 2592000 -noout -in "$tls/server.crt"; then
  exit 0
fi
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -subj '/CN=unifi-origin.internal' \
  -keyout "$tls/server.key.new" -out "$tls/server.csr"
cat > "$tls/extensions.cnf" <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:unifi-origin.internal
EXT
openssl x509 -req -sha256 -days 90 -in "$tls/server.csr" \
  -CA "$tls/ca.crt" -CAkey "$tls/ca.key" -CAcreateserial \
  -extfile "$tls/extensions.cnf" -out "$tls/server.crt.new"
openssl verify -CAfile "$tls/ca.crt" -verify_hostname unifi-origin.internal "$tls/server.crt.new"
mv "$tls/server.key.new" "$tls/server.key"
mv "$tls/server.crt.new" "$tls/server.crt"
if systemctl is-active --quiet nginx; then
  nginx -t
  systemctl reload nginx
fi
