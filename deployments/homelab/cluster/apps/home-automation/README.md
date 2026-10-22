# Home automation on Kubernetes

One StatefulSet pod runs Home Assistant, Matter.js, Mosquitto, Zigbee2MQTT and a
backup/metrics sidecar. They share one network namespace so internal MQTT and
the unauthenticated Matter WebSocket API stay on loopback. OTBR runs in its own
pod (`thread.yaml`) because it needs a TUN device and IPv6 routing; its
privileged exception is confined there. Both pods attach to IoT VLAN 50 through
Multus `net1` (see [secondary IoT networking](../../infrastructure/multus/README.md));
NetworkPolicies do not cover `net1`, the pod nftables rules do.

**This is a single-writer stack.** Never scale either pod above one replica or
start a second copy of the Zigbee network, Matter fabric or Thread network, and
never replay old radio/fabric state while another copy runs.

## Ownership

- Git owns `configuration.yaml` (copied over the live file on every start),
  `packages/`, `automations/` and `dashboard/`, mounted read-only at
  `/config/managed`. Change them here; HA shows them as not UI-editable.
- HA owns users, integrations, the device/area registry, `.storage` and the
  UI-edited `automations.yaml`, `scripts.yaml` and `scenes.yaml`.
- `bootstrap.py` seeds `.storage/http` once (HA 2026.9 imports `http:` YAML only
  once, then ignores it) and seeds Zigbee2MQTT's `configuration.yaml` once:
  Zigbee2MQTT writes generated network keys and device options back into it.
  **Never replace an initialized Zigbee configuration with one containing
  `GENERATE`**; that forms a new network and orphans every device.
- `install-pinned.py` installs checksum-pinned Onecta and dashboard JS modules
  and caches them on the state PVC, so restarts work offline. A new volume
  needs HTTPS to GitHub.
- Application state backup and restore drills are owned by the backup sidecar
  and `infrastructure/backups/`.

## First start

From the trusted LAN or admin VPN, open <https://home.fahrican.com>, create the
owner (enable MFA), then add **MQTT** (`127.0.0.1:1883`, user `homeassistant`,
password from `credentials.sops.yaml`) and **Matter** (`ws://127.0.0.1:5580/ws`).
Select `net1` under Settings → System → Network. Add **OpenThread Border Router**
at `http://10.21.50.11:8081`. Matter storage holds the fabric keys and must
survive every upgrade and restore.

## Matter commissioning

Put the phone on `Rooftrollen_IoT` with Bluetooth on and use the HA Companion
app; commissioning needs working local multicast and IPv6 (no mDNS reflector,
no client isolation). For Matter-over-Thread devices, first sync the preferred
Thread credentials to the phone:

- Android: Companion app → Settings → Companion app → Troubleshooting →
  **Sync Thread credentials**.
- iPhone: Settings → Devices & services → Thread → Configure →
  **Send credentials to phone**.

`Rooftrollen` is the only Thread network. Additional border routers must join
its dataset; **never form a second Thread network** for this home.

## Radios

Two SONOFF Dongle-M on Ethernet: one in Zigbee coordinator mode, one as Thread
RCP (the modes are mutually exclusive). Their serial allowlists admit only the
automation pod (`.10`) and OTBR (`.11`); web passwords are in
`secrets/home-automation-radios.yaml`. Automatic firmware updates are off; check
compatibility with the pinned Zigbee2MQTT/OTBR release before flashing. The
Zigbee2MQTT UI additionally requires `zigbee-ui-token`; keep pairing closed
outside a bounded pairing window.

## Daikin Onecta

The BRP069C4x adapter (firmware 2.6.2) answers discovery but not the local HTTP
API, so the built-in Daikin integration cannot control it; Onecta uses Daikin's
cloud. Enroll the developer credentials from `secrets/daikin-onecta.yaml`
through HA's `application_credentials/create` WebSocket command. HA owns the
OAuth tokens. `onecta-application-credentials.py` overrides the OAuth platform
so the redirect is exactly `https://home.fahrican.com/auth/external/callback`;
change it and the Daikin portal registration together. Keep polling at 10 min
by day and 30 min at night (about 108 polls/day) under the 200 requests/day
developer quota; MIDI swing commands spend the same quota.

## Nuki Ultra

Matter (`lock.smart_lock_ultra`) is the command path. MQTT carries telemetry
only, via OTBR's NAT64 to the `.10:1883` listener with its own ACL. In the Nuki
app set host `10.21.50.10`, user `nuki`, **Allow locking off, Auto discovery
off**; `packages/nuki-mqtt.yaml` defines the entities. Use a 24-character
alphanumeric password: at 32 characters the lock sends only 31 and fails to
authenticate. **The MQTT action event is a request, not proof the door
moved**; the keypad automation waits for the Matter lock state.

## Lighting

All five Hue bulbs use Zigbee2MQTT `hue_native_control: true` and
`transition: 0` (stored in Zigbee2MQTT's own configuration). Without native
control, a zero-transition off is a level-to-zero command, and a Zigbee2MQTT
restart forgets the previous brightness. Hue dimmers drive bulbs through HA
automations: remove only the dimmer-to-bulb `genOnOff`/`genLevelCtrl` bindings
(`skip_disable_reporting: true`), keep coordinator bindings; battery dimmers may
need a button press to wake for unbinding.

`fp300-profiles.yaml` is the replay source for the three FP300 presence sensors
(publish each `settings` to `zigbee2mqtt/<id>/set`; press the button once to
wake). Run `spatial_learning` separately with the area empty for 30 s; profile
replay never starts it. The bathroom light relies on the sensor's 30 s absence
delay and treats unknown/unavailable as occupied.

RØDECaster MIDI webhooks (see [home-midi](../../../../../components/nix/home-midi/README.md))
stay UI-owned because their IDs live only in `secrets/home-assistant-midi.yaml`;
`install-rodecaster-midi.py` reinstalls them.

## Live recovery

1. Pass the isolated restore check first.
2. Stop the main StatefulSet and OTBR.
3. Extract the verified archive onto a **new** state PVC (UID/GID 1000) and the
   Thread bundle's `thread.tar.gz` onto OTBR's new volume; `dataset.txt` is the
   TLV fallback for replacement hardware.
4. Point the claims at the recovered volumes and start exactly one instance.
5. Verify HA login, MQTT discovery, coordinator identity and Matter devices
   before deleting the old volumes.
