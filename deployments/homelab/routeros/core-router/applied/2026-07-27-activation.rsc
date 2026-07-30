# APPLIED ACTIVATION RECORD - not a live convergence script.
# Do not import this file into the configured router.
:error "infra: archived applied record; import refused"
#
# This records the CCR2004 activation that followed the staged bootstrap.
#
# This phase is secret-free. PPPoE credentials are installed separately over
# host-key-pinned SSH from private sops-nix runtime files. The old
# sfp-sfpplus1 uplink remains a distance-10, double-NAT fallback until the
# PPPoE cutover is proven.

:if ([:len [/interface ethernet find where default-name="ether1"]] != 1) do={ :error "infra activation preflight: WAN port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether16"]] != 1) do={ :error "infra activation preflight: LAN trunk is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="sfp-sfpplus1"]] != 1) do={ :error "infra activation preflight: rollback port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether15"]] != 1) do={ :error "infra activation preflight: rescue port is missing or ambiguous" }
:if ([:len [/ip address find where address="192.168.88.1/24" and interface="ether15"]] != 1) do={ :error "infra activation preflight: direct rescue address is missing" }
:if ([:len [/ip dhcp-client find where interface="sfp-sfpplus1"]] != 1) do={ :error "infra activation preflight: rollback DHCP client is missing or ambiguous" }
:if ([:len [/interface pppoe-client find where name="pppoe-turknet"]] != 1) do={ :error "infra activation preflight: PPPoE client is missing or ambiguous" }
:if ([:len [/ppp profile find where name="turknet"]] != 1) do={ :error "infra activation preflight: TurkNet PPP profile is missing or ambiguous" }
:if ([:len [/interface pppoe-client get [find where name="pppoe-turknet"] user]] = 0) do={ :error "infra activation preflight: PPPoE username is missing" }
:if ([/interface pppoe-client get [find where name="pppoe-turknet"] comment] != "infra: TurkNet PPPoE; credentials installed") do={ :error "infra activation preflight: PPPoE credentials are not marked ready" }

:foreach vlanName in={"vlan10-trusted";"vlan20-servers";"vlan50-iot";"vlan60-guest";"vlan90-mgmt"} do={ :if ([:len [/interface vlan find where name=$vlanName]] != 1) do={ :error ("infra activation preflight: missing or ambiguous " . $vlanName) } }
:foreach dhcpName in={"dhcp-trusted";"dhcp-servers-bootstrap";"dhcp-iot";"dhcp-guest"} do={ :if ([:len [/ip dhcp-server find where name=$dhcpName]] != 1) do={ :error ("infra activation preflight: missing or ambiguous " . $dhcpName) } }
:foreach ruleComment in={"infra: activate input policy";"infra: input final drop";"infra: activate forward policy";"infra: forward final drop"} do={ :if ([:len [/ip firewall filter find where comment=$ruleComment]] != 1) do={ :error ("infra activation preflight: missing or ambiguous firewall rule " . $ruleComment) } }
:if ([:len [/ip firewall nat find where comment="infra: PPPoE masquerade"]] != 1) do={ :error "infra activation preflight: PPPoE NAT rule is missing or ambiguous" }

/interface ethernet set [find where default-name="ether16"] comment="infra: 1G tagged trunk to TP-Link port1"

/interface vlan set [find where name="vlan10-trusted"] disabled=no interface="ether16" vlan-id=10
/interface vlan set [find where name="vlan20-servers"] disabled=no interface="ether16" vlan-id=20
/interface vlan set [find where name="vlan50-iot"] disabled=no interface="ether16" vlan-id=50
/interface vlan set [find where name="vlan60-guest"] disabled=no interface="ether16" vlan-id=60
/interface vlan set [find where name="vlan90-mgmt"] disabled=no interface="ether16" vlan-id=90
/interface vlan set [find where name="wan-vlan35"] disabled=no interface="ether1" mtu=1500 vlan-id=35

/ppp profile set [find where name="turknet"] change-tcp-mss=yes use-ipv6=no
/interface pppoe-client set [find where name="pppoe-turknet"] add-default-route=yes default-route-distance=1 dial-on-demand=no disabled=yes interface=wan-vlan35 keepalive-timeout=60 max-mru=1492 max-mtu=1492 mrru=disabled profile=turknet use-peer-dns=no
/ip dhcp-client set [find where interface="sfp-sfpplus1"] add-default-route=yes default-route-distance=10 disabled=no use-peer-dns=no

:if ([:len [/interface list member find where interface="sfp-sfpplus1" and list="INFRA-WAN"]] = 0) do={ /interface list member add comment="infra: temporary old-router fallback" interface="sfp-sfpplus1" list=INFRA-WAN }
:if ([:len [/interface list member find where interface="wan-vlan35" and list="INFRA-WAN"]] = 0) do={ /interface list member add comment="infra: raw ISP transport" interface=wan-vlan35 list=INFRA-WAN }

:if ([:len [/ip dhcp-server lease find where comment="infra: primary admin workstation"]] = 0) do={ /ip dhcp-server lease add address=10.21.10.20 comment="infra: primary admin workstation" mac-address=60:CF:84:ED:E9:1E server=dhcp-trusted } else={ /ip dhcp-server lease set [find where comment="infra: primary admin workstation"] address=10.21.10.20 mac-address=60:CF:84:ED:E9:1E server=dhcp-trusted }

/ip dns set allow-remote-requests=yes servers=1.1.1.1

:if ([:len [/ip firewall filter find where comment="infra: input rollback DHCP"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input rollback DHCP" dst-port=68 in-interface="sfp-sfpplus1" place-before=[find where comment="infra: input final drop"] protocol=udp src-port=67 }
:if ([:len [/ip firewall filter find where comment="infra: input rollback admin"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input rollback admin" dst-port=22,8291 in-interface="sfp-sfpplus1" place-before=[find where comment="infra: input final drop"] protocol=tcp src-address=192.168.1.197 }
:if ([:len [/ip firewall filter find where comment="infra: TRUSTED to SERVERS"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: TRUSTED to SERVERS" dst-address=10.21.20.0/24 in-interface=vlan10-trusted place-before=[find where comment="infra: forward final drop"] }
:if ([:len [/ip firewall filter find where comment="infra: TRUSTED to IOT"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: TRUSTED to IOT" dst-address=10.21.50.0/24 in-interface=vlan10-trusted place-before=[find where comment="infra: forward final drop"] }
:if ([:len [/ip firewall filter find where comment="infra: forward dstnat"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: forward dstnat" connection-nat-state=dstnat connection-state=new in-interface-list=INFRA-WAN place-before=[find where comment="infra: forward final drop"] }

:foreach ruleComment in={"infra: activate IPv6 input policy";"infra: IPv6 input established";"infra: IPv6 input invalid";"infra: IPv6 input LAN ICMP";"infra: IPv6 input rescue";"infra: IPv6 input trusted management";"infra: IPv6 input final drop";"infra: activate IPv6 forward policy";"infra: IPv6 forward established";"infra: IPv6 forward invalid";"infra: IPv6 forward LAN ICMP";"infra: IPv6 forward final drop"} do={ :if ([:len [/ipv6 firewall filter find where comment=$ruleComment]] > 1) do={ :error ("infra activation preflight: duplicate IPv6 firewall rule " . $ruleComment) } }
:if ([:len [/ipv6 firewall filter find where comment="infra: activate IPv6 input policy"]] = 0) do={ /ipv6 firewall filter add action=jump chain=input comment="infra: activate IPv6 input policy" disabled=yes jump-target=infra6-input }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input established"]] = 0) do={ /ipv6 firewall filter add action=accept chain=infra6-input comment="infra: IPv6 input established" connection-state=established,related,untracked }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input invalid"]] = 0) do={ /ipv6 firewall filter add action=drop chain=infra6-input comment="infra: IPv6 input invalid" connection-state=invalid }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input LAN ICMP"]] = 0) do={ /ipv6 firewall filter add action=accept chain=infra6-input comment="infra: IPv6 input LAN ICMP" in-interface-list=INFRA-LAN protocol=icmpv6 }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input rescue"]] = 0) do={ /ipv6 firewall filter add action=accept chain=infra6-input comment="infra: IPv6 input rescue" in-interface="ether15" }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input trusted management"]] = 0) do={ /ipv6 firewall filter add action=accept chain=infra6-input comment="infra: IPv6 input trusted management" dst-port=22,8291 in-interface=vlan10-trusted protocol=tcp }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 input final drop"]] = 0) do={ /ipv6 firewall filter add action=drop chain=infra6-input comment="infra: IPv6 input final drop" }
:if ([:len [/ipv6 firewall filter find where comment="infra: activate IPv6 forward policy"]] = 0) do={ /ipv6 firewall filter add action=jump chain=forward comment="infra: activate IPv6 forward policy" disabled=yes jump-target=infra6-forward }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 forward established"]] = 0) do={ /ipv6 firewall filter add action=accept chain=infra6-forward comment="infra: IPv6 forward established" connection-state=established,related,untracked }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 forward invalid"]] = 0) do={ /ipv6 firewall filter add action=drop chain=infra6-forward comment="infra: IPv6 forward invalid" connection-state=invalid }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 forward LAN ICMP"]] = 0) do={ /ipv6 firewall filter add action=accept chain=infra6-forward comment="infra: IPv6 forward LAN ICMP" in-interface-list=INFRA-LAN protocol=icmpv6 }
:if ([:len [/ipv6 firewall filter find where comment="infra: IPv6 forward final drop"]] = 0) do={ /ipv6 firewall filter add action=drop chain=infra6-forward comment="infra: IPv6 forward final drop" }
/ipv6 settings set accept-router-advertisements=no

:if ([:len [/interface list find where name="INFRA-MAC-MGMT"]] = 0) do={ /interface list add comment="infra: L2 management only" name=INFRA-MAC-MGMT }
:foreach iface in={"ether15";"vlan10-trusted";"vlan90-mgmt"} do={ :if ([:len [/interface list member find where interface=$iface and list="INFRA-MAC-MGMT"]] = 0) do={ /interface list member add interface=$iface list=INFRA-MAC-MGMT } }
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

:local inputHook [/ip firewall filter find where comment="infra: activate input policy"]
:local firstInputRule [:pick [/ip firewall filter find where chain="input"] 0]
:if ($inputHook != $firstInputRule) do={ /ip firewall filter move $inputHook $firstInputRule }
:local forwardHook [/ip firewall filter find where comment="infra: activate forward policy"]
:local firstForwardRule [:pick [/ip firewall filter find where chain="forward"] 0]
:if ($forwardHook != $firstForwardRule) do={ /ip firewall filter move $forwardHook $firstForwardRule }
:local input6Hook [/ipv6 firewall filter find where comment="infra: activate IPv6 input policy"]
:local firstInput6Rule [:pick [/ipv6 firewall filter find where chain="input"] 0]
:if ($input6Hook != $firstInput6Rule) do={ /ipv6 firewall filter move $input6Hook $firstInput6Rule }
:local forward6Hook [/ipv6 firewall filter find where comment="infra: activate IPv6 forward policy"]
:local firstForward6Rule [:pick [/ipv6 firewall filter find where chain="forward"] 0]
:if ($forward6Hook != $firstForward6Rule) do={ /ipv6 firewall filter move $forward6Hook $firstForward6Rule }
/ip firewall nat enable [find where comment="infra: PPPoE masquerade"]
/ip firewall filter enable [find where comment="infra: activate input policy"]
/ip firewall filter enable [find where comment="infra: activate forward policy"]
/ipv6 firewall filter enable [find where comment="infra: activate IPv6 input policy"]
/ipv6 firewall filter enable [find where comment="infra: activate IPv6 forward policy"]

/ip dhcp-server enable [find where name="dhcp-trusted"]
/ip dhcp-server enable [find where name="dhcp-servers-bootstrap"]
/ip dhcp-server enable [find where name="dhcp-iot"]
/ip dhcp-server enable [find where name="dhcp-guest"]

/interface pppoe-client enable [find where name="pppoe-turknet"]

:put "CCR2004 activated: PPPoE awaits WAN; IPv4/IPv6 policies enabled; old uplink remains distance-10 fallback"
