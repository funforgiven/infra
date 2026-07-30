# APPLIED FACTORY-BOOTSTRAP RECORD - not a live convergence script.
# Do not import this file into the configured switch.
:error "infra: archived applied record; import refused"
#
# This records the CRS510 one-shot staged bootstrap that was applied to the
# inspected factory configuration.
#
# The bridge VLAN table and server LACP bonds are installed, but bridge VLAN
# filtering stays disabled. Native VLAN 1 is retained only on the uplink and
# CPU bridge during the transition so the existing management path survives
# activation until VLAN 90 has been verified through the TP-Link trunk.

:if ([:len [/interface bridge find where name="bridge"]] != 1) do={ :error "infra preflight: expected exactly one bridge named bridge" }
:if ([:len [/interface ethernet find where default-name="sfp28-1"]] != 1) do={ :error "infra preflight: uplink port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="sfp28-2"]] != 1) do={ :error "infra preflight: PC port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether1"]] != 1) do={ :error "infra preflight: rescue port is missing or ambiguous" }
:foreach bridgeVlan in=[/interface bridge vlan find where dynamic=no] do={ :if (([/interface bridge vlan get $bridgeVlan comment] ~ "^infra:") = false) do={ :error "infra preflight: unmanaged static bridge VLAN exists" } }

/system identity set name="core-switch"
/system clock set time-zone-name=Europe/Istanbul
/interface bridge set [find where name="bridge"] frame-types=admit-all ingress-filtering=yes protocol-mode=rstp pvid=1 vlan-filtering=no

/interface ethernet set [find where default-name="sfp28-1"] comment="infra: 10G tagged trunk to TP-Link port9"
/interface ethernet set [find where default-name="sfp28-2"] comment="infra: PC tagged VLANs 10 and 20"
/interface ethernet set [find where default-name="ether1"] comment="infra: direct rescue only"
/interface ethernet set [find where default-name="sfp28-3"] comment="infra: server 1 LACP member A"
/interface ethernet set [find where default-name="sfp28-4"] comment="infra: server 1 LACP member B"
/interface ethernet set [find where default-name="sfp28-5"] comment="infra: server 2 LACP member A"
/interface ethernet set [find where default-name="sfp28-6"] comment="infra: server 2 LACP member B"
/interface ethernet set [find where default-name="sfp28-7"] comment="infra: server 3 LACP member A"
/interface ethernet set [find where default-name="sfp28-8"] comment="infra: server 3 LACP member B"

:foreach iface in={"ether1";"sfp28-3";"sfp28-4";"sfp28-5";"sfp28-6";"sfp28-7";"sfp28-8"} do={ :local bridgePort [/interface bridge port find where interface=$iface]; :if ([:len $bridgePort] > 0) do={ /interface bridge port remove $bridgePort } }

:foreach iface in={"qsfp28-1-1";"qsfp28-1-2";"qsfp28-1-3";"qsfp28-1-4";"qsfp28-2-1";"qsfp28-2-2";"qsfp28-2-3";"qsfp28-2-4"} do={ :local bridgePort [/interface bridge port find where interface=$iface]; :if ([:len $bridgePort] > 0) do={ /interface bridge port remove $bridgePort }; /interface ethernet set [find where default-name=$iface] comment="infra: unassigned" }

:if ([:len [/interface bonding find where name="bond-server1"]] = 0) do={ /interface bonding add comment="infra: server 1; VLANs 20 and 30" disabled=yes lacp-mode=active lacp-rate=1sec link-monitoring=mii min-links=1 mode=802.3ad name=bond-server1 slaves="sfp28-3,sfp28-4" }
:if ([:len [/interface bonding find where name="bond-server2"]] = 0) do={ /interface bonding add comment="infra: server 2; VLANs 20 and 30" disabled=yes lacp-mode=active lacp-rate=1sec link-monitoring=mii min-links=1 mode=802.3ad name=bond-server2 slaves="sfp28-5,sfp28-6" }
:if ([:len [/interface bonding find where name="bond-server3"]] = 0) do={ /interface bonding add comment="infra: server 3; VLANs 20 and 30" disabled=yes lacp-mode=active lacp-rate=1sec link-monitoring=mii min-links=1 mode=802.3ad name=bond-server3 slaves="sfp28-7,sfp28-8" }

:if ([:len [/interface bridge port find where interface="bond-server1"]] = 0) do={ /interface bridge port add bridge=bridge disabled=yes frame-types=admit-only-vlan-tagged ingress-filtering=yes interface=bond-server1 }
:if ([:len [/interface bridge port find where interface="bond-server2"]] = 0) do={ /interface bridge port add bridge=bridge disabled=yes frame-types=admit-only-vlan-tagged ingress-filtering=yes interface=bond-server2 }
:if ([:len [/interface bridge port find where interface="bond-server3"]] = 0) do={ /interface bridge port add bridge=bridge disabled=yes frame-types=admit-only-vlan-tagged ingress-filtering=yes interface=bond-server3 }
:if ([:len [/interface bridge port find where interface="sfp28-1"]] = 0) do={ /interface bridge port add bridge=bridge frame-types=admit-all ingress-filtering=yes interface="sfp28-1" pvid=1 } else={ /interface bridge port set [find where interface="sfp28-1"] bridge=bridge disabled=no frame-types=admit-all ingress-filtering=yes pvid=1 }
:if ([:len [/interface bridge port find where interface="sfp28-2"]] = 0) do={ /interface bridge port add bridge=bridge disabled=yes frame-types=admit-only-vlan-tagged ingress-filtering=yes interface="sfp28-2" } else={ /interface bridge port set [find where interface="sfp28-2"] bridge=bridge disabled=yes frame-types=admit-only-vlan-tagged ingress-filtering=yes }

:foreach bridgeVlan in=[/interface bridge vlan find where comment~"^infra:"] do={ /interface bridge vlan remove $bridgeVlan }
/interface bridge vlan add bridge=bridge comment="infra: transition native VLAN 1" untagged="bridge,sfp28-1" vlan-ids=1
/interface bridge vlan add bridge=bridge comment="infra: TRUSTED" tagged="sfp28-1,sfp28-2" vlan-ids=10
/interface bridge vlan add bridge=bridge comment="infra: SERVERS" tagged="sfp28-1,bond-server1,bond-server2,bond-server3,sfp28-2" vlan-ids=20
/interface bridge vlan add bridge=bridge comment="infra: CEPH; switch-local only" tagged=bond-server1,bond-server2,bond-server3 vlan-ids=30
/interface bridge vlan add bridge=bridge comment="infra: MGMT" tagged="bridge,sfp28-1" vlan-ids=90

:if ([:len [/interface vlan find where name="vlan90-mgmt"]] = 0) do={ /interface vlan add comment="infra: management plane" interface=bridge name=vlan90-mgmt vlan-id=90 }
:if ([:len [/ip address find where comment="infra: MGMT address"]] = 0) do={ /ip address add address=10.21.90.2/24 comment="infra: MGMT address" interface=vlan90-mgmt }
:if ([:len [/ip address find where comment="infra: direct rescue address"]] = 0) do={ /ip address add address=192.168.89.2/24 comment="infra: direct rescue address" interface="ether1" }
:if ([:len [/ip route find where comment="infra: management default route"]] = 0) do={ /ip route add comment="infra: management default route" disabled=yes distance=10 dst-address=0.0.0.0/0 gateway=10.21.90.1 }

:put "CRS510 staged: native VLAN 1 recovery remains; filtering, bonds, PC port, and default route remain disabled"
