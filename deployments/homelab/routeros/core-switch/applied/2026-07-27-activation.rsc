# APPLIED ACTIVATION RECORD - not a live convergence script.
# Do not import this file into the configured switch.
:error "infra: archived applied record; import refused"
#
# This records the CRS510 activation that followed the staged bootstrap.
#
# The TP-Link uplink and CPU bridge retain native VLAN 1 as a temporary
# recovery path. Remove that transition VLAN only after tagged VLAN 90 has
# been verified end to end.

:if ([:len [/interface bridge find where name="bridge"]] != 1) do={ :error "infra activation preflight: expected exactly one bridge" }
:if ([:len [/interface ethernet find where default-name="sfp28-1"]] != 1) do={ :error "infra activation preflight: uplink is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="sfp28-2"]] != 1) do={ :error "infra activation preflight: PC port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether1"]] != 1) do={ :error "infra activation preflight: rescue port is missing or ambiguous" }
:foreach iface in={"sfp28-3";"sfp28-4";"sfp28-5";"sfp28-6";"sfp28-7";"sfp28-8"} do={ :if ([:len [/interface ethernet find where default-name=$iface]] != 1) do={ :error ("infra activation preflight: server port is missing or ambiguous: " . $iface) }; :if ([:len [/interface ethernet find where default-name=$iface and running]] > 0) do={ :error ("infra activation preflight: refusing an unexpected live server port: " . $iface) } }
:if ([:len [/interface ethernet find where default-name="sfp28-2" and running]] > 0) do={ :error "infra activation preflight: refusing an unexpected live PC port" }
:foreach bondName in={"bond-server1";"bond-server2";"bond-server3"} do={ :if ([:len [/interface bonding find where name=$bondName]] != 1) do={ :error ("infra activation preflight: missing or ambiguous " . $bondName) } }
:if ([:tostr [/interface bonding get [find where name="bond-server1"] slaves]] != "sfp28-3;sfp28-4") do={ :error "infra activation preflight: bond-server1 has unexpected slaves" }
:if ([:tostr [/interface bonding get [find where name="bond-server2"] slaves]] != "sfp28-5;sfp28-6") do={ :error "infra activation preflight: bond-server2 has unexpected slaves" }
:if ([:tostr [/interface bonding get [find where name="bond-server3"] slaves]] != "sfp28-7;sfp28-8") do={ :error "infra activation preflight: bond-server3 has unexpected slaves" }
:foreach vlanId in={1;10;20;30;90} do={ :if ([:len [/interface bridge vlan find where vlan-ids=$vlanId and comment~"^infra:"]] != 1) do={ :error ("infra activation preflight: missing or ambiguous VLAN " . $vlanId) } }
:if ([:len [/ip address find where address="192.168.89.2/24" and interface="ether1"]] != 1) do={ :error "infra activation preflight: direct rescue address is missing" }
:if ([:len [/ip address find where address="10.21.90.2/24" and interface="vlan90-mgmt"]] != 1) do={ :error "infra activation preflight: management address is missing" }

/interface bridge set [find where name="bridge"] frame-types=admit-all ingress-filtering=yes protocol-mode=rstp pvid=1 vlan-filtering=no
/interface bridge port set [find where interface="sfp28-1"] bridge=bridge disabled=no frame-types=admit-all ingress-filtering=yes pvid=1

/interface bonding enable [find where name="bond-server1"]
/interface bonding enable [find where name="bond-server2"]
/interface bonding enable [find where name="bond-server3"]
/interface bridge port enable [find where interface="bond-server1"]
/interface bridge port enable [find where interface="bond-server2"]
/interface bridge port enable [find where interface="bond-server3"]
/interface bridge port enable [find where interface="sfp28-2"]
/ip route enable [find where comment="infra: management default route"]

:if ([:len [/interface list find where name="INFRA-MAC-MGMT"]] = 0) do={ /interface list add comment="infra: L2 management during transition" name=INFRA-MAC-MGMT }
:foreach iface in={"bridge";"vlan90-mgmt";"ether1"} do={ :if ([:len [/interface list member find where interface=$iface and list="INFRA-MAC-MGMT"]] = 0) do={ /interface list member add interface=$iface list=INFRA-MAC-MGMT } }
/ip neighbor discovery-settings set discover-interface-list=INFRA-MAC-MGMT
/tool mac-server set allowed-interface-list=INFRA-MAC-MGMT
/tool mac-server mac-winbox set allowed-interface-list=INFRA-MAC-MGMT
/tool mac-server ping set enabled=no

/ip service set [find where name="ftp" and dynamic=no] disabled=yes
/ip service set [find where name="telnet" and dynamic=no] disabled=yes
/ip service set [find where name="www" and dynamic=no] disabled=yes
/ip service set [find where name="www-ssl" and dynamic=no] disabled=yes
/ip service set [find where name="api" and dynamic=no] disabled=yes
/ip service set [find where name="api-ssl" and dynamic=no] disabled=yes
:if ([/ip service get [find where name="ssh" and dynamic=no] disabled]) do={ /ip service set [find where name="ssh" and dynamic=no] disabled=no }
:if ([/ip service get [find where name="winbox" and dynamic=no] disabled]) do={ /ip service set [find where name="winbox" and dynamic=no] disabled=no }

:delay 5s
/interface bridge set [find where name="bridge"] vlan-filtering=yes

:put "CRS510 activated: filtering enabled with temporary native VLAN 1 recovery"
