# Home automation on Kubernetes

Home Assistant Container replaces the empty standalone NixOS/HAOS installation.
Flux owns the deployment and image upgrades. Home Assistant owns integrations,
users, dashboards and automations in its persistent configuration directory.
The old appliance has no data to migrate; its VM, two boot volumes, dedicated
ports and security groups are explicitly retired by the services-hosts root.

The [Rooftrollen dashboard](dashboard/README.md) provides room controls, lighting,
climate and door pages with a theme that follows the system's light/dark setting.
Its recovery source and pinned frontend resources are tracked in `dashboard/`;
Home Assistant owns the live, UI-editable configuration and existing application
backups include it.

## Components

| Component | Pinned release | Purpose |
| --- | --- | --- |
| Home Assistant Container | 2026.9.2 | Frontend, automations and integration configuration |
| Matter.js Server | 1.4.0 | Matter controller and persistent fabric identity; matches the current official HA app's base image |
| Eclipse Mosquitto | 2.1.2 | Authenticated local MQTT broker with per-user topic ACLs |
| Zigbee2MQTT | 2.14.1 | Ember coordinator over Ethernet at `10.21.50.20` |
| OpenThread Border Router | ownbee v0.3.0 | TCP-connected Thread RCP at `10.21.50.21` |
| Daikin Onecta custom integration | 4.6.19 | Cloud control and telemetry for the Daikin AC |

Every image is pinned by digest. The main StatefulSet contains HA, Matter,
Mosquitto, Zigbee2MQTT and a backup/metrics sidecar. They share one network
namespace so internal MQTT and the unauthenticated Matter WebSocket API use
loopback. A separate MQTT listener accepts only Nuki telemetry through OTBR.
A single 20 GiB Cinder volume holds four separate state directories.
This is deliberately a single-writer stack: upgrades and recovery replace the
whole instance. Do not scale it above one replica or start a second copy of its
Zigbee network or Matter fabric. A second 20 GiB volume holds verified recovery
archives. Cinder can reattach the volumes to another prepared worker.

OTBR has its own pod and 1 GiB state/archive volumes because it creates a TUN
interface and routes IPv6. Its privileged-container exception is confined to
that pod, without host networking, host PID/IPC, a service-account token, or
host filesystem mounts other than `/dev/net/tun`. HA, MQTT, Zigbee2MQTT, Matter
and the backup sidecar run as UID 1000 with no Linux capabilities and a read-only
root filesystem. The network init container has only NET_ADMIN in the pod's
network namespace.

## Networking

```text
LAN / administration WireGuard
          |
https://home.fahrican.com -> Octavia -> Envoy -> HA :8123 on eth0
                                              |
                                              +-- MQTT 127.0.0.1:1883
                                              +-- Matter ws://127.0.0.1:5580/ws
                                              +-- Zigbee2MQTT -> Dongle-M TCP :6638
                                              |
                                        net1 10.21.50.10
                                              |
               physical IoT VLAN 50 -- Multus macvlan bridge
                                              |
                                        net1 10.21.50.11
                                              |
                                  OTBR -> separate Thread RCP
                                              |
                                        Thread mesh IPv6
```

The Omada-to-CRS trunk, CRS server bonds, `bond0.50`, OVS `br-iot`, and the
Neutron `physnet-iot` network carry VLAN 50 end to end. Neutron supplies no DHCP,
router or IPv6 advertisements on this attachment. The existing IoT DHCP pool
is `10.21.50.100–199`; `.10` and `.11` are reserved here for automation pods.

The services-cluster reconciler attaches one unnumbered IoT NIC to each worker,
identified by a deterministic `fa:16:51:*` MAC. A restricted node label selects
prepared workers. The node-network DaemonSet names the interface `iot0`, leaves
it unnumbered, blocks host input on it and installs pinned CNI plugins.
Multus gives each automation pod its secondary interface. Port security is
disabled **only on these IoT ports**, allowing pod IPv4/IPv6 addresses and
multicast to use each pod's own MAC. Tenant ports keep their existing security.
Stale ports from retired workers are retained for inspection rather than
silently detached or reassigned.

Calico NetworkPolicies filter the primary pod interface. They do not protect
Multus interfaces: the explicit pod nftables rules protect `net1`. IoT clients
can exchange discovery and Matter traffic but cannot reach HA, Matter's
management API or the metrics endpoint on that interface. MQTT on `.10:1883`
accepts only OTBR's `.11` NAT64 source, with separate authentication and ACLs.
Internal MQTT credentials are not accepted by this listener. OTBR's API accepts
only the main automation pod's `.10` address. Router advertisements and route
information options are enabled for IPv6 Thread reachability; no ISP IPv6
connection is required. The main pod does not forward traffic between networks.

During Matter commissioning put the phone on `Rooftrollen_IoT` (VLAN 50), with
Bluetooth enabled, and use the HA Companion app. Matter's controller, the Thread
border router and commissioning phone need working local multicast and IPv6.
Do not substitute an mDNS reflector for this L2 attachment. Disable multicast
blocking/client isolation on that SSID if present. Ordinary phone use can return
to the trusted LAN after commissioning. The router permits IoT clients to reach
the services HTTPS VIP `10.21.40.122:443`; the onboarding and Zigbee administration
routes still require an operator network. End-device commissioning is performed later with the Companion app.

## First login and integrations

The owner account exists, MQTT/Matter/OTBR are enrolled, and HA discovery uses
`net1`. The following settings also document how to recreate those integrations.

1. From the trusted LAN or administration WireGuard, open
   <https://home.fahrican.com> and create the owner account. Enable MFA in the
   owner's profile. Every onboarding route is restricted to operator networks.
2. Add **MQTT** with broker `127.0.0.1`, port `1883`, username `homeassistant`,
   and the `homeassistant-password` value in `credentials.sops.yaml`. Retrieve
   it into the password manager or clipboard, without putting it in command
   arguments or logs. The separate Nuki listener carries cleartext MQTT only
   across the local IoT segment between the border router and broker.
3. Add **Matter**, choose an existing/custom server, and set
   `ws://127.0.0.1:5580/ws`. The server's storage contains the fabric keys and
   must survive every upgrade and restore. No host Bluetooth or D-Bus mount is
   needed for Companion-app commissioning.
4. Configure HA's network adapter selection for the IoT interface `net1` under
   Settings → System → Network. HA's supported native account remains the
   authentication authority; no OIDC proxy interferes with its app or APIs.

HA 2026.8 moved HTTP options into authenticated runtime storage. `bootstrap.py`
seeds the pinned 2026.9.2 HTTP schema **once** with forwarded-header trust for
`172.16.0.0/13`, login banning and port 8123. The primary-interface ingress
policy admits HTTP only from Envoy. Subsequent HTTP changes use HA's UI and its
confirmation/rollback mechanism. The initializer never overwrites existing
configuration, network identities or user state.

## Daikin Onecta

The Fahrican Loft FTXM71A2V1B uses a BRP069C4x adapter on `Rooftrollen_IoT`, observed at
`10.21.50.119` (DHCP), MAC `34:90:EA:D1:9B:20`. Firmware `2.6.2` answers Daikin
UDP discovery, but the legacy HTTP status endpoints and a read-only POST to
`/dsiot/multireq` return HTTP 404; HTTPS port 443 refuses connections. These
checks were performed from HA's own IoT address. The built-in local Daikin
integration cannot control this adapter/firmware; use the
[Onecta integration](https://github.com/jwillemsen/daikin_onecta).

`install-onecta.py` runs before HA starts and installs release 4.6.19, pinned
to commit `719600642d2e21f02d87f4a570ce4580849f87b1` and a SHA-256 checksum.
It caches the verified source archive under `home-assistant/.managed-integrations`
on the state PVC, so subsequent pod starts do not need GitHub access. A new
volume needs HTTPS access to `codeload.github.com`. Both the cache and installed
component are included in the existing application backups. Upgrade the version,
commit and checksum together after checking HA compatibility. HACS is not used
to manage this component.

The owner's Daikin developer credentials are encrypted for the administrator
only in `secrets/daikin-onecta.yaml`. Enroll them through HA's authenticated
`application_credentials/create` WebSocket command with domain `daikin_onecta`;
do not place credentials in command arguments, ConfigMaps or logs. HA owns the
live application credentials and OAuth tokens in `.storage`, included in normal
backups. Restoring client credentials alone requires the owner to authorize again.

The registered redirect URI is exactly:

```text
https://home.fahrican.com/auth/external/callback
```

`onecta-application-credentials.py` replaces only the upstream component's OAuth
platform using HA's documented `AuthImplementation` extension. It sets this
callback for Onecta while leaving My Home Assistant enabled for other uses.
The authorization URL and signed OAuth state both use the same callback, which
HA then supplies during token exchange. Do not change just the Daikin portal's
redirect: update the overlay to match and restart HA too. The owner must finish
Daikin login and consent in a browser that can reach `home.fahrican.com`.

Use conservative polling: 10 minutes from 07:00 to 22:00 and 30 minutes overnight,
with 30 seconds of refresh suppression after a command. This schedules about
108 regular polls/day, leaving room beneath Daikin's private-developer limit of
200 API requests/day for commands and additional requests. The actual remaining
quota is exposed by the integration; scheduled polls are not the entire API
request budget. Onecta requires internet and Daikin cloud availability.

## Radio inventory

| Role | Omada PoE port | Reserved IPv4 | Ethernet MAC | mDNS name |
| --- | --- | --- | --- | --- |
| Zigbee coordinator | 4 | `10.21.50.20` | `20:E7:C8:CC:25:8B` | `home-zigbee.local` |
| Thread RCP | 5 | `10.21.50.21` | `20:E7:C8:CD:0D:8F` | `home-thread.local` |

Both ports use `infra-iot-access` (VLAN 50). DHCP reservations are owned by
`network-inventory.yaml`; the dongles use DHCP, not Smart IP. Both run SONOFF
stable ESP32 firmware 1.0.10. The Zigbee radio runs stock coordinator firmware
1.0.0 / Ember 7.4.5; Thread runs stock RCP 1.0.0 / OpenThread SDK 2.4.5.
Automatic firmware updates are disabled. No USB connection is required.

Unique web passwords are encrypted for the administrator in
`secrets/home-automation-radios.yaml`. The operator-provided HA token is encrypted
in `secrets/home-assistant.yaml`; it is not deployed into the cluster. The
ignored `secrets/home-assistant-token.local` input is removed after enrollment.
These credentials are separate from Flux's application credentials. Both setup
hotspots are disabled; serial allowlists admit only `.10` to Zigbee and `.11`
to Thread. The web consoles still require their individual passwords.

## Zigbee coordinator

Use one Dongle-M in **Zigbee coordinator** mode, with Ethernet, stable power and
a DHCP reservation or static address on VLAN 50. Zigbee router mode is for mesh
repeaters; it cannot replace the coordinator. Use a separate dongle for Thread:
Zigbee coordinator, Zigbee router and Thread RCP modes are mutually exclusive.

`radios.env` enables the coordinator at `tcp://10.21.50.20:6638`. Its serial
allowlist admits only `10.21.50.10`. The `ember` adapter uses 115200 baud with
hardware flow control disabled. Before any future firmware change, check
compatibility with the pinned Zigbee2MQTT release.

The frontend is <https://home.fahrican.com/zigbee2mqtt/>. It is restricted to
operator networks and additionally requires `zigbee-ui-token` from SOPS.
Pairing stays closed by default; open it only for the bounded pairing window.
Review the channel before pairing (initial Zigbee channel 20); network keys,
PAN ID and extended PAN ID are generated once and retained on the state PVC.
Never replace an initialized configuration with a new `GENERATE` configuration.
Mesh routers can be added later without changing the Kubernetes infrastructure.

## Thread border router

The `thread.yaml` StatefulSet runs one instance. `thread.env` connects to the
second Dongle-M at `10.21.50.21:6638`, using 115200 baud and no flow control.
`DEVICE=/tmp/ttyOTBR` is the container's TCP-to-PTY bridge. Automatic firmware
flashing is disabled. The serial allowlist admits only OTBR's `.11`.

NAT64 and upstream DNS are enabled for Nuki's MQTT-over-Thread connection.
IPv4 forwarding is enabled only inside the OTBR pod. Its nftables rules permit
translated Thread traffic only to `10.21.50.10:1883` and ICMP to that same broker;
all other translated IPv4 forwarding is dropped, including cluster and internet
destinations. Native IPv6 Matter traffic retains its existing IoT-only routing.
DNS queries handled by OTBR use its existing cluster DNS egress permission.
`thread-ready.sh` configures NAT64 after every agent start, including the
service restart performed by backups; the image's initial configuration runs
only once per container.

The **OpenThread Border Router** integration uses `http://10.21.50.11:8081`.
`Rooftrollen` is the preferred Thread network on channel 25; Zigbee uses channel
20. Its keys were generated once and are retained in OTBR state and HA's Thread
integration. Sync this network's credentials into the Companion app before
pairing Matter-over-Thread devices. Additional border routers must join this
same dataset. Avoid forming a second independent network for the same home.

## Nuki Ultra MQTT activity

The Nuki Ultra (`4E988F8F`) is paired through Matter as
`lock.smart_lock_ultra`. Matter remains the command interface. The separate
MQTT account `nuki` can publish an explicit list of status/event topics under
`nuki/4E988F8F/`; it cannot read commands, publish commands, alter discovery,
or access Zigbee topics. Its password is `stringData.nuki-password` in
`credentials.sops.yaml`. It is not accepted by the loopback listener.
Use a random 24-character ASCII alphanumeric password for this account. This
leaves room below Nuki's documented 32-character limit. During enrollment, the
lock transmitted 31 characters for a configured 32-character password and the
broker rejected authentication; the exact cause of the missing character was
not established. Avoid special characters for compatibility.

In the Nuki app use **Features & Configuration → Smart Home → MQTT**:

- Host: `10.21.50.10`; Nuki uses port `1883` automatically.
- Username: `nuki`; retrieve its password from SOPS.
- **Allow locking: off.**
- **Auto discovery: off.** The repository defines activity entities without a
  duplicate MQTT lock or command buttons.
- Keep the working Matter pairing. Wi-Fi is not needed. Nuki's separate cloud
  remote access is not provided by the restricted NAT64 path.

`nuki-mqtt-discovery.yaml` contains retained MQTT discovery messages. Publish
each mapping entry through HA's authenticated `mqtt.publish` action with
`topic` set to the mapping key, `payload` to the JSON-encoded mapping value,
`retain: true`, and `qos: 1`. These messages and HA's entity registry are included
in normal application backups. Re-publish them after changing the file or
rebuilding an empty broker.

The activity device exposes `event.nuki_ultra_action`, MQTT connection,
lock/keypad low-battery flags, and firmware. Events include requested action,
trigger, authorization ID, code ID, and keypad source when reported. IDs are
not PINs. The MQTT event is an action request, not proof the door unlocked;
use the Matter lock state to confirm completion. Invalid payloads are ignored,
and HA discards replayed retained event messages. No door, alarm or access
automation is created by discovery. User-name mappings require observing the
owner's deliberate keypad/fingerprint actions.

### Keypad lighting

`nuki-keypad-lighting.yaml` is the recovery copy of HA automation
`nuki_keypad_hue_1600_lighting` ("Fahrican Loft keypad - Loft and Bedroom lights"). Install
its YAML mapping as JSON through HA's authenticated
`POST /api/config/automation/config/nuki_keypad_hue_1600_lighting` endpoint.
HA validates, saves and reloads this automation; its live configuration remains
editable in the UI and is included in application backups. It is not a
Kubernetes resource and does not restart the automation pod.

PIN and fingerprint unlock/unlatch actions turn on only the two 1600 lm bulbs,
`light.0x001788011015148f` in Fahrican Loft and `light.0x0017880110151bb9`
in Fahrican Bedroom (Philips model
`9290038536H`). Identified keypad lock/full-lock actions turn them off. The
automation preserves brightness and color and sets transition to zero.
It requires a keypad code ID and source, excludes other command sources,
and waits up to 20 seconds for Matter to confirm the requested lock state.
If confirmation times out or another action supersedes the request, it stops.
Firmware 5.9.4 was observed reporting fingerprint actions with action ID `0`,
which the event entity labels `unknown`, followed by the actual Matter lock
state. For an identified keypad event with action `0`, the automation waits
for a final Matter state whose change timestamp is at or after that event;
`locked` turns the lights off and `unlocked`/`open` turns them on. It never uses
the pre-event state to guess what action `0` will do. Other unknown action IDs
are ignored.
The event trigger ignores restored states on startup/reconnection; a new
keypad request replaces a pending run. No lock command is sent.
Live verification with firmware 5.9.4 confirmed that fingerprint locking turns
both bulbs off, fingerprint unlocking turns both on, and inside-button locking
leaves them unchanged. PIN actions use the same source filter but have not yet
been verified with a physical PIN entry.

MQTT publishes an action request, not a physical door-open sensor reading.
Keypad back-button actions without a code ID cannot be identified by this
rule and require a verified keypad authorization mapping before inclusion.

## Rooms and dimmers

`home-layout.yaml` records the owner's floor/area layout and device assignments.
Home Assistant owns the live floor, area and device registries, which are
included in application backups. Apply the inventory through HA's authenticated
`config/floor_registry`, `config/area_registry` and `config/device_registry`
WebSocket APIs. Registry display names describe the rooms while entity IDs and
Zigbee2MQTT friendly names remain stable for existing automations.

HA permits one floor per area. The shared `5th–6th` floor entry contains
Stairwell; its level is unset because it spans the two physical floors. The
unused initial Bedroom area was renamed Enes Room. Living Room and Kitchen
retain their original registry IDs. Both the Matter lock and MQTT activity
device belong to Fahrican Loft, at the external door. The SONOFF `d047` relay
and Aqara FP300 `4e3e` presence sensor belong to Fahrican Bathroom.

`hue-dimmer-automations.yaml` contains four HA automation recovery copies.
Install each mapping with `POST /api/config/automation/config/<id>`. The power
button's `on_press` event toggles the paired bulb's current HA state. Brightness
up/down press and hold events apply steps of 25 percentage points, with zero
transition. Release events and the unassigned Hue button are ignored. Each
room's dimmer automation has an ordered action queue; unavailable bulbs are
skipped. The two Fahrican Bedroom dimmers share the same automation and queue,
so either remote acts on the bulb's current state. The bedside dimmer is named
`Fahrican Bedroom bedside dimmer` and assigned to `fahrican_bedroom` in HA.
MQTT trigger payloads explicitly use UTF-8 decoding. All five Hue bulbs use
`hue_native_control: true` and `transition: 0`. `hue-device-options.yaml`
contains recovery payloads: publish each mapping to
`zigbee2mqtt/bridge/request/device/options` with QoS 1 and retain disabled,
then verify the response has `status: ok` and the expected `data.to` options.
These options apply immediately and persist in the backed-up Zigbee2MQTT
configuration; the recovery file is not a Kubernetes resource.

Native control is required here to preserve brightness while switching off
instantly. In converters 26.105.0, the standard light converter treats an
explicit zero transition as a level-to-zero off command. Hue then reports
brightness 1; the converter stores the previous brightness only in memory.
A Zigbee2MQTT restart, including the routine backup pause/resume, loses that
value and a subsequent on command restores minimum brightness. On September
26, logs showed the Loft and Bedroom bulbs drop from 254 to 1 after their
01:44 off commands, then turn on at 2 at 18:54 and 15:22 respectively (Istanbul
time), with service restarts in between and no intervening down-button events.
The supported [native Hue control option](https://www.zigbee2mqtt.io/devices/9290038536H.html#options)
sends on/off and zero fade directly without overwriting brightness.
Live HA toggle checks passed on the 1600 lm Loft and 1100 lm Spare Room bulbs:
hardware reads retained brightness 254 and 129 respectively while off and
after turning on. The Spare Room also passed a 129 → 193 → 129 brightness-step
check. Both bulbs were returned to their starting on/off state.

The complete scheduled backup cycle also passed on September 26 at 19:36
Istanbul time. The Spare Room bulb was set to 37% (94/254) and switched off
before the backup. Logs confirmed Zigbee2MQTT stopped and restarted; the
archive passed integrity verification at 19:36:44. Afterward, a hardware read
still returned OFF/94, and a normal HA turn-on without an explicit brightness
returned ON/94. The bulb was restored to its original OFF/129 state. All five
bulbs' native-control options remained in the live configuration after restart.

| Area | Dimmer | Bulb |
| --- | --- | --- |
| Fahrican Loft | `0x001788010ed6a389` | `0x001788011015148f` |
| Fahrican Bedroom | `0x001788010ed6a323` | `0x0017880110151bb9` |
| Fahrican Bedroom (bedside) | `0x001788010edcc45f` | `0x0017880110151bb9` |
| Living Room | `0x001788010edcc2de` | `0x001788010c012f69` |
| Fahrican Spare Room | `0x001788010edcc4bf` | `0x001788010c0179eb` |

Remove only the dimmer-to-bulb `genOnOff` and `genLevelCtrl` bindings, with
`skip_disable_reporting: true`, before enabling each replacement automation.
Retain coordinator bindings for button events and battery/status reports, and
bulb-to-coordinator reporting. Battery dimmers may need a button press to wake
for unbinding. The requested software controls depend on HA, Zigbee2MQTT and
Mosquitto being available. Stairwell keeps its separate motion automation.

## Bathroom presence lighting

`bathroom-presence-lighting.yaml` is the recovery copy of automation
`fahrican_bathroom_presence_lighting`. Install its mapping with
`POST /api/config/automation/config/fahrican_bathroom_presence_lighting`.
HA validates, saves and reloads it; the live automation and room assignments
are included in application backups. This file is not a Kubernetes resource
and needs no pod restart.

### Loft desk FP300

The second FP300, `0x54ef4410017220eb`, is **Fahrican Loft desk sensor** in
the Fahrican Loft area. Its Zigbee2MQTT name and HA entity IDs remain based
on the IEEE address. The Home, Climate and Loft dashboard views show its
temperature and humidity; the Loft view also shows desk presence.

For a seat less than one metre away, the device uses low sensitivity,
`presence_detection_options: both`, adaptive sensitivity off, and radar
range `63` (the six 0.25 m bands from 0 to 1.5 m). The absence delay is
10 seconds and the PIR interval is 5 seconds. Both PIR and radar remain
enabled so someone sitting still can keep the display awake. Use the
combined `presence` entity for the desktop; PIR clearing alone does not
mean the desk is empty.

Climate sampling is `custom`, once every 60 seconds. Temperature reports
on a 0.3 °C change or every 600 seconds; humidity reports on a 2 percentage
point change or every 600 seconds. Both reporting modes are
`threshold and interval`. These values were read back from the device
after configuration on September 27. The device's climate readings are
not calibrated against a reference instrument.

Parmigiano's [presence reader](../../../../../components/nix/funforgiven/window-manager/desk-presence/README.md)
connects over the existing HA HTTPS endpoint using a dedicated local-only,
read-only account. It controls the PC's AMOLED saver, not the loft lights.
The sensor configuration and HA device/area registry are included in the
normal application backups; the desktop service and encrypted credential
are recoverable from this repository.

### Bathroom FP300

The Fahrican Bathroom FP300 (`0x54ef441001724e3e`, model PS-S04D) controls the
SONOFF relay `switch.0xe456acfffe5cd047`. The relay was previously mislabeled
as Fahrican Bedroom; its entity ID and Zigbee2MQTT friendly name stay stable.
`binary_sensor.0x54ef441001724e3e_pir_detection` turns the light on promptly
when motion is reported. `binary_sensor.0x54ef441001724e3e_presence` also turns
it on and keeps it on while radar detects a stationary occupant. Both readings
must be clear before turning off: PIR can clear while radar still detects
someone. Keep `presence_detection_options: both`, `motion_sensitivity: high`,
`ai_sensitivity_adaptive: OFF`, `pir_detection_interval: 2` and
`absence_delay_timer: 10` on the sensor. The PIR interval is at the supported
minimum to test faster detection, at the cost of increased battery use. It is
not a guaranteed entry-to-light latency. See the
[FP300 device documentation](https://www.zigbee2mqtt.io/devices/PS-S04D.html).

Commands have no fade and there is no maximum occupied duration. Once both
readings are clear, HA waits 20 seconds before turning off, making the total
about 30 seconds including the radar's own absence delay. Activity from either
sensor cancels the countdown. Unknown/unavailable readings cancel pending
turn-off and are never treated as vacant; either valid active reading can
still turn the light on. HA startup, automation reload and relay availability
recovery reconcile the light with current sensor states. The relay remains
manually operable between sensor state transitions.

The owner reported intermittent, very short-range radar detection even after
high sensitivity and empty-room spatial learning. On September 26, direct
device reads returned PIR active with radar presence inactive; one earlier
event had a 24-second gap between those reports. The owner subsequently
confirmed near-contact-only detection persisted with fixed high sensitivity
and the shorter PIR interval. Received motion reports switched the relay on
within about half a second. A supported sensor restart was confirmed by its
power-outage counter increasing, and standard device reconfiguration returned
`status: ok`, with the tuned settings preserved. Detection from 1–2 metres in
an open position outside the bathroom remains to be tested to distinguish
placement/interference from a sensor fault. Automatic lighting is not yet
qualified as reliable. The sensor runs firmware `0.0.0_6542`; Zigbee2MQTT
2.14.1 includes the upstream presence/PIR reporting fix, and both coordinator
bindings and configured report entries are present. Do not treat cached
`target_distance: 0` as proof of a failed radar; distance tracking is a separate
diagnostic function.

Later on September 26, the owner clarified that detection was occurring with
about four seconds of delay. Three recent PIR reports were followed by the
relay reporting on within 0.11–0.34 seconds, confirming that HA adds no entry
countdown. Two of those events had no radar presence confirmation. The sensor
accepted `pir_detection_interval: 2` at 20:34 Istanbul time, reduced from 5;
both MQTT and HA reported the new value. The owner reported no improvement
in the roughly four-second entry delay after this change.

A coordinated PIR-only comparison at 21:05–21:06 Istanbul time also produced
the same owner-observed delay. The mode change was confirmed before the owner
waited for the light to switch off and walked back into view. The PIR report
arrived at 21:06:13.900 and the relay reported on at 21:06:14.223, about 0.32
seconds later. Combined mode was restored and verified at 21:06:43.799. This
shows that disabling radar does not eliminate the delay; it does not establish
whether the remaining delay is in PIR detection/firmware or device-specific
Zigbee reporting. Do not attribute it to a HA turn-on timer or to waiting for
radar confirmation. Reliable detection and stationary presence at 3–4 metres
remain unqualified.

## Monitoring and backup

Prometheus scrapes the backup sidecar through an internal ServiceMonitor. It
checks process supervision, authenticated MQTT, Matter's HTTP API and the last
verified archive time. Alerts cover missing readiness, stale backups, MQTT or
Matter failures, repeated restarts and low PVC space. Existing HTTPS/TLS probes,
Velero failure/staleness alerts and infrastructure Telegram delivery apply too.
HA's authenticated Prometheus integration is enabled for optional entity metrics;
its owner token is not generated or stored as a default admin credential.

Every six hours, and before each Velero backup, the backup sidecar asks the four
applications to shut down cleanly. It checkpoints SQLite and archives all state
while the writers are stopped. A pause lease expires after three minutes if the
backup sidecar dies. Forced shutdown, timeout or checksum failure fails the
backup and preserves the previous verified archive. Applications resume before
archive verification and offsite upload. Expect a short interruption during
local snapshots; a growing recorder database can require a larger budget.

Only the verified archive PVC is copied by Velero. Restoring filesystem copies
of live databases is not the recovery procedure. The existing B2/Kopia policy
provides encrypted offsite daily backups at 02:30 UTC (30 days) and weekly
backups at 03:15 UTC Sunday (90 days). Local archive freshness is not proof of
offsite coverage: check both the archive metric and Velero's completed backup
and PodVolumeBackup records. B2 Object Lock is not enabled in this platform.

OTBR's daily/weekly backup hook exports the native dataset privately, stops
`otbr-agent`, waits for its cleanup, archives `/data/thread`, and resumes it.
It atomically publishes one `thread-recovery.tar.gz` bundle containing native
state, `dataset.txt`, a timestamp and SHA-256 checksums. Failed captures preserve
the previous bundle. These files contain Thread keys and must stay private.
The restricted metrics sidecar validates this bundle and reports Thread mesh
attachment. Alerts cover detached Thread state and backups older than 28 hours.
The liveness probe remains active during captures so a stuck backup cannot keep
OTBR stopped indefinitely.

The `backup-qualification/home-automation-restore` CronJob runs monthly on day 2
at 05:30 Istanbul time. It uses the newest completed daily backup and restores
both archives into new scratch PVCs in `home-automation-restore`. PVC modifiers
clear original volume bindings and select the Delete storage class. Velero also
discovers unmounted state-claim placeholders; the verifiers never mount them and
the controller removes them after confirming they remain unbound. The pod
transformation preserves Velero's injected restore helper and removes every
application container. It checks every file hash, JSON payload and the SQLite
database, plus Thread bundle checksums, required dataset fields and native
settings. Each verifier has no service credentials, secondary NIC, host mounts
or network access and cannot start another controller. Scratch volumes use a
Delete reclaim policy.

Run this same check on demand after a deployment and after stateful upgrades:

```sh
velero backup create automation-<unique-name> --include-namespaces home-automation \
  --default-volumes-to-fs-backup --snapshot-volumes=false --wait
kubectl -n backup-qualification create job \
  --from=cronjob/home-automation-restore home-automation-restore-<unique-name> \
  --dry-run=client -o yaml > /tmp/automation-restore-job.yaml
kubectl set env --local -f /tmp/automation-restore-job.yaml \
  BACKUP_NAME=automation-<unique-name> -o yaml | kubectl create -f -
kubectl -n backup-qualification logs -f job/home-automation-restore-<unique-name>
```

The monthly CronJob always selects the newest daily backup. `BACKUP_NAME` is an
explicit override for a scoped on-demand test; manual tests do not replace or
mislabel the daily services backup.

For live recovery, first pass the isolated check, stop the main StatefulSet and
OTBR, mount a **new** state PVC in a disposable non-networked restore pod, and
extract the verified archive there with path traversal and symlinks rejected.
Restore the four state subdirectories with UID/GID 1000. Reuse the SOPS MQTT
credentials and Git configuration, point `automation-state` at the recovered
volume, and start exactly one instance. Unpack the verified Thread bundle, then
restore its inner `thread.tar.gz` into OTBR's new `/data` volume before enabling
its pod; `dataset.txt` is the native TLV fallback for replacement hardware. Verify HA login, MQTT discovery, coordinator identity
and Matter devices before retiring the old volume. Never replay old fabric or
radio state while another copy is running.

## Deployment qualification — 2026-09-15

The live deployment passed these checks before handover:

- The main pod had all five containers ready with zero restarts. The automation,
  IoT network and backup-policy Flux Kustomizations were ready and healthy.
- HTTPS certificate validation and HA WebSocket upgrade succeeded through Envoy.
  IoT clients received HTTP 403 for onboarding; direct IoT access to ports 8123,
  1883, 5580 and 9000 was blocked.
- A temporary pod on another worker reached the HA IoT interface over IPv4 and
  IPv6 link-local, received local IPv6 multicast replies, and reached an existing
  Hue bridge. The temporary probe and its network attachment were removed.
- Prometheus reported authenticated MQTT and the Matter API as healthy, and
  recorded a successful local recovery archive.
- `home-automation-qualification-20260915c` completed in the existing B2 location
  with one PodVolumeBackup: the archive volume, 741,635 bytes. No application
  state or runtime volume was copied directly.
- `home-automation-restore-20260915e` completed at 19:02 UTC. Its PodVolumeRestore
  downloaded all 741,635 bytes into a new scratch volume. The offline verifier
  succeeded, the unmounted state placeholder was removed, and the monthly
  CronJob recorded the successful qualification. Failed diagnostic attempts
  were removed after this result.
- All 15 native-platform flake checks and nine recovery tests passed. The checks
  include archive corruption, SQLite integrity, backup failure recovery, restore
  helper preservation and removal of production PVC bindings.

This initial qualification covered the deployment before radio activation.
The hardware qualification below extends it to the connected dongles.

## Radio qualification — 2026-09-16

- Both Dongle-M devices are configured over PoE/Ethernet, with unique encrypted
  passwords, disabled setup hotspots, DHCP reservations and serial allowlists.
- Zigbee2MQTT connected to Ember 7.4.5, generated its persistent coordinator
  backup, and reported online through MQTT discovery. Pairing remains closed.
  The HTTPS frontend works; an invalid frontend token is rejected with 4401.
- MQTT, Matter, Thread and OTBR integrations are loaded in HA. `Rooftrollen`
  on Thread channel 25 is preferred; HA discovery is limited to `net1`.
- The original ipvlan attachment passed host-address tests but dropped routed
  Thread traffic. Both attachments now use macvlan bridge mode. HA and a probe
  on another prepared worker learned OTBR's IPv6 route and reached its Thread
  address with three replies out of three. The Thread prefix and dataset
  survived the network migration and the backup pause/resume cycle.
- The main pod has five ready containers and OTBR has two, with zero restarts.
  Prometheus scrapes both, reports MQTT/Matter/Thread healthy, and has no active
  home-automation alerts after the backup pause clears.
- From IoT, HA ports 8123/1883/5580/8080/9000 and OTBR's API are blocked.
  Onboarding and Zigbee administration via HTTPS return 403. The temporary
  network probes and attachments are removed.
- B2 backup `home-automation-radios-20260916a` completed at 21:13 UTC on September
  15 (00:13 Istanbul on September 16). Its two PodVolumeBackups contain
  1,470,247 bytes for HA and 993 bytes for Thread, using the existing encrypted
  `fahrican-cloud-recovery/services/kubernetes` destination.
- Restore `home-automation-restore-20260916b` completed at 21:22 UTC September
  15 (00:22 Istanbul September 16), downloading both archives in full. Both
  restricted offline verifiers succeeded, including native Thread state and
  dataset checks. Unmounted state placeholders were removed. The failed
  diagnostic restore/job were removed after this successful rerun.
- All cloud configuration checks and 12 recovery tests passed, including
  corrupt/truncated Thread datasets, unsafe archives, and removal of OTBR's
  privileges from Velero's filesystem restore helper.

End-device Zigbee pairing and Matter-over-Thread commissioning remain to be
performed when devices are available. Before Matter commissioning, connect the
phone to `Rooftrollen_IoT` and sync the preferred Thread credentials:

- Android: Companion app → Settings → Companion app → Troubleshooting →
  **Sync Thread credentials**.
- iPhone: Settings → Devices & services → Thread → Configure →
  **Send credentials to phone** under the preferred network.

Then use the Companion app to add a Matter device. These phone-side steps are
required even though HA already stores and prefers the network.

## Sources

- [Home Assistant Container](https://www.home-assistant.io/installation/linux#install-home-assistant-container)
- [HA HTTP settings](https://www.home-assistant.io/integrations/http/)
- [Thread credential synchronization](https://www.home-assistant.io/integrations/thread/)
- [Matter requirements](https://www.home-assistant.io/integrations/matter/)
- [Official Matter app image selection](https://github.com/home-assistant/addons/blob/master/matter_server/build.yaml)
- [Matter.js container options](https://github.com/matter-js/matterjs-server/blob/v1.4.0/docs/docker.md)
- [SONOFF Dongle-M modes](https://dongle.sonoff.tech/guide/dongle-m/web_console/)
- [Zigbee2MQTT Ember adapters](https://www.zigbee2mqtt.io/guide/adapters/emberznet.html)
- [CNI macvlan](https://www.cni.dev/plugins/current/main/macvlan/)
- [Standalone OTBR container](https://github.com/ownbee/hass-otbr-docker/tree/v0.3.0)
