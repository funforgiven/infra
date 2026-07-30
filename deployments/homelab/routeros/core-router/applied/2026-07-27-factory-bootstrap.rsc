# APPLIED FACTORY-BOOTSTRAP RECORD - not a live convergence script.
# Do not import this file into the configured router.
:error "infra: archived applied record; import refused"
#
# This records the CCR2004 one-shot staged bootstrap that was applied to the
# inspected minimal configuration.
#
# The transition deliberately preserved the existing sfp-sfpplus1 DHCP/NAT path.
# The PPPoE client, its NAT rule, and the final firewall policy are installed
# disabled. Client VLANs and their DHCP servers are also disabled. The PPPoE
# username and password are set only on the router.

:if ([:len [/interface ethernet find where default-name="ether1"]] != 1) do={ :error "infra preflight: WAN port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether16"]] != 1) do={ :error "infra preflight: LAN trunk port is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="ether15"]] != 1) do={ :error "infra preflight: rescue port is missing or ambiguous" }
:if ([:len [/interface bridge port find where interface="ether1"]] > 0) do={ :error "infra preflight: WAN port is a bridge slave" }
:if ([:len [/interface bridge port find where interface="ether16"]] > 0) do={ :error "infra preflight: LAN trunk port is a bridge slave" }
:if ([:len [/interface bonding find]] > 0) do={ :error "infra preflight: unexpected bonding interface exists" }
:if ([:len [/ip dhcp-client find where interface="ether1"]] > 0) do={ :error "infra preflight: WAN port has a DHCP client" }
:if ([:len [/ip dhcp-client find where interface="ether16"]] > 0) do={ :error "infra preflight: LAN trunk has a DHCP client" }
:if ([:len [/ip address find where interface="ether1"]] > 0) do={ :error "infra preflight: WAN port has an IP address" }
:if ([:len [/ip address find where interface="ether16"]] > 0) do={ :error "infra preflight: LAN trunk has an IP address" }
:if ([:len [/ip address find where address="192.168.88.1/24" and interface="ether15"]] != 1) do={ :error "infra preflight: expected rescue address is missing" }

/system identity set name="core-router"
/system clock set time-zone-name=Europe/Istanbul
/system note set show-at-login=no

/interface ethernet set [find where default-name="ether1"] comment="infra: TurkNet ONT; tagged VLAN 35"
/interface ethernet set [find where default-name="ether16"] comment="infra: 1G tagged trunk to TP-Link port1"
/interface ethernet set [find where default-name="sfp-sfpplus1"] comment="infra: temporary old-LAN rollback path"
/interface ethernet set [find where default-name="ether15"] comment="infra: direct rescue access"

:if ([:len [/interface vlan find where name="wan-vlan35"]] = 0) do={ /interface vlan add comment="infra: TurkNet PPPoE transport" interface="ether1" mtu=1500 name=wan-vlan35 vlan-id=35 }
:if ([:len [/interface vlan find where name="vlan10-trusted"]] = 0) do={ /interface vlan add comment="infra: TRUSTED" disabled=yes interface="ether16" name=vlan10-trusted vlan-id=10 }
:if ([:len [/interface vlan find where name="vlan20-servers"]] = 0) do={ /interface vlan add comment="infra: SERVERS" disabled=yes interface="ether16" name=vlan20-servers vlan-id=20 }
:if ([:len [/interface vlan find where name="vlan50-iot"]] = 0) do={ /interface vlan add comment="infra: IOT" disabled=yes interface="ether16" name=vlan50-iot vlan-id=50 }
:if ([:len [/interface vlan find where name="vlan60-guest"]] = 0) do={ /interface vlan add comment="infra: GUEST" disabled=yes interface="ether16" name=vlan60-guest vlan-id=60 }
:if ([:len [/interface vlan find where name="vlan90-mgmt"]] = 0) do={ /interface vlan add comment="infra: MGMT" interface="ether16" name=vlan90-mgmt vlan-id=90 }

:if ([:len [/ppp profile find where name="turknet"]] = 0) do={ /ppp profile add change-tcp-mss=yes name=turknet use-ipv6=no }
:if ([:len [/interface pppoe-client find where name="pppoe-turknet"]] = 0) do={ /interface pppoe-client add add-default-route=yes comment="infra: TurkNet PPPoE; credentials pending" default-route-distance=1 dial-on-demand=no disabled=yes interface=wan-vlan35 keepalive-timeout=60 max-mru=1492 max-mtu=1492 mrru=disabled name=pppoe-turknet profile=turknet use-peer-dns=no }

:if ([:len [/interface list find where name="INFRA-LAN"]] = 0) do={ /interface list add comment="infra: routed client VLANs" name=INFRA-LAN }
:if ([:len [/interface list find where name="INFRA-MGMT"]] = 0) do={ /interface list add comment="infra: management plane" name=INFRA-MGMT }
:if ([:len [/interface list find where name="INFRA-WAN"]] = 0) do={ /interface list add comment="infra: internet uplinks" name=INFRA-WAN }
:if ([:len [/interface list member find where interface="vlan10-trusted" and list="INFRA-LAN"]] = 0) do={ /interface list member add interface=vlan10-trusted list=INFRA-LAN }
:if ([:len [/interface list member find where interface="vlan20-servers" and list="INFRA-LAN"]] = 0) do={ /interface list member add interface=vlan20-servers list=INFRA-LAN }
:if ([:len [/interface list member find where interface="vlan50-iot" and list="INFRA-LAN"]] = 0) do={ /interface list member add interface=vlan50-iot list=INFRA-LAN }
:if ([:len [/interface list member find where interface="vlan60-guest" and list="INFRA-LAN"]] = 0) do={ /interface list member add interface=vlan60-guest list=INFRA-LAN }
:if ([:len [/interface list member find where interface="vlan90-mgmt" and list="INFRA-LAN"]] = 0) do={ /interface list member add interface=vlan90-mgmt list=INFRA-LAN }
:if ([:len [/interface list member find where interface="vlan90-mgmt" and list="INFRA-MGMT"]] = 0) do={ /interface list member add interface=vlan90-mgmt list=INFRA-MGMT }
:if ([:len [/interface list member find where interface="pppoe-turknet" and list="INFRA-WAN"]] = 0) do={ /interface list member add interface=pppoe-turknet list=INFRA-WAN }
:if ([:len [/interface list member find where interface="wan-vlan35" and list="INFRA-WAN"]] = 0) do={ /interface list member add comment="infra: raw ISP transport" interface=wan-vlan35 list=INFRA-WAN }

:if ([:len [/ip address find where comment="infra: TRUSTED gateway"]] = 0) do={ /ip address add address=10.21.10.1/24 comment="infra: TRUSTED gateway" interface=vlan10-trusted }
:if ([:len [/ip address find where comment="infra: SERVERS gateway"]] = 0) do={ /ip address add address=10.21.20.1/24 comment="infra: SERVERS gateway" interface=vlan20-servers }
:if ([:len [/ip address find where comment="infra: IOT gateway"]] = 0) do={ /ip address add address=10.21.50.1/24 comment="infra: IOT gateway" interface=vlan50-iot }
:if ([:len [/ip address find where comment="infra: GUEST gateway"]] = 0) do={ /ip address add address=10.21.60.1/24 comment="infra: GUEST gateway" interface=vlan60-guest }
:if ([:len [/ip address find where comment="infra: MGMT gateway"]] = 0) do={ /ip address add address=10.21.90.1/24 comment="infra: MGMT gateway" interface=vlan90-mgmt }

:if ([:len [/ip pool find where name="pool-trusted"]] = 0) do={ /ip pool add name=pool-trusted ranges=10.21.10.100-10.21.10.199 }
:if ([:len [/ip pool find where name="pool-servers-bootstrap"]] = 0) do={ /ip pool add name=pool-servers-bootstrap ranges=10.21.20.100-10.21.20.127 }
:if ([:len [/ip pool find where name="pool-iot"]] = 0) do={ /ip pool add name=pool-iot ranges=10.21.50.100-10.21.50.199 }
:if ([:len [/ip pool find where name="pool-guest"]] = 0) do={ /ip pool add name=pool-guest ranges=10.21.60.100-10.21.60.199 }

:if ([:len [/ip dhcp-server find where name="dhcp-trusted"]] = 0) do={ /ip dhcp-server add address-pool=pool-trusted disabled=yes interface=vlan10-trusted lease-time=1d name=dhcp-trusted }
:if ([:len [/ip dhcp-server find where name="dhcp-servers-bootstrap"]] = 0) do={ /ip dhcp-server add address-pool=pool-servers-bootstrap disabled=yes interface=vlan20-servers lease-time=1h name=dhcp-servers-bootstrap }
:if ([:len [/ip dhcp-server find where name="dhcp-iot"]] = 0) do={ /ip dhcp-server add address-pool=pool-iot disabled=yes interface=vlan50-iot lease-time=1d name=dhcp-iot }
:if ([:len [/ip dhcp-server find where name="dhcp-guest"]] = 0) do={ /ip dhcp-server add address-pool=pool-guest disabled=yes interface=vlan60-guest lease-time=4h name=dhcp-guest }

:if ([:len [/ip dhcp-server network find where address="10.21.10.0/24"]] = 0) do={ /ip dhcp-server network add address=10.21.10.0/24 dns-server=10.21.10.1 gateway=10.21.10.1 }
:if ([:len [/ip dhcp-server network find where address="10.21.20.0/24"]] = 0) do={ /ip dhcp-server network add address=10.21.20.0/24 dns-server=10.21.20.1 gateway=10.21.20.1 }
:if ([:len [/ip dhcp-server network find where address="10.21.50.0/24"]] = 0) do={ /ip dhcp-server network add address=10.21.50.0/24 dns-server=10.21.50.1 gateway=10.21.50.1 }
:if ([:len [/ip dhcp-server network find where address="10.21.60.0/24"]] = 0) do={ /ip dhcp-server network add address=10.21.60.0/24 dns-server=10.21.60.1 gateway=10.21.60.1 }

:if ([:len [/ip firewall address-list find where address="10.21.10.0/24" and list="INFRA-LAN-NAT"]] = 0) do={ /ip firewall address-list add address=10.21.10.0/24 comment="infra: TRUSTED" list=INFRA-LAN-NAT }
:if ([:len [/ip firewall address-list find where address="10.21.20.0/24" and list="INFRA-LAN-NAT"]] = 0) do={ /ip firewall address-list add address=10.21.20.0/24 comment="infra: SERVERS" list=INFRA-LAN-NAT }
:if ([:len [/ip firewall address-list find where address="10.21.50.0/24" and list="INFRA-LAN-NAT"]] = 0) do={ /ip firewall address-list add address=10.21.50.0/24 comment="infra: IOT" list=INFRA-LAN-NAT }
:if ([:len [/ip firewall address-list find where address="10.21.60.0/24" and list="INFRA-LAN-NAT"]] = 0) do={ /ip firewall address-list add address=10.21.60.0/24 comment="infra: GUEST" list=INFRA-LAN-NAT }
:if ([:len [/ip firewall address-list find where address="10.21.90.0/24" and list="INFRA-LAN-NAT"]] = 0) do={ /ip firewall address-list add address=10.21.90.0/24 comment="infra: MGMT" list=INFRA-LAN-NAT }
:if ([:len [/ip firewall address-list find where address="10.21.10.20" and list="INFRA-ADMIN-SOURCES"]] = 0) do={ /ip firewall address-list add address="10.21.10.20" comment="infra: primary admin workstation" list=INFRA-ADMIN-SOURCES }

:if ([:len [/ip firewall filter find where comment="infra: activate input policy"]] = 0) do={ /ip firewall filter add action=jump chain=input comment="infra: activate input policy" disabled=yes jump-target=infra-input }
:if ([:len [/ip firewall filter find where comment="infra: input established"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input established" connection-state=established,related }
:if ([:len [/ip firewall filter find where comment="infra: input invalid"]] = 0) do={ /ip firewall filter add action=drop chain=infra-input comment="infra: input invalid" connection-state=invalid }
:if ([:len [/ip firewall filter find where comment="infra: input ICMP"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input ICMP" protocol=icmp }
:if ([:len [/ip firewall filter find where comment="infra: input rescue"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input rescue" in-interface="ether15" }
:if ([:len [/ip firewall filter find where comment="infra: input admin"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input admin" dst-port=22,8291 in-interface=vlan10-trusted protocol=tcp src-address-list=INFRA-ADMIN-SOURCES }
:if ([:len [/ip firewall filter find where comment="infra: input DHCP"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input DHCP" dst-port=67 in-interface-list=INFRA-LAN protocol=udp }
:if ([:len [/ip firewall filter find where comment="infra: input DNS UDP"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input DNS UDP" dst-port=53 in-interface-list=INFRA-LAN protocol=udp }
:if ([:len [/ip firewall filter find where comment="infra: input DNS TCP"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input DNS TCP" dst-port=53 in-interface-list=INFRA-LAN protocol=tcp }
:if ([:len [/ip firewall filter find where comment="infra: input final drop"]] = 0) do={ /ip firewall filter add action=drop chain=infra-input comment="infra: input final drop" }

:if ([:len [/ip firewall filter find where comment="infra: activate forward policy"]] = 0) do={ /ip firewall filter add action=jump chain=forward comment="infra: activate forward policy" disabled=yes jump-target=infra-forward }
:if ([:len [/ip firewall filter find where comment="infra: forward established"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: forward established" connection-state=established,related }
:if ([:len [/ip firewall filter find where comment="infra: forward invalid"]] = 0) do={ /ip firewall filter add action=drop chain=infra-forward comment="infra: forward invalid" connection-state=invalid }
:if ([:len [/ip firewall filter find where comment="infra: drop unsolicited WAN"]] = 0) do={ /ip firewall filter add action=drop chain=infra-forward comment="infra: drop unsolicited WAN" connection-nat-state=!dstnat connection-state=new in-interface-list=INFRA-WAN }
:if ([:len [/ip firewall filter find where comment="infra: admin to MGMT"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: admin to MGMT" dst-address=10.21.90.0/24 in-interface=vlan10-trusted src-address-list=INFRA-ADMIN-SOURCES }
:if ([:len [/ip firewall filter find where comment="infra: TRUSTED to WAN"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: TRUSTED to WAN" in-interface=vlan10-trusted out-interface-list=INFRA-WAN }
:if ([:len [/ip firewall filter find where comment="infra: SERVERS to WAN"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: SERVERS to WAN" in-interface=vlan20-servers out-interface-list=INFRA-WAN }
:if ([:len [/ip firewall filter find where comment="infra: IOT to WAN"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: IOT to WAN" in-interface=vlan50-iot out-interface-list=INFRA-WAN }
:if ([:len [/ip firewall filter find where comment="infra: GUEST to WAN"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: GUEST to WAN" in-interface=vlan60-guest out-interface-list=INFRA-WAN }
:if ([:len [/ip firewall filter find where comment="infra: MGMT to WAN"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: MGMT to WAN" in-interface=vlan90-mgmt out-interface-list=INFRA-WAN }
:if ([:len [/ip firewall filter find where comment="infra: forward final drop"]] = 0) do={ /ip firewall filter add action=drop chain=infra-forward comment="infra: forward final drop" }

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

:if ([:len [/ip firewall nat find where comment="infra: PPPoE masquerade"]] = 0) do={ /ip firewall nat add action=masquerade chain=srcnat comment="infra: PPPoE masquerade" disabled=yes out-interface=pppoe-turknet src-address-list=INFRA-LAN-NAT }

:put "CCR2004 staged: client VLANs, DHCP, PPPoE, IPv4/IPv6 policy jumps, and final NAT remain disabled"
