# APPLIED LAN-BRIDGE CORRECTION RECORD - not a live convergence script.
# Do not import this file into the configured router.
:error "infra: archived applied record; import refused"
#
# This records the applied CCR2004 LAN-bridge correction.
#
# Before this correction, the Omada uplink was on ether16 and an unused
# untagged TRUSTED access bridge occupied ether15. The correction replaced it
# with one VLAN-aware LAN bridge.
#
# Both physical ports remained hybrid during the physical handoff, preserving
# the Omada path on ether16 until the same cable moved to ether15. The current
# transitional configuration still needs a supervised finalization that
# removes tagged VLANs from ether16 after the new uplink is proven.
#
# Hardware offload is deliberately disabled for this live transition. Enabling
# it can reprogram/reset the shared switch chip and belongs in a maintenance
# window after the physical move.

:if ([:len [/interface ethernet find where default-name="ether15"]] != 1) do={ :error "infra LAN bridge preflight: Omada trunk port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether16"]] != 1) do={ :error "infra LAN bridge preflight: legacy access port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether8"]] != 1) do={ :error "infra LAN bridge preflight: rescue port is missing or ambiguous" }
:if ([/interface ethernet get [find where default-name="ether15"] running]) do={ :error "infra LAN bridge preflight: future Omada trunk must be physically disconnected" }
:if (([/interface ethernet get [find where default-name="ether16"] running]) = false) do={ :error "infra LAN bridge preflight: current Omada trunk is not running" }
:if ([:len [/interface bridge find]] != 1) do={ :error "infra LAN bridge preflight: unexpected bridge count" }
:if ([:len [/interface bridge find where name="bridge-lan"]] != 0) do={ :error "infra LAN bridge preflight: target bridge already exists" }
:if ([:len [/interface bridge find where name="bridge10-trusted-access" and disabled=no and protocol-mode=none and vlan-filtering=yes]] != 1) do={ :error "infra LAN bridge preflight: historical TRUSTED bridge is missing or unexpected" }
:if ([:len [/interface bridge port find where bridge="bridge10-trusted-access"]] != 2) do={ :error "infra LAN bridge preflight: historical TRUSTED bridge has unexpected ports" }
:if ([:len [/interface bridge port find where bridge="bridge10-trusted-access" and interface="vlan10-trusted" and disabled=no]] != 1) do={ :error "infra LAN bridge preflight: historical VLAN 10 bridge port is missing or unexpected" }
:if ([:len [/interface bridge port find where bridge="bridge10-trusted-access" and interface="ether15" and disabled=no]] != 1) do={ :error "infra LAN bridge preflight: historical physical bridge port is missing or unexpected" }
:if ([:len [/interface bridge vlan find where bridge="bridge10-trusted-access"]] != 1) do={ :error "infra LAN bridge preflight: historical TRUSTED bridge has unexpected VLAN entries" }
:if ([:len [/interface bridge vlan find where bridge="bridge10-trusted-access" and comment="infra: internal TRUSTED access segment" and vlan-ids=1]] != 1) do={ :error "infra LAN bridge preflight: historical TRUSTED bridge VLAN is missing or unexpected" }
:if ([:len [/ip address find where address="10.21.10.1/24" and interface="bridge10-trusted-access"]] != 1) do={ :error "infra LAN bridge preflight: TRUSTED gateway is not on the historical bridge" }
:if ([:len [/ip dhcp-server find where name="dhcp-trusted" and interface="bridge10-trusted-access" and disabled=no]] != 1) do={ :error "infra LAN bridge preflight: TRUSTED DHCP is not active on the historical bridge" }
:if ([:len [/ip dhcp-server lease find where server="dhcp-trusted" and status="bound"]] > 0) do={ :error "infra LAN bridge preflight: refusing to move an active TRUSTED DHCP service" }
:if ([:len [/interface list member find where interface="bridge10-trusted-access" and list="INFRA-LAN"]] != 1) do={ :error "infra LAN bridge preflight: historical TRUSTED LAN membership is missing or ambiguous" }
:if ([:len [/interface list member find where interface="bridge10-trusted-access" and list="INFRA-MAC-MGMT"]] != 1) do={ :error "infra LAN bridge preflight: historical TRUSTED MAC management membership is missing or ambiguous" }
:foreach ruleComment in={"infra: input admin";"infra: admin to MGMT";"infra: TRUSTED to WAN";"infra: TRUSTED to SERVERS";"infra: TRUSTED to IOT"} do={ :if ([:len [/ip firewall filter find where comment=$ruleComment and in-interface="bridge10-trusted-access"]] != 1) do={ :error ("infra LAN bridge preflight: missing or unexpected TRUSTED firewall rule: " . $ruleComment) } }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input trusted management" and in-interface="bridge10-trusted-access"]] != 1) do={ :error "infra LAN bridge preflight: IPv6 TRUSTED management rule is missing or unexpected" }
:if ([:len [/ip address find where address="192.168.1.1/24" and interface="ether16"]] != 1) do={ :error "infra LAN bridge preflight: legacy gateway is not on the current trunk" }
:if ([:len [/ip dhcp-server find where name="dhcp-legacy" and interface="ether16" and disabled=no]] != 1) do={ :error "infra LAN bridge preflight: legacy DHCP is not active on the current trunk" }
:if ([:len [/interface list member find where interface="ether16" and list="INFRA-LAN"]] != 1) do={ :error "infra LAN bridge preflight: legacy LAN membership is missing or ambiguous" }
:foreach ruleComment in={"infra: input legacy admin";"infra: legacy admin to MGMT";"infra: legacy LAN to PPPoE"} do={ :if ([:len [/ip firewall filter find where comment=$ruleComment and in-interface="ether16"]] != 1) do={ :error ("infra LAN bridge preflight: missing or unexpected legacy firewall rule: " . $ruleComment) } }
:foreach vlanName in={"vlan10-trusted";"vlan20-servers";"vlan50-iot";"vlan60-guest";"vlan90-mgmt"} do={ :if ([:len [/interface vlan find where name=$vlanName and interface="ether16" and disabled=no]] != 1) do={ :error ("infra LAN bridge preflight: deployment VLAN is not active on the current trunk: " . $vlanName) } }
:if ([:len [/ip address find where address="192.168.88.1/24" and interface="ether8"]] != 1) do={ :error "infra LAN bridge preflight: direct rescue is not ready" }
:if ([:len [/interface list member find where interface="ether8" and list="INFRA-MAC-MGMT"]] != 1) do={ :error "infra LAN bridge preflight: rescue MAC management membership is missing or ambiguous" }
:if ([:len [/interface pppoe-client find where name="pppoe-turknet" and disabled=no]] != 1) do={ :error "infra LAN bridge preflight: PPPoE client is missing, disabled, or ambiguous" }
:if (([/interface get [find where name="pppoe-turknet"] running]) = false) do={ :error "infra LAN bridge preflight: PPPoE is not connected" }
:if ([:len [/ip firewall nat find where comment="infra: PPPoE masquerade" and disabled=no]] != 1) do={ :error "infra LAN bridge preflight: PPPoE masquerade is missing, disabled, or ambiguous" }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft TCP" and protocol="tcp" and to-addresses="192.168.1.197"]] != 1) do={ :error "infra LAN bridge preflight: temporary Minecraft TCP forward is missing or unexpected" }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft UDP" and protocol="udp" and to-addresses="192.168.1.197"]] != 1) do={ :error "infra LAN bridge preflight: temporary Minecraft UDP forward is missing or unexpected" }
:if ([:len [/ip dhcp-server find where name="dhcp1" and interface="ether15"]] != 1) do={ :error "infra LAN bridge preflight: leftover factory DHCP server is missing or unexpected" }
:foreach transitionComment in={"infra: transition bridge legacy admin";"infra: transition bridge legacy admin to MGMT";"infra: transition bridge legacy LAN to PPPoE"} do={ :if ([:len [/ip firewall filter find where comment=$transitionComment]] != 0) do={ :error ("infra LAN bridge preflight: stale transition firewall rule exists: " . $transitionComment) } }

# Remove the mistaken direct-TRUSTED bridge without changing the live legacy
# path on ether16.
/ip dhcp-server disable [find where name="dhcp1" and interface="ether15"]
/ip dhcp-server disable [find where name="dhcp-trusted"]
/interface bridge port remove [find where bridge="bridge10-trusted-access" and interface="vlan10-trusted"]
/interface bridge port remove [find where bridge="bridge10-trusted-access" and interface="ether15"]
/ip address set [find where address="10.21.10.1/24" and interface="bridge10-trusted-access"] interface=vlan10-trusted
/ip dhcp-server set [find where name="dhcp-trusted"] interface=vlan10-trusted
/interface list member set [find where interface="bridge10-trusted-access" and list="INFRA-LAN"] interface=vlan10-trusted
/interface list member set [find where interface="bridge10-trusted-access" and list="INFRA-MAC-MGMT"] interface=vlan10-trusted
/ip firewall filter set [find where comment="infra: input admin"] in-interface=vlan10-trusted
/ip firewall filter set [find where comment="infra: admin to MGMT"] in-interface=vlan10-trusted
/ip firewall filter set [find where comment="infra: TRUSTED to WAN"] in-interface=vlan10-trusted
/ip firewall filter set [find where comment="infra: TRUSTED to SERVERS"] in-interface=vlan10-trusted
/ip firewall filter set [find where comment="infra: TRUSTED to IOT"] in-interface=vlan10-trusted
/ipv6 firewall filter set [find where comment="infra: IPv6 input trusted management"] in-interface=vlan10-trusted
/interface bridge vlan remove [find where bridge="bridge10-trusted-access"]
/interface bridge remove [find where name="bridge10-trusted-access"]

# Pre-stage the new bridge before making ether16 a bridge port.
# Reusing that port's MAC keeps the legacy gateway MAC stable.
/interface ethernet set [find where default-name="ether15"] comment="infra: Omada port 1 handoff; native legacy plus tagged deployment VLANs"
/interface ethernet set [find where default-name="ether16"] comment="infra: current Omada handoff; later untagged friend access"
/interface bridge add admin-mac=[/interface ethernet get [find where default-name="ether16"] mac-address] auto-mac=no comment="infra: VLAN-aware LAN bridge; software forwarding during handoff" disabled=no frame-types=admit-all ingress-filtering=yes name="bridge-lan" protocol-mode=rstp pvid=1 vlan-filtering=yes
/interface bridge port add bridge="bridge-lan" comment="infra: Omada port 1 hybrid trunk" edge=no frame-types=admit-all hw=no ingress-filtering=yes interface="ether15" pvid=1
/interface bridge vlan add bridge="bridge-lan" comment="infra: handoff native legacy LAN" untagged="bridge-lan,ether15,ether16" vlan-ids=1
/interface bridge vlan add bridge="bridge-lan" comment="infra: handoff TRUSTED" tagged="bridge-lan,ether15,ether16" vlan-ids=10
/interface bridge vlan add bridge="bridge-lan" comment="infra: handoff SERVERS" tagged="bridge-lan,ether15,ether16" vlan-ids=20
/interface bridge vlan add bridge="bridge-lan" comment="infra: handoff IOT" tagged="bridge-lan,ether15,ether16" vlan-ids=50
/interface bridge vlan add bridge="bridge-lan" comment="infra: handoff GUEST" tagged="bridge-lan,ether15,ether16" vlan-ids=60
/interface bridge vlan add bridge="bridge-lan" comment="infra: handoff MGMT" tagged="bridge-lan,ether15,ether16" vlan-ids=90
/interface list member add comment="infra: transition VLAN-aware legacy LAN" interface="bridge-lan" list=INFRA-LAN
/ip firewall filter add action=accept chain=infra-input comment="infra: transition bridge legacy admin" dst-port=22,8291 in-interface="bridge-lan" place-before=[find where comment="infra: input final drop"] protocol=tcp src-address=192.168.1.197
/ip firewall filter add action=accept chain=infra-forward comment="infra: transition bridge legacy admin to MGMT" dst-address=10.21.90.0/24 in-interface="bridge-lan" place-before=[find where comment="infra: forward final drop"] src-address=192.168.1.197
/ip firewall filter add action=accept chain=infra-forward comment="infra: transition bridge legacy LAN to PPPoE" in-interface="bridge-lan" out-interface=pppoe-turknet place-before=[find where comment="infra: forward final drop"] src-address=192.168.1.0/24

# Tagged services can move to the prepared bridge before the critical native
# legacy transition. No TRUSTED lease is active at this point.
:foreach vlanName in={"vlan10-trusted";"vlan20-servers";"vlan50-iot";"vlan60-guest";"vlan90-mgmt"} do={ /interface vlan set [find where name=$vlanName] interface="bridge-lan" }

# Critical low-disruption section. Do not insert unrelated operations between
# making ether16 a slave and moving the legacy gateway.
/ip dhcp-server disable [find where name="dhcp-legacy"]
/interface bridge port add bridge="bridge-lan" comment="infra: hybrid during Omada handoff; later friend legacy access" edge=yes frame-types=admit-all hw=no ingress-filtering=yes interface="ether16" pvid=1
/ip address set [find where address="192.168.1.1/24" and interface="ether16"] interface="bridge-lan"
/ip dhcp-server set [find where name="dhcp-legacy"] interface="bridge-lan"
/ip dhcp-server enable [find where name="dhcp-legacy"]

# Canonicalize policy only after bridge-bound duplicates are already active.
/ip firewall filter set [find where comment="infra: input legacy admin"] in-interface="bridge-lan"
/ip firewall filter set [find where comment="infra: legacy admin to MGMT"] in-interface="bridge-lan"
/ip firewall filter set [find where comment="infra: legacy LAN to PPPoE"] in-interface="bridge-lan"
/ip firewall filter remove [find where comment="infra: transition bridge legacy admin"]
/ip firewall filter remove [find where comment="infra: transition bridge legacy admin to MGMT"]
/ip firewall filter remove [find where comment="infra: transition bridge legacy LAN to PPPoE"]
/interface list member remove [find where interface="ether16" and list="INFRA-LAN"]
/ip dhcp-server enable [find where name="dhcp-trusted"]

:if ([:len [/interface bridge find where name="bridge-lan" and disabled=no and protocol-mode=rstp and vlan-filtering=yes]] != 1) do={ :error "infra LAN bridge postflight: target bridge is not active with the expected policy" }
:if ([/interface bridge get [find where name="bridge-lan"] admin-mac] != [/interface ethernet get [find where default-name="ether16"] mac-address]) do={ :error "infra LAN bridge postflight: bridge MAC does not preserve the legacy gateway MAC" }
:if ([:len [/interface bridge port find where bridge="bridge-lan" and interface="ether15" and disabled=no and hw=no and pvid=1]] != 1) do={ :error "infra LAN bridge postflight: Omada hybrid bridge port is missing or unexpected" }
:if ([:len [/interface bridge port find where bridge="bridge-lan" and interface="ether16" and disabled=no and hw=no and pvid=1]] != 1) do={ :error "infra LAN bridge postflight: legacy handoff bridge port is missing or unexpected" }
:if ([:len [/interface bridge vlan find where bridge="bridge-lan"]] != 6) do={ :error "infra LAN bridge postflight: bridge VLAN count is unexpected" }
:foreach vlanName in={"vlan10-trusted";"vlan20-servers";"vlan50-iot";"vlan60-guest";"vlan90-mgmt"} do={ :if ([:len [/interface vlan find where name=$vlanName and interface="bridge-lan" and disabled=no]] != 1) do={ :error ("infra LAN bridge postflight: deployment VLAN is not active on the LAN bridge: " . $vlanName) } }
:if ([:len [/ip address find where address="192.168.1.1/24" and interface="bridge-lan"]] != 1) do={ :error "infra LAN bridge postflight: legacy gateway is not on the LAN bridge" }
:if ([:len [/ip dhcp-server find where name="dhcp-legacy" and interface="bridge-lan" and disabled=no]] != 1) do={ :error "infra LAN bridge postflight: legacy DHCP is not active on the LAN bridge" }
:if ([:len [/interface list member find where interface="bridge-lan" and list="INFRA-LAN"]] != 1) do={ :error "infra LAN bridge postflight: bridge LAN membership is missing or ambiguous" }
:if ([:len [/interface list member find where interface="ether16" and list="INFRA-LAN"]] != 0) do={ :error "infra LAN bridge postflight: obsolete physical LAN membership remains" }
:foreach ruleComment in={"infra: input legacy admin";"infra: legacy admin to MGMT";"infra: legacy LAN to PPPoE"} do={ :if ([:len [/ip firewall filter find where comment=$ruleComment and in-interface="bridge-lan"]] != 1) do={ :error ("infra LAN bridge postflight: canonical legacy firewall rule did not move: " . $ruleComment) } }
:if ([:len [/ip address find where address="10.21.10.1/24" and interface="vlan10-trusted"]] != 1) do={ :error "infra LAN bridge postflight: TRUSTED gateway is not on VLAN 10" }
:if ([:len [/ip dhcp-server find where name="dhcp-trusted" and interface="vlan10-trusted" and disabled=no]] != 1) do={ :error "infra LAN bridge postflight: TRUSTED DHCP is not active on VLAN 10" }
:if ([:len [/interface list member find where interface="vlan10-trusted" and list="INFRA-LAN"]] != 1) do={ :error "infra LAN bridge postflight: TRUSTED LAN membership is missing or ambiguous" }
:if ([:len [/interface list member find where interface="vlan10-trusted" and list="INFRA-MAC-MGMT"]] != 1) do={ :error "infra LAN bridge postflight: TRUSTED MAC management membership is missing or ambiguous" }
:foreach ruleComment in={"infra: input admin";"infra: admin to MGMT";"infra: TRUSTED to WAN";"infra: TRUSTED to SERVERS";"infra: TRUSTED to IOT"} do={ :if ([:len [/ip firewall filter find where comment=$ruleComment and in-interface="vlan10-trusted"]] != 1) do={ :error ("infra LAN bridge postflight: canonical TRUSTED firewall rule did not return to VLAN 10: " . $ruleComment) } }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input trusted management" and in-interface="vlan10-trusted"]] != 1) do={ :error "infra LAN bridge postflight: IPv6 TRUSTED management rule did not return to VLAN 10" }
:if ([:len [/ip address find where address="192.168.88.1/24" and interface="ether8"]] != 1) do={ :error "infra LAN bridge postflight: direct rescue changed unexpectedly" }
:if ([:len [/ip dhcp-server find where name="dhcp1" and interface="ether15" and disabled=yes]] != 1) do={ :error "infra LAN bridge postflight: factory DHCP server is not safely disabled" }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft TCP" and protocol="tcp" and to-addresses="192.168.1.197"]] != 1) do={ :error "infra LAN bridge postflight: temporary Minecraft TCP forward changed unexpectedly" }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft UDP" and protocol="udp" and to-addresses="192.168.1.197"]] != 1) do={ :error "infra LAN bridge postflight: temporary Minecraft UDP forward changed unexpectedly" }

:put "CCR2004 LAN bridge prepared: current service remains on ether16; move only the Omada port 1 cable to ether15, then verify before making ether16 friend-only"
