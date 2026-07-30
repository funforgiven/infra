#!/usr/bin/env bash

set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)

if ! python3 -c 'import paramiko' >/dev/null 2>&1; then
  if [[ -n ${IN_NIX_SHELL:-} ]]; then
    echo "Paramiko is unavailable in the current Nix development shell" >&2
    exit 1
  fi

  exec nix develop "$repo_root" --accept-flake-config \
    -c "$repo_root/components/routeros/validate.sh"
fi

router_config="$repo_root/deployments/homelab/routeros/core-router/applied/2026-07-27-factory-bootstrap.rsc"
router_activation_config="$repo_root/deployments/homelab/routeros/core-router/applied/2026-07-27-activation.rsc"
router_legacy_lan_config="$repo_root/deployments/homelab/routeros/core-router/applied/2026-07-27-legacy-lan.rsc"
router_lan_bridge_config="$repo_root/deployments/homelab/routeros/core-router/applied/2026-07-29-lan-bridge-correction.rsc"
switch_config="$repo_root/deployments/homelab/routeros/core-switch/applied/2026-07-27-factory-bootstrap.rsc"
switch_activation_config="$repo_root/deployments/homelab/routeros/core-switch/applied/2026-07-27-activation.rsc"
pppoe_credentials_entrypoint="$repo_root/deployments/homelab/routeros/core-router/install-pppoe.sh"
pppoe_credentials_helper="$repo_root/components/routeros/install_pppoe_credentials.py"
pppoe_credentials_tests="$repo_root/components/routeros/test_install_pppoe_credentials.py"

for executable in \
  "$pppoe_credentials_entrypoint" \
  "$pppoe_credentials_helper" \
  "$repo_root/components/routeros/validate.sh"; do
  if [[ ! -x $executable ]]; then
    echo "required RouterOS tool is not executable: ${executable#"$repo_root"/}" >&2
    exit 1
  fi
done

expected_configs=(
  "$router_config"
  "$router_activation_config"
  "$router_legacy_lan_config"
  "$router_lan_bridge_config"
  "$switch_config"
  "$switch_activation_config"
)

mapfile -t actual_configs < <(
  find "$repo_root/deployments/homelab/routeros" \
    -type f -name '*.rsc' -print |
    sort
)

if (( ${#actual_configs[@]} != ${#expected_configs[@]} )); then
  echo "expected exactly six applied RouterOS records" >&2
  exit 1
fi

for config in "${expected_configs[@]}"; do
  if [[ ! -f $config ]]; then
    echo "missing expected RouterOS record: ${config#"$repo_root"/}" >&2
    exit 1
  fi

  if [[ $(sed -n '1p' "$config") != "# APPLIED "*'not a live convergence script.' ]] ||
    [[ $(sed -n '2p' "$config") != "# Do not import this file into the configured "*'.' ]]; then
    echo "RouterOS record lacks an explicit applied/do-not-import header: ${config#"$repo_root"/}" >&2
    exit 1
  fi

  if [[ $(sed -n '3p' "$config") != ':error "infra: archived applied record; import refused"' ]]; then
    echo "RouterOS record lacks an unconditional import guard: ${config#"$repo_root"/}" >&2
    exit 1
  fi
done

if ! diff -u \
  <(printf '%s\n' "${expected_configs[@]}" | sort) \
  <(printf '%s\n' "${actual_configs[@]}") \
  >/dev/null; then
  echo "RouterOS records exist outside the explicit device-scoped inventory" >&2
  exit 1
fi

if find \
  "$repo_root/components/routeros" \
  "$repo_root/deployments/homelab/routeros" \
  -type f -name '*.rsc.in' -print -quit |
  rg --quiet .; then
  echo "obsolete RouterOS template files remain" >&2
  exit 1
fi

if find "$repo_root/deployments/homelab/routeros" \
  -maxdepth 1 -type f -name '*.sh' -print -quit |
  rg --quiet .; then
  echo "ambiguous flat RouterOS shell entrypoints remain" >&2
  exit 1
fi

temporary_directory=$(mktemp -d)
trap 'rm -rf -- "$temporary_directory"' EXIT

if command -v shellcheck >/dev/null; then
  shellcheck \
    "$repo_root/components/routeros/validate.sh" \
    "$pppoe_credentials_entrypoint"
fi

if rg --ignore-case --quiet \
  '(user|password|secret|preshared-key|private-key)[[:space:]]*=|BEGIN [A-Z ]*PRIVATE KEY' \
  "${expected_configs[@]}"; then
  echo "applied RouterOS record contains a credential or private key" >&2
  exit 1
fi

if rg --pcre2 --ignore-case --quiet \
  "^[[:space:]]*[A-Z0-9_]*(password|secret|token|private_key|preshared_key)[A-Z0-9_]*[[:space:]]*(?::[^=]+)?=[[:space:]]*[\"'][^\"']+[\"']" \
  "$repo_root/components/routeros" \
  "$repo_root/deployments/homelab/routeros" \
  --glob '*.py' \
  --glob '!test_*.py'; then
  echo "RouterOS Python source contains a hard-coded credential-like value" >&2
  exit 1
fi

if rg --quiet '@@[A-Z][A-Z0-9_]*@@' "${expected_configs[@]}"; then
  echo "applied RouterOS record contains an unresolved placeholder" >&2
  exit 1
fi

if rg --quiet --fixed-strings '.env' \
  "$repo_root/components/routeros" \
  "$pppoe_credentials_entrypoint" \
  --glob '*.py' \
  --glob '*.sh' \
  --glob '!validate.sh'; then
  echo "active RouterOS tooling still depends on a .env file" >&2
  exit 1
fi

PYTHONPYCACHEPREFIX="$temporary_directory/pycache" \
  python3 -m py_compile \
  "$pppoe_credentials_helper" \
  "$pppoe_credentials_tests"
PYTHONPATH="$repo_root/components/routeros" \
  PYTHONPYCACHEPREFIX="$temporary_directory/pycache" \
  python3 -m unittest discover \
  -s "$repo_root/components/routeros" \
  -p 'test_*.py'

rg --quiet 'router_host=\$\{1:-192\.168\.1\.1\}' "$pppoe_credentials_entrypoint"
rg --quiet --fixed-strings \
  '$repo_root/components/routeros/install_pppoe_credentials.py' \
  "$pppoe_credentials_entrypoint"
rg --quiet --fixed-strings \
  -- \
  '--pppoe-username-file /run/secrets/homelab-routeros-pppoe-username' \
  "$pppoe_credentials_entrypoint"
rg --quiet --fixed-strings \
  -- \
  '--pppoe-password-file /run/secrets/homelab-routeros-pppoe-password' \
  "$pppoe_credentials_entrypoint"
rg --quiet \
  -- '--fingerprint SHA256:[A-Za-z0-9+/]{43}$' \
  "$pppoe_credentials_entrypoint"

if rg --quiet -- '--env-file|192\.168\.1\.175' "$pppoe_credentials_entrypoint"; then
  echo "PPPoE credential installer uses a retired environment file or router address" >&2
  exit 1
fi

rg --quiet 'interface="ether1".*vlan-id=35|interface=ether1.*vlan-id=35' "$router_config"
rg --quiet 'name=pppoe-turknet.*disabled=yes|disabled=yes.*name=pppoe-turknet' "$router_config"
rg --quiet 'TurkNet PPPoE; credentials pending' "$router_config"
rg --quiet 'pool-servers-bootstrap ranges=10\.21\.20\.100-10\.21\.20\.127' "$router_config"
rg --quiet 'PPPoE masquerade.*disabled=yes|disabled=yes.*PPPoE masquerade' "$router_config"
rg --quiet 'address="?192\.168\.88\.1/24"?.*interface="ether15"|interface="ether15".*address="?192\.168\.88\.1/24"?' "$router_config"
rg --quiet 'activate input policy.*disabled=yes|disabled=yes.*activate input policy' "$router_config"
rg --quiet 'activate forward policy.*disabled=yes|disabled=yes.*activate forward policy' "$router_config"
rg --quiet 'activate IPv6 input policy.*disabled=yes|disabled=yes.*activate IPv6 input policy' "$router_config"
rg --quiet 'activate IPv6 forward policy.*disabled=yes|disabled=yes.*activate IPv6 forward policy' "$router_config"
rg --quiet 'interface=wan-vlan35.*list=INFRA-WAN|list=INFRA-WAN.*interface=wan-vlan35' "$router_config"
rg --quiet 'tagged trunk to TP-Link port1' "$router_config"

for vlan_id in 10 20 50 60; do
  if ! rg --quiet \
    "/interface vlan add .*disabled=yes.*vlan-id=${vlan_id}([^0-9]|$)" \
    "$router_config"; then
    echo "client VLAN $vlan_id is active during staging" >&2
    exit 1
  fi
done

if rg --pcre2 --quiet '/ip dhcp-server add(?![^\n]*disabled=yes)' "$router_config"; then
  echo "a DHCP server is active during staging" >&2
  exit 1
fi

if rg --quiet '^/ip dns set ' "$router_config"; then
  echo "staged router configuration changes global DNS" >&2
  exit 1
fi

if rg --quiet 'name=(LAN|WAN|MGMT)([^A-Z-]|$)|list=(LAN|WAN|MGMT)([^A-Z-]|$)' "$router_config"; then
  echo "staged router configuration uses a non-namespaced interface list" >&2
  exit 1
fi

if rg --quiet '/interface vlan .*vlan-id=(30|40|70|80|999)([^0-9]|$)' "$router_config"; then
  echo "CCR configuration routes a reserved or switch-local VLAN" >&2
  exit 1
fi

rg --quiet 'default-route-distance=1.*name="pppoe-turknet"|name="pppoe-turknet".*default-route-distance=1' "$router_activation_config"
rg --quiet '/ppp profile set .*name="turknet".*change-tcp-mss=yes.*use-ipv6=no' "$router_activation_config"
rg --quiet 'PPPoE username is missing' "$router_activation_config"
rg --quiet 'TurkNet PPPoE; credentials installed' "$router_activation_config"
rg --quiet 'default-route-distance=10.*interface="sfp-sfpplus1"|interface="sfp-sfpplus1".*default-route-distance=10' "$router_activation_config"
rg --quiet 'name="pppoe-turknet".*use-peer-dns=no|use-peer-dns=no.*name="pppoe-turknet"' "$router_activation_config"
rg --quiet 'interface="sfp-sfpplus1".*use-peer-dns=no|use-peer-dns=no.*interface="sfp-sfpplus1"' "$router_activation_config"
rg --quiet '/ip dns set .*allow-remote-requests=yes.*servers=1\.1\.1\.1|/ip dns set .*servers=1\.1\.1\.1.*allow-remote-requests=yes' "$router_activation_config"
rg --quiet 'infra: primary admin workstation.*mac-address=60:CF:84:ED:E9:1E|mac-address=60:CF:84:ED:E9:1E.*infra: primary admin workstation' "$router_activation_config"
rg --quiet 'infra: input rollback admin' "$router_activation_config"
rg --quiet 'interface="sfp-sfpplus1".*list=INFRA-WAN|list=INFRA-WAN.*interface="sfp-sfpplus1"' "$router_activation_config"
rg --quiet '/ip firewall filter enable .*infra: activate input policy' "$router_activation_config"
rg --quiet '/ip firewall filter enable .*infra: activate forward policy' "$router_activation_config"
rg --quiet '/ipv6 firewall filter enable .*infra: activate IPv6 input policy' "$router_activation_config"
rg --quiet '/ipv6 firewall filter enable .*infra: activate IPv6 forward policy' "$router_activation_config"
rg --quiet 'IPv6 input final drop' "$router_activation_config"
rg --quiet 'IPv6 forward final drop' "$router_activation_config"
rg --quiet '/ipv6 settings set accept-router-advertisements=no' "$router_activation_config"
rg --quiet '/ip firewall nat enable .*infra: PPPoE masquerade' "$router_activation_config"
rg --quiet '/interface pppoe-client enable .*pppoe-turknet' "$router_activation_config"
rg --quiet 'discover-interface-list=INFRA-MAC-MGMT' "$router_activation_config"
rg --quiet 'tagged trunk to TP-Link port1' "$router_activation_config"

if rg --quiet 'TP-Link port7' "$router_config" "$router_activation_config"; then
  echo "CCR configuration still targets TP-Link port 7" >&2
  exit 1
fi

rg --quiet 'LAN trunk must be physically disconnected' "$router_legacy_lan_config"
rg --quiet 'address=192\.168\.1\.1/24.*disabled=yes.*interface="ether16"|disabled=yes.*interface="ether16".*address=192\.168\.1\.1/24' "$router_legacy_lan_config"
rg --quiet 'name=pool-legacy ranges=192\.168\.1\.50-192\.168\.1\.99|name="pool-legacy".*ranges=192\.168\.1\.50-192\.168\.1\.99' "$router_legacy_lan_config"
rg --quiet 'name=dhcp-legacy.*disabled=yes.*interface="ether16"|disabled=yes.*interface="ether16".*name=dhcp-legacy' "$router_legacy_lan_config"
rg --quiet 'address=192\.168\.1\.0/24.*dns-server=192\.168\.1\.1.*domain=internal.*gateway=192\.168\.1\.1' "$router_legacy_lan_config"
rg --quiet 'address=192\.168\.1\.197.*mac-address=60:CF:84:ED:E9:1E.*server=dhcp-legacy' "$router_legacy_lan_config"
rg --quiet 'address=192\.168\.1\.189.*mac-address=98:25:4A:CB:BF:BE.*server=dhcp-legacy' "$router_legacy_lan_config"
rg --quiet 'address=192\.168\.1\.163.*mac-address=9C:A2:F4:C2:ED:74.*server=dhcp-legacy' "$router_legacy_lan_config"
rg --quiet 'address=192\.168\.1\.121.*mac-address=EC:B5:FA:8E:DB:63.*server=dhcp-legacy' "$router_legacy_lan_config"
rg --quiet 'interface="ether16".*list="INFRA-LAN"|interface="ether16".*list=INFRA-LAN' "$router_legacy_lan_config"
rg --quiet 'address="192\.168\.1\.0/24".*list="INFRA-LAN-NAT"|address=192\.168\.1\.0/24.*list=INFRA-LAN-NAT' "$router_legacy_lan_config"
rg --quiet 'infra: input legacy admin.*in-interface="ether16".*src-address=192\.168\.1\.197' "$router_legacy_lan_config"
rg --quiet 'infra: legacy LAN to PPPoE.*in-interface="ether16".*out-interface=pppoe-turknet.*src-address=192\.168\.1\.0/24' "$router_legacy_lan_config"
rg --quiet 'infra: temporary Minecraft TCP.*dst-port=25565.*in-interface=pppoe-turknet.*protocol=tcp.*to-addresses=192\.168\.1\.197.*to-ports=25565' "$router_legacy_lan_config"
rg --quiet 'infra: temporary Minecraft UDP.*dst-port=25565.*in-interface=pppoe-turknet.*protocol=udp.*to-addresses=192\.168\.1\.197.*to-ports=25565' "$router_legacy_lan_config"
rg --quiet '/ip dhcp-client disable .*interface="sfp-sfpplus1"' "$router_legacy_lan_config"
rg --quiet '/interface list member remove .*interface="sfp-sfpplus1".*list="INFRA-WAN"' "$router_legacy_lan_config"
rg --quiet 'name="infra-legacy-cutover-watch".*interval=5s|interval=5s.*name="infra-legacy-cutover-watch"' "$router_legacy_lan_config"
rg --quiet '/ip address enable .*temporary legacy LAN gateway' "$router_legacy_lan_config"
rg --quiet '/ip dhcp-server enable .*name="dhcp-legacy"' "$router_legacy_lan_config"
rg --quiet '/ip dns set .*allow-remote-requests=yes.*servers=1\.1\.1\.1|/ip dns set .*servers=1\.1\.1\.1.*allow-remote-requests=yes' "$router_legacy_lan_config"

if rg --quiet 'legacy LAN to (TRUSTED|SERVERS|IOT|GUEST)' "$router_legacy_lan_config"; then
  echo "temporary legacy LAN unexpectedly reaches a deployment VLAN" >&2
  exit 1
fi

rg --quiet 'future Omada trunk must be physically disconnected' "$router_lan_bridge_config"
rg --quiet 'current Omada trunk is not running' "$router_lan_bridge_config"
rg --quiet 'name="bridge10-trusted-access".*protocol-mode=none.*vlan-filtering=yes|protocol-mode=none.*name="bridge10-trusted-access".*vlan-filtering=yes' "$router_lan_bridge_config"
rg --quiet '/ip dhcp-server disable .*name="dhcp1".*interface="ether15"' "$router_lan_bridge_config"
rg --quiet 'admin-mac=\[/interface ethernet get .*default-name="ether16".*mac-address\]' "$router_lan_bridge_config"
rg --quiet 'name="bridge-lan".*protocol-mode=rstp.*vlan-filtering=yes|protocol-mode=rstp.*name="bridge-lan".*vlan-filtering=yes' "$router_lan_bridge_config"
rg --quiet 'bridge="bridge-lan".*edge=no.*hw=no.*interface="ether15"|bridge="bridge-lan".*interface="ether15".*hw=no' "$router_lan_bridge_config"
rg --quiet 'bridge="bridge-lan".*edge=yes.*hw=no.*interface="ether16"|bridge="bridge-lan".*interface="ether16".*hw=no' "$router_lan_bridge_config"
rg --quiet 'handoff native legacy LAN.*untagged="bridge-lan,ether15,ether16".*vlan-ids=1' "$router_lan_bridge_config"

for vlan_id in 10 20 50 60 90; do
  rg --quiet \
    "tagged=\"bridge-lan,ether15,ether16\".*vlan-ids=${vlan_id}([^0-9]|$)" \
    "$router_lan_bridge_config"
done

for vlan_name in vlan10-trusted vlan20-servers vlan50-iot vlan60-guest vlan90-mgmt; do
  rg --quiet \
    "\"${vlan_name}\".*interface=\"bridge-lan\"|name=\"${vlan_name}\".*interface=\"bridge-lan\"" \
    "$router_lan_bridge_config"
done

rg --quiet '/ip address set .*address="192\.168\.1\.1/24".*interface="ether16".*interface="bridge-lan"' "$router_lan_bridge_config"
rg --quiet '/ip dhcp-server set .*name="dhcp-legacy".*interface="bridge-lan"' "$router_lan_bridge_config"
rg --quiet 'interface="bridge-lan".*list=INFRA-LAN|list=INFRA-LAN.*interface="bridge-lan"' "$router_lan_bridge_config"
rg --quiet '/ip address set .*address="10\.21\.10\.1/24".*interface="bridge10-trusted-access".*interface=vlan10-trusted' "$router_lan_bridge_config"
rg --quiet '/ip dhcp-server set .*name="dhcp-trusted".*interface=vlan10-trusted' "$router_lan_bridge_config"
rg --quiet 'bridge MAC does not preserve the legacy gateway MAC' "$router_lan_bridge_config"
rg --quiet 'factory DHCP server is not safely disabled' "$router_lan_bridge_config"

for rule_comment in \
  'infra: input legacy admin' \
  'infra: legacy admin to MGMT' \
  'infra: legacy LAN to PPPoE'; do
  rg --fixed-strings --quiet \
    "/ip firewall filter set [find where comment=\"${rule_comment}\"] in-interface=\"bridge-lan\"" \
    "$router_lan_bridge_config"
done

for rule_comment in \
  'infra: input admin' \
  'infra: admin to MGMT' \
  'infra: TRUSTED to WAN' \
  'infra: TRUSTED to SERVERS' \
  'infra: TRUSTED to IOT'; do
  rg --fixed-strings --quiet \
    "/ip firewall filter set [find where comment=\"${rule_comment}\"] in-interface=vlan10-trusted" \
    "$router_lan_bridge_config"
done

if rg --quiet \
  '^/interface pppoe-client (set|disable|remove)|^/ppp profile (set|disable|remove)|^/ip firewall nat (set|disable|remove)|^/ip dns set |infra-lan-role-cutover' \
  "$router_lan_bridge_config"; then
  echo "LAN bridge transition mutates PPPoE, NAT, DNS, or installs an unsafe link-state watcher" >&2
  exit 1
fi

if rg --quiet 'vlan-ids=[^[:space:]]*(30|40|70|80|999)' "$router_lan_bridge_config"; then
  echo "LAN bridge transition configures a switch-local or reserved VLAN" >&2
  exit 1
fi

for vlan_name in vlan10-trusted vlan20-servers vlan50-iot vlan60-guest vlan90-mgmt; do
  if ! rg --quiet \
    "/interface vlan set .*name=\"${vlan_name}\".*disabled=no" \
    "$router_activation_config"; then
    echo "VLAN $vlan_name is not enabled by activation" >&2
    exit 1
  fi
done

for dhcp_name in dhcp-trusted dhcp-servers-bootstrap dhcp-iot dhcp-guest; do
  rg --quiet "/ip dhcp-server enable .*name=\"${dhcp_name}\"" "$router_activation_config"
done

if rg --quiet '/interface vlan .*vlan-id=(30|40|70|80|999)([^0-9]|$)' "$router_activation_config"; then
  echo "CCR activation routes a reserved or switch-local VLAN" >&2
  exit 1
fi

rg --quiet 'vlan-filtering=no' "$switch_config"
rg --quiet 'transition native VLAN 1.*vlan-ids=1|vlan-ids=1.*transition native VLAN 1' "$switch_config"
rg --quiet '^/interface bridge vlan add bridge=bridge comment="infra: CEPH; switch-local only" tagged=bond-server1,bond-server2,bond-server3 vlan-ids=30$' "$switch_config"
rg --quiet 'name=bond-server1.*disabled=yes|disabled=yes.*name=bond-server1' "$switch_config"
rg --quiet 'name=bond-server2.*disabled=yes|disabled=yes.*name=bond-server2' "$switch_config"
rg --quiet 'name=bond-server3.*disabled=yes|disabled=yes.*name=bond-server3' "$switch_config"
rg --quiet 'name=bond-server1.*slaves="sfp28-3,sfp28-4"|slaves="sfp28-3,sfp28-4".*name=bond-server1' "$switch_config"
rg --quiet 'name=bond-server2.*slaves="sfp28-5,sfp28-6"|slaves="sfp28-5,sfp28-6".*name=bond-server2' "$switch_config"
rg --quiet 'name=bond-server3.*slaves="sfp28-7,sfp28-8"|slaves="sfp28-7,sfp28-8".*name=bond-server3' "$switch_config"
rg --quiet 'interface="sfp28-2".*disabled=yes|disabled=yes.*interface="sfp28-2"' "$switch_config"
rg --quiet 'management default route.*disabled=yes|disabled=yes.*management default route' "$switch_config"

rg --quiet 'vlan-filtering=yes' "$switch_activation_config"
rg --quiet '/interface bonding enable .*name="bond-server1"' "$switch_activation_config"
rg --quiet '/interface bonding enable .*name="bond-server2"' "$switch_activation_config"
rg --quiet '/interface bonding enable .*name="bond-server3"' "$switch_activation_config"
rg --fixed-strings --quiet ':if ([:tostr [/interface bonding get [find where name="bond-server1"] slaves]] != "sfp28-3;sfp28-4")' "$switch_activation_config"
rg --fixed-strings --quiet ':if ([:tostr [/interface bonding get [find where name="bond-server2"] slaves]] != "sfp28-5;sfp28-6")' "$switch_activation_config"
rg --fixed-strings --quiet ':if ([:tostr [/interface bonding get [find where name="bond-server3"] slaves]] != "sfp28-7;sfp28-8")' "$switch_activation_config"
rg --quiet '/interface bridge port enable .*interface="sfp28-2"' "$switch_activation_config"
rg --quiet '/ip route enable .*infra: management default route' "$switch_activation_config"
rg --quiet 'discover-interface-list=INFRA-MAC-MGMT' "$switch_activation_config"

if rg --quiet 'vlan-ids=[^[:space:]]*(40|70|80|999)' "$switch_config" "$switch_activation_config"; then
  echo "reserved VLAN was configured before it gained a deployment" >&2
  exit 1
fi

echo "RouterOS configuration validation passed"
