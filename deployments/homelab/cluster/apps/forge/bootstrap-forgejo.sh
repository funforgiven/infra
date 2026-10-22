#!/bin/sh
set -eu
umask 077
mkdir -p "${GITEA_TEMP:-/tmp/gitea}" /var/lib/gitea/custom/conf /var/lib/gitea/git
# forgejo.ini reads secrets through *_URI files. [metrics] TOKEN has no URI
# form, so Forgejo's own environment-to-ini adds it to the generated app.ini.
FORGEJO__metrics__TOKEN__FILE=/run/forge-secrets/forgejo-metrics-token \
  /usr/local/bin/environment-to-ini --config /bootstrap/forgejo.ini \
  --out /var/lib/gitea/custom/conf/app.ini
forgejo() { /app/gitea/gitea --config /var/lib/gitea/custom/conf/app.ini "$@"; }
forgejo migrate
if ! forgejo admin user list | awk '$2 == "forge-admin" { found = 1 } END { exit !found }'; then
  forgejo admin user create --username forge-admin --admin \
    --email forge-admin@fahrican.com \
    --password "$(cat /run/forge-secrets/forgejo-admin-password)" \
    --must-change-password=false
fi
auth_id=$(forgejo admin auth list | awk '$2 == "ZITADEL" { print $1 }')
# Forgejo 15.0.7 claimValueToStringSet uses fmt.Sprintf("%s", value),
# including boolean OIDC claims. Match Go's exact representation of true;
# false and a missing claim still fail closed. Recheck on Forgejo upgrades.
set -- --name ZITADEL --provider openidConnect \
  --key "$(cat /run/forge-secrets/forgejo-oidc-client-id)" \
  --secret "$(cat /run/forge-secrets/forgejo-oidc-client-secret)" \
  --auto-discover-url https://auth.cloud.fahrican.com/.well-known/openid-configuration \
  --scopes openid --scopes email --scopes profile --skip-local-2fa \
  --required-claim-name email_verified --required-claim-value '%!s(bool=true)'
if test -n "$auth_id"; then
  forgejo admin auth update-oauth --id "$auth_id" "$@"
else
  forgejo admin auth add-oauth "$@"
fi
