# Home automation on Kubernetes

Home Assistant Container replaces the empty standalone NixOS/HAOS installation.
Flux owns the deployment and image upgrades. Home Assistant owns integrations,
users, dashboards and automations in its persistent configuration directory.
The old appliance has no data to migrate; its VM, two boot volumes, dedicated
ports and security groups are explicitly retired by the services-hosts root.

## Components

| Component | Pinned release | Purpose |
| --- | --- | --- |
| Home Assistant Container | 2026.9.2 | Frontend, automations and integration configuration |
| Matter.js Server | 1.4.0 | Matter controller and persistent fabric identity; matches the current official HA app's base image |
| Eclipse Mosquitto | 2.1.2 | Authenticated local MQTT broker with per-user topic ACLs |
| Zigbee2MQTT | 2.14.1 | Ember coordinator over Ethernet at `10.21.50.20` |
| OpenThread Border Router | ownbee v0.3.0 | TCP-connected Thread RCP at `10.21.50.21` |

Every image is pinned by digest. The main StatefulSet contains HA, Matter,
Mosquitto, Zigbee2MQTT and a backup/metrics sidecar. They share one network
namespace so MQTT and the unauthenticated Matter WebSocket API stay on
loopback. A single 20 GiB Cinder volume holds four separate state directories.
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
               physical IoT VLAN 50 -- Multus ipvlan L2
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
it unnumbered, blocks host input on it and installs pinned ipvlan CNI plugins.
Multus gives each automation pod its secondary interface. Port security is
disabled **only on these IoT ports**, allowing pod IPv4/IPv6 addresses and
multicast to use the parent MAC. Tenant ports keep their existing security.
Stale ports from retired workers are retained for inspection rather than
silently detached or reassigned.

Calico NetworkPolicies filter the primary pod interface. They do not protect
Multus interfaces: the explicit pod nftables rules protect `net1`. IoT clients
can exchange discovery and Matter traffic but cannot reach HA, MQTT, Matter's
management API or the metrics endpoint on that interface. OTBR's API accepts
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
routes still require an operator network. Hardware commissioning remains
unverified until the radios arrive.

## First login and integrations

1. From the trusted LAN or administration WireGuard, open
   <https://home.fahrican.com> and create the owner account. Enable MFA in the
   owner's profile. Every onboarding route is restricted to operator networks.
2. Add **MQTT** with broker `127.0.0.1`, port `1883`, username `homeassistant`,
   and the `homeassistant-password` value in `credentials.sops.yaml`. Retrieve
   it into the password manager or clipboard, without putting it in command
   arguments or logs. Only loopback carries cleartext MQTT.
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
These credentials are separate from Flux's application credentials.

## Zigbee coordinator

Use one Dongle-M in **Zigbee coordinator** mode, with Ethernet, stable power and
a DHCP reservation or static address on VLAN 50. Zigbee router mode is for mesh
repeaters; it cannot replace the coordinator. Use a separate dongle for Thread:
Zigbee coordinator, Zigbee router and Thread RCP modes are mutually exclusive.

Set `ZIGBEE_SERIAL_PORT=tcp://<coordinator-ip>:6638` and `ZIGBEE_ENABLED=true` in
`radios.env`, then commit. Confirm the socket port in the dongle UI; 6638 is the
usual value. Allow only `10.21.50.10` in the dongle's coordinator IP allowlist.
The `ember` adapter uses 115200 baud with hardware flow control disabled.
Check firmware compatibility against the pinned Zigbee2MQTT release before
flashing; firmware flashing is a separate hardware operation.

The frontend is <https://home.fahrican.com/zigbee2mqtt/>. It is restricted to
operator networks and additionally requires `zigbee-ui-token` from SOPS.
Pairing stays closed by default; open it only for the bounded pairing window.
Review the channel before pairing (initial Zigbee channel 20); network keys,
PAN ID and extended PAN ID are generated once and retained on the state PVC.
Never replace an initialized configuration with a new `GENERATE` configuration.
Mesh routers can be added later without changing the Kubernetes infrastructure.

## Thread border router

The `thread.yaml` StatefulSet runs one instance. `thread.env` connects to the
second Dongle-M at `10.21.50.21:6638`, using 115200 baud and no flow control. `DEVICE=/tmp/ttyOTBR` is the
container's TCP-to-PTY bridge, not a host USB device. Automatic firmware flashing
and NAT64 are disabled. The community OTBR container and network RCP path must
be qualified against the actual hardware before relying on Thread automations.

Add the **OpenThread Border Router** integration at `http://10.21.50.11:8081`.
Create/select one Thread network, set it as preferred, and sync its credentials
into the Companion app. Export the active dataset into the password manager.
Additional border routers should join this same dataset instead of forming
independent networks. Choose the Thread channel after checking local Wi-Fi and
Zigbee interference. Pair Matter devices through the Companion app afterwards.

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

When OTBR is enabled, its backup hook exports the native dataset privately,
stops `otbr-agent`, archives `/data/thread`, and resumes it before the offsite
copy. Its archive and dataset contain Thread keys. The dormant OTBR volumes
hold no network state and are not expected to have PodVolumeBackups yet.

The `backup-qualification/home-automation-restore` CronJob runs monthly on day 2
at 05:30 Istanbul time. It uses the newest completed daily backup and restores
the archive into a new scratch PVC in `home-automation-restore`. PVC modifiers
clear original volume bindings and select the Delete storage class. Velero also
discovers an unmounted state-claim placeholder; the verifier never mounts it and
the controller removes it after confirming it remains unbound. The pod
transformation preserves Velero's injected restore helper and removes every
application container. It checks every file hash, JSON payload and the SQLite
database. The verifier has no credentials, secondary NIC or network access and
cannot start another home automation controller. Its scratch volume uses a
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
volume, and start exactly one instance. Restore OTBR's checked archive/dataset
before re-enabling its pod. Verify HA login, MQTT discovery, coordinator identity
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

This qualifies infrastructure and archive recovery with the initially empty HA
installation. Zigbee pairing, the TCP Thread RCP, OTBR dataset recovery and
Matter-over-Thread commissioning still require the physical radios and devices.

## Sources

- [Home Assistant Container](https://www.home-assistant.io/installation/linux#install-home-assistant-container)
- [HA HTTP settings](https://www.home-assistant.io/integrations/http/)
- [Matter requirements](https://www.home-assistant.io/integrations/matter/)
- [Official Matter app image selection](https://github.com/home-assistant/addons/blob/master/matter_server/build.yaml)
- [Matter.js container options](https://github.com/matter-js/matterjs-server/blob/v1.4.0/docs/docker.md)
- [SONOFF Dongle-M modes](https://dongle.sonoff.tech/guide/dongle-m/web_console/)
- [Zigbee2MQTT Ember adapters](https://www.zigbee2mqtt.io/guide/adapters/emberznet.html)
- [Standalone OTBR container](https://github.com/ownbee/hass-otbr-docker/tree/v0.3.0)
