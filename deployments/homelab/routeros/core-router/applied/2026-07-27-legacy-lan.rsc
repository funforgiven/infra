# APPLIED LEGACY-LAN TRANSITION RECORD - not a live convergence script.
# Do not import this file into the configured router.
:error "infra: archived applied record; import refused"
#
# This records the CCR2004 temporary untagged legacy-LAN overlay.
#
# It was applied while the LAN trunk was physically disconnected. The
# transition prepared the CCR to replace the old router in place: ether1
# received the TurkNet ONT and the existing TP-Link port1 cable moved to
# ether16. Tagged deployment VLANs coexist on the same interface, while
# unmigrated clients remain untagged on 192.168.1.0/24.

:if ([:len [/interface ethernet find where default-name="ether16"]] != 1) do={ :error "infra legacy preflight: LAN trunk is missing or ambiguous" }
:if ([:len [/interface ethernet find where default-name="sfp-sfpplus1"]] != 1) do={ :error "infra legacy preflight: rollback port is missing or ambiguous" }
:if ([/interface ethernet get [find where default-name="ether16"] running]) do={ :error "infra legacy preflight: LAN trunk must be physically disconnected" }
:if ([:len [/ip dhcp-client find where interface="sfp-sfpplus1"]] != 1) do={ :error "infra legacy preflight: rollback DHCP client is missing or ambiguous" }
:if ([:len [/interface list find where name="INFRA-LAN"]] != 1) do={ :error "infra legacy preflight: INFRA-LAN is missing or ambiguous" }
:if ([:len [/interface pppoe-client find where name="pppoe-turknet"]] != 1) do={ :error "infra legacy preflight: PPPoE client is missing or ambiguous" }
:if ([:len [/ip firewall nat find where comment="infra: PPPoE masquerade"]] != 1) do={ :error "infra legacy preflight: PPPoE NAT is missing or ambiguous" }
:if ([/ip firewall nat get [find where comment="infra: PPPoE masquerade"] disabled]) do={ :error "infra legacy preflight: PPPoE NAT is disabled" }
:if ([:len [/ip firewall filter find where comment="infra: input final drop"]] != 1) do={ :error "infra legacy preflight: input final drop is missing or ambiguous" }
:if ([:len [/ip firewall filter find where comment="infra: forward final drop"]] != 1) do={ :error "infra legacy preflight: forward final drop is missing or ambiguous" }
:if ([:len [/ip firewall filter find where comment="infra: forward dstnat"]] != 1) do={ :error "infra legacy preflight: dstnat forward rule is missing or ambiguous" }
:if ([:len [/ip address find where address="192.168.1.1/24" and comment!="infra: temporary legacy LAN gateway"]] > 0) do={ :error "infra legacy preflight: legacy gateway address is owned by an unexpected entry" }
:if ([:len [/ip address find where comment="infra: temporary legacy LAN gateway"]] > 1) do={ :error "infra legacy preflight: duplicate legacy gateway entries" }
:if ([:len [/ip dhcp-server find where name="dhcp-legacy"]] > 1) do={ :error "infra legacy preflight: duplicate legacy DHCP servers" }
:if ([:len [/ip pool find where name="pool-legacy"]] > 1) do={ :error "infra legacy preflight: duplicate legacy DHCP pools" }
:if ([:len [/system script find where name="infra-legacy-cutover"]] > 1) do={ :error "infra legacy preflight: duplicate cutover scripts" }
:if ([:len [/system scheduler find where name="infra-legacy-cutover-watch"]] > 1) do={ :error "infra legacy preflight: duplicate cutover schedulers" }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft TCP"]] > 1) do={ :error "infra legacy preflight: duplicate Minecraft TCP forwards" }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft UDP"]] > 1) do={ :error "infra legacy preflight: duplicate Minecraft UDP forwards" }

/interface ethernet set [find where default-name="ether16"] comment="infra: native legacy LAN and tagged trunk to TP-Link port1"

:if ([:len [/ip pool find where name="pool-legacy"]] = 0) do={ /ip pool add name=pool-legacy ranges=192.168.1.50-192.168.1.99 } else={ /ip pool set [find where name="pool-legacy"] ranges=192.168.1.50-192.168.1.99 }
:if ([:len [/ip address find where comment="infra: temporary legacy LAN gateway"]] = 0) do={ /ip address add address=192.168.1.1/24 comment="infra: temporary legacy LAN gateway" disabled=yes interface="ether16" } else={ /ip address set [find where comment="infra: temporary legacy LAN gateway"] address=192.168.1.1/24 disabled=yes interface="ether16" }
:if ([:len [/ip dhcp-server find where name="dhcp-legacy"]] = 0) do={ /ip dhcp-server add address-pool=pool-legacy comment="infra: temporary untagged legacy LAN" disabled=yes interface="ether16" lease-time=1d name=dhcp-legacy } else={ /ip dhcp-server set [find where name="dhcp-legacy"] address-pool=pool-legacy disabled=yes interface="ether16" lease-time=1d }
:if ([:len [/ip dhcp-server network find where address="192.168.1.0/24"]] = 0) do={ /ip dhcp-server network add address=192.168.1.0/24 comment="infra: temporary untagged legacy LAN" dns-server=192.168.1.1 domain=internal gateway=192.168.1.1 } else={ /ip dhcp-server network set [find where address="192.168.1.0/24"] dns-server=192.168.1.1 domain=internal gateway=192.168.1.1 }
:if ([:len [/ip dhcp-server lease find where comment="infra: temporary legacy admin workstation"]] = 0) do={ /ip dhcp-server lease add address=192.168.1.197 comment="infra: temporary legacy admin workstation" mac-address=60:CF:84:ED:E9:1E server=dhcp-legacy } else={ /ip dhcp-server lease set [find where comment="infra: temporary legacy admin workstation"] address=192.168.1.197 mac-address=60:CF:84:ED:E9:1E server=dhcp-legacy }
:if ([:len [/ip dhcp-server lease find where comment="infra: temporary legacy Omada switch"]] = 0) do={ /ip dhcp-server lease add address=192.168.1.189 comment="infra: temporary legacy Omada switch" mac-address=98:25:4A:CB:BF:BE server=dhcp-legacy } else={ /ip dhcp-server lease set [find where comment="infra: temporary legacy Omada switch"] address=192.168.1.189 mac-address=98:25:4A:CB:BF:BE server=dhcp-legacy }
:if ([:len [/ip dhcp-server lease find where comment="infra: temporary legacy Omada AP"]] = 0) do={ /ip dhcp-server lease add address=192.168.1.163 comment="infra: temporary legacy Omada AP" mac-address=9C:A2:F4:C2:ED:74 server=dhcp-legacy } else={ /ip dhcp-server lease set [find where comment="infra: temporary legacy Omada AP"] address=192.168.1.163 mac-address=9C:A2:F4:C2:ED:74 server=dhcp-legacy }
:if ([:len [/ip dhcp-server lease find where comment="infra: temporary legacy Hue Bridge"]] = 0) do={ /ip dhcp-server lease add address=192.168.1.121 comment="infra: temporary legacy Hue Bridge" mac-address=EC:B5:FA:8E:DB:63 server=dhcp-legacy } else={ /ip dhcp-server lease set [find where comment="infra: temporary legacy Hue Bridge"] address=192.168.1.121 mac-address=EC:B5:FA:8E:DB:63 server=dhcp-legacy }

:if ([:len [/interface list member find where interface="ether16" and list="INFRA-LAN"]] = 0) do={ /interface list member add comment="infra: temporary untagged legacy LAN" interface="ether16" list=INFRA-LAN }
:if ([:len [/ip firewall address-list find where address="192.168.1.0/24" and list="INFRA-LAN-NAT"]] = 0) do={ /ip firewall address-list add address=192.168.1.0/24 comment="infra: temporary legacy LAN" list=INFRA-LAN-NAT }

:if ([:len [/ip firewall filter find where comment="infra: input legacy admin"]] = 0) do={ /ip firewall filter add action=accept chain=infra-input comment="infra: input legacy admin" dst-port=22,8291 in-interface="ether16" place-before=[find where comment="infra: input final drop"] protocol=tcp src-address=192.168.1.197 }
:if ([:len [/ip firewall filter find where comment="infra: legacy admin to MGMT"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: legacy admin to MGMT" dst-address=10.21.90.0/24 in-interface="ether16" place-before=[find where comment="infra: forward final drop"] src-address=192.168.1.197 }
:if ([:len [/ip firewall filter find where comment="infra: legacy LAN to PPPoE"]] = 0) do={ /ip firewall filter add action=accept chain=infra-forward comment="infra: legacy LAN to PPPoE" in-interface="ether16" out-interface=pppoe-turknet place-before=[find where comment="infra: forward final drop"] src-address=192.168.1.0/24 }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft TCP"]] = 0) do={ /ip firewall nat add action=dst-nat chain=dstnat comment="infra: temporary Minecraft TCP" dst-port=25565 in-interface=pppoe-turknet protocol=tcp to-addresses=192.168.1.197 to-ports=25565 } else={ /ip firewall nat set [find where comment="infra: temporary Minecraft TCP"] action=dst-nat chain=dstnat disabled=no dst-port=25565 in-interface=pppoe-turknet protocol=tcp to-addresses=192.168.1.197 to-ports=25565 }
:if ([:len [/ip firewall nat find where comment="infra: temporary Minecraft UDP"]] = 0) do={ /ip firewall nat add action=dst-nat chain=dstnat comment="infra: temporary Minecraft UDP" dst-port=25565 in-interface=pppoe-turknet protocol=udp to-addresses=192.168.1.197 to-ports=25565 } else={ /ip firewall nat set [find where comment="infra: temporary Minecraft UDP"] action=dst-nat chain=dstnat disabled=no dst-port=25565 in-interface=pppoe-turknet protocol=udp to-addresses=192.168.1.197 to-ports=25565 }

:if ([:len [/system scheduler find where name="infra-legacy-cutover-watch"]] > 0) do={ /system scheduler remove [find where name="infra-legacy-cutover-watch"] }
:if ([:len [/system script find where name="infra-legacy-cutover"]] > 0) do={ /system script remove [find where name="infra-legacy-cutover"] }
/system script add name="infra-legacy-cutover" policy=read,write,policy,test source={
    :local lanRunning [/interface ethernet get [find where default-name="ether16"] running]
    :local setupRunning [/interface ethernet get [find where default-name="sfp-sfpplus1"] running]
    :if ($lanRunning = true) do={
        :if ($setupRunning = false) do={
            /ip dhcp-client disable [find where interface="sfp-sfpplus1"]
            :if ([:len [/interface list member find where interface="sfp-sfpplus1" and list="INFRA-WAN"]] > 0) do={ /interface list member remove [find where interface="sfp-sfpplus1" and list="INFRA-WAN"] }
            /system scheduler disable [find where name="infra-legacy-cutover-watch"]
            :log warning "infra: legacy LAN cutover disabled the temporary setup DHCP client"
        }
    }
}
/system scheduler add interval=5s name="infra-legacy-cutover-watch" on-event="/system script run infra-legacy-cutover" policy=read,write,policy,test start-time=startup

/ip dns set allow-remote-requests=yes servers=1.1.1.1
/ip address enable [find where comment="infra: temporary legacy LAN gateway"]
/ip dhcp-server enable [find where name="dhcp-legacy"]

:put "CCR2004 legacy LAN ready: connect ether1 to ONT and ether16 to TP-Link port1 only after disconnecting the old router"
