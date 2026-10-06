# Migration validation — 2026-09-27

The controller and AP are online using a **temporary 1 Gb/s Ethernet limit** on
switch port 6. Automatic 2.5 Gb/s negotiation does not sustain connectivity on
the current cable/switch path, including after updating the AP to 8.7.11. This
record includes the 2026-09-26 migration and the following day's offsite backup
verification. The owner accepted retaining 1 Gb/s and reported good wireless
speeds after tuning.

## Verified deployment

| Area | Observation |
| --- | --- |
| Ownership | UniFi is AP-only. MikroTik retains routing, DHCP, firewall and VPN. Omada retains its switch. |
| Replacement AP | U7 Pro Max `74:F9:2C:3C:99:F7`, on the former EAP670 cable at SG3210XHP-M2 port 6. |
| Port contract | `infra-ap-trunk`: untagged/native VLAN 90, tagged VLANs 10 and 50. Switch reconciliation reports no changes or blockers. |
| Physical link | Port 6 at 1 Gb/s full duplex as a temporary workaround. The Omada reconciler preserves physical speed/duplex; the limit is recorded in `unifi-network.yaml`. |
| Address | Router reservation `10.21.90.6`; old EAP address `10.21.90.4` preserved. |
| Controller | Dedicated retained-volume VM, `192.168.80.12` / `10.21.40.127`; installed UniFi OS 5.1.42 and Network 10.5.67. Native automatic updating advanced Network to 10.6.106; its served UI version was verified. |
| Authentication | Generated local owner and separate Network Read Only monitoring user, stored in administrator-only SOPS. Remote access disabled; diagnostics disabled; default automatic updates retained. |
| WLAN configuration | `Rooftrollen` references the third-party VLAN-10 network; `Rooftrollen_IoT` references VLAN 50. Existing PSKs retained. Controller API read-back confirms both references. |
| Origin TLS | Private CA and hostname verification passed against nginx; leaf renewal timer enabled. Services-cluster TCP probe to `192.168.80.12:8443` succeeded. |
| Exporters | Node exporter, controller health textfile and UnPoller running. The disconnected-AP metric was observed during the initial failure. |
| Router access | Narrow inform/STUN, private setup/SSH and VPN AP-SSH rules applied. No WAN port forwards added. |

The migration and radio settings were published to `origin/main` at signed
commit `f24709377ca4a3495523d5278b88def864d518b2`, after the owner's explicit
authorization and secret checks. Gitleaks found no exposed credentials in the
pending history. A separate in-memory comparison verified that the actual
UniFi passwords, backup password and WLAN PSKs occur nowhere in that history
as plaintext or base64. Only SOPS-encrypted credential fields and public
host/CA keys were published; private keys, kubeconfigs and recovery archives
were excluded.

The private access and monitoring rollout is verified:

- DNS resolves `unifi.fahrican.com` to `10.21.40.122`.
- The services Gateway certificate includes the new hostname and is Ready.
  HTTPRoute and BackendTLSPolicy have Accepted/ResolvedRefs conditions;
  the administrator SecurityPolicy is Accepted.
- An admin-workstation request returned HTTP 200 with successful certificate
  verification. An authenticated owner login and Network API read through
  `https://unifi.fahrican.com` succeeded; the verification session logged out.
- The same HTTPS request from a non-admin VM returned HTTP 403, also with
  successful certificate verification. The allowlist remains the admin
  workstation and administration WireGuard subnet.
- Prometheus reports healthy node-metrics, AP-metrics and origin-probe targets.
  `unifi_service_up`, `unifi_https_up` and `probe_success` are 1; AP uptime is
  present. A transient poller reauthentication failure cleared on a later
  scrape, and the AP-metrics alert cleared. The first offsite backup succeeded
  on 2026-09-27 at 00:05:35 UTC and exported its success timestamp.
  Prometheus subsequently observed that timestamp, all three targets were
  healthy, and `ALERTS{alertname=~"UniFi.*"}` returned no active alerts.
- Both undercloud UniFi/DNS waves and the services UniFi/Gateway waves applied
  the published revision. The UniFi Terraform resource is Ready and reports
  **Plan no changes**, confirming adoption of the already-provisioned VM
  without replacement.

The native private recovery UI remains on `10.21.40.127:11443`. Actual access
from an external VPN client still needs acceptance testing.

## AP connectivity failure and recovery

The controller recorded adoption completion at 20:02:51 UTC. Its stored inform
URL is `http://10.21.40.127:8080/inform`. The initial firmware was
`7.0.48.15574`. After adoption the AP lost its address and SSH access, despite
showing a solid blue LED and allowing the Android phone to associate. The phone
received a fresh VLAN-10 DHCP lease but reported no internet access.

Router logs show the AP releasing its lease after adoption, then repeatedly
discovering DHCP. A packet capture shows a correctly addressed DHCP offer with
the matching transaction ID; it contains no subsequent request/acknowledgment.
The switch learned the AP MAC on VLAN 90. The phone's neighbor entry repeatedly
failed too, despite occasional valid ARP replies and outbound traffic.

Bounded diagnostics found:

- Port 6 supplies PoE+ Class 4, approximately 10 W at 52.7 V. Its transmit and
  receive error counters are zero; STP is forwarding.
- DHCP snooping is disabled on both the Omada switch and CCR bridge.
- One port-6 PoE recovery completed successfully but did not restore access.
- A temporary port-6 native/tagged VLAN test confirmed untagged AP management;
  it did not restore DHCP. The original profile was restored and rechecked.
- An AP-only DHCP broadcast-reply test did not help. Normal reply behavior was
  restored. Captures were stopped, sniffer filters cleared and router-side
  capture files removed.
- The expected IPv6 link-local address and ARP probes for the standard fallback
  address `192.168.1.20` on VLAN 90 did not respond. A later short capture limited
  to the AP MAC yielded no additional fallback-address evidence.
- No switch ACL, ARP-inspection or 802.1X restriction was enabled. A temporary
  DHCP-verified static neighbor entry for the phone did not restore connectivity
  and was removed.

Restricting only port 6 to **1 Gb/s full duplex** restored the AP's DHCP lease,
SSH and authenticated controller connection. Returning to automatic 2.5 Gb/s
negotiation lost connectivity again. The controller subsequently upgraded the AP
to the offered official `8.7.11.19419` release over the working link. The direct
official HTTPS artifact matched the controller's cached MD5/size; its SHA-256
was `f55f221433b4fe3eace4438cf93e5ab313138928a26c2d6cf0ffaf10f653fb4d`.
The model-specific artifact is
[`8a98-U7PROMAX-8.7.11-436e4a04-695d-41a0-bc7b-687a5484a53c.bin`](https://fw-download.ubnt.com/data/unifi-firmware/8a98-U7PROMAX-8.7.11-436e4a04-695d-41a0-bc7b-687a5484a53c.bin).

An automatic-speed retest after the upgrade again failed sustained reachability,
so port 6 was returned to 1 Gb/s. On the restored link the AP reported Connected,
three associated clients and synchronized time. Five probes each to the gateway
and `1.1.1.1` passed with zero loss. Authentication with the managed device SSH
credential was verified on both firmware versions.

Immediately after recovery, the controller identified three associated clients
on `Rooftrollen_IoT`; the Android phone was then absent. A later user speed test
confirmed working Wi-Fi at approximately 450 Mb/s. The AP initially showed `Rooftrollen` on
2.4/5 GHz and `Rooftrollen_IoT` on 2.4 GHz, plus hidden UniFi internal interfaces.
The user reported `6ghz-control` while the old firmware was running; it is not
a configured user WLAN. No post-upgrade over-the-air scan has been completed.

The firmware adds an Ed25519 SSH host key, but the original pinned RSA key is
unchanged. RSA-SHA2 negotiation verified continuity without accepting an unknown
host key. Clients with a known-host algorithm selection issue can select
`rsa-sha2-512,rsa-sha2-256`; do not disable host-key verification.

This isolates the failure to behavior dependent on the Ethernet speed; it does
not establish whether the cable, AP PHY or switch interoperability is at fault.
The SG3210XHP-M2 v3.0 currently runs firmware `3.0.0 Build 20230725 Rel.71176`.
The user confirmed the cable is Cat6 and accepted keeping 1 Gb/s. Cable category
is sufficient for 2.5 Gb/s; the observed failure does not prove a cable fault.
Further Ethernet diagnosis is deferred. A switch-wide firmware update needs a
separate maintenance window because it interrupts the other endpoints.

For immediate wireless rollback, reconnect the EAP670 to this same port 6; its
old address and Omada WLAN objects remain available. Restore automatic port
speed when qualifying that rollback if its previous 2.5 Gb/s link is required.

## Wireless performance and MLO

Before tuning, the phone at `10.21.10.101` was associated on 5 GHz with a strong
-46 dBm signal, 40 MHz channel width, two spatial streams and a reported AP-to-
client PHY rate of 573.6 Mb/s. The user's approximately 450 Mb/s speed test is
consistent with that limited channel width. The default bandwidth profile has
no download or upload rate cap, and the Ethernet link reports full duplex with
zero receive/transmit errors.

At the user's request, Rooftrollen now uses only **5 and 6 GHz**, with **MLO,
WPA3-only and required PMF**. Its password and VLAN-10 network reference are
unchanged. Rooftrollen_IoT remains **2.4 GHz, WPA2-AES, VLAN 50**; a complete
before/after API comparison confirmed its WLAN object was unchanged.

The AP's native radio state confirms 5 GHz at **80 MHz** on primary channel 40
and 6 GHz at **160 MHz** on primary channel 85. The 2.4-GHz radio remains at
20 MHz on channel 11. Country code 792 (Turkey) and its lower-6-GHz channel set
are retained. The controller confirms `mlo_enabled=true`, and the AP has an
`mld0` interface. A client MLO association still requires verification; enabling
the feature alone does not prove it. The owner subsequently reported good
speeds after tuning, without supplying an exact result.

The U7 Pro Max's dedicated `wifi3`/`scan0` radio and `/usr/sbin/ubnt-airview -w 1`
are active. The installed Network 10.6.106 UI exposes Spectrum Analyzer under
AirView > WiFi Scanner; the checkbox changes the display mode. There is no
additional persistent AP-enable setting required. Automatic Channel AI remains
disabled. No disruptive full-radio scan was started.

## Backup evidence

A cold archive was taken with the UniFi container stopped, then the controller
was restarted before encrypting/copying the checkpoint. Restic snapshot
`c94c30bba1bb9bbfd806e737c63f6456c590284ce2f802c90496f210fed9791c`
processed 2,886,420,480 bytes. Both `restic check --read-data` and a complete
decrypted tar listing succeeded.

The encrypted repository copy is local at
`secrets/recovery/unifi-c94c30bb.tar.backup` (ignored by Git, mode `0600`, parent
directory `0700`). Its password is the existing SOPS
`UNIFI_BACKUP_RESTIC_PASSWORD`. The source encrypted repository also remains on
the controller VM at `/var/lib/unifi-local-recovery`.

That earlier checkpoint is local. On 2026-09-27, the standard B2 reconciler
created `infra-services-unifi-backup-writer`, restricted to
`fahrican-cloud-recovery/services/hosts/unifi/`. Credentials were persisted in
SOPS and installed in root-owned mode-`0400` runtime files under a mode-`0700`
directory. The existing Restic password was reused. Both mode-`0600` master
intake files were cleared after reconciliation; no master credential was
installed on the VM. Six other configured writers authenticated successfully
and retained their existing credentials and prefix restrictions.

The first offsite snapshot is
`7dff5a25e3a904f07fc1cf72852d15a52add5fabc172233195ee6250aa8d3df0`,
taken at 00:03:30 UTC. Upload and retention completed at 00:05:35 UTC. The
controller was restarted before upload, and its authenticated production API
still reported the AP connected with four clients afterward. The snapshot
processed 3.251 GiB and stored 1.144 GiB after compression/deduplication.
`restic check --read-data` read all 72 packs with no errors, and an offsite
restore produced a completely readable archive with SHA-256
`329b1ce3ea49c116338b3f19f0b44ddf323e52bd52336f5578f1bd39800b53a5`.

The offsite archive was then restored onto a separate VM using the same pinned
Ubuntu image and UniFi OS 5.1.42 installer. Its host key was pinned through the
authenticated OpenStack console. Before receiving the saved identity, its
general egress rule was removed. Only operator SSH through the production VM
and local DHCP request/reply traffic were allowed; no production floating IP
was attached. API inspection verified the exact security group and secured
port, and connection probes to the AP, production inform endpoint and internet
failed as expected.

The archive's SHA-256 matched after transfer. UID/GID `1001` and subordinate
range `165536:65536` matched the saved account mappings. Initial startup exposed
stale Podman runtime state from the blank installation; rebooting the isolated
recovery VM recreated it and started the saved controller successfully. The
runbook now records that reboot and the required DHCP-only firewall exception.

Authenticated verification on the running recovery controller passed:

- Local owner login and the `Homelab WiFi` / default site were restored.
- Network reported `10.6.106`; the adopted U7 Pro Max MAC and firmware
  `8.7.11.19419` were retained. Its state was disconnected, as isolation requires.
- Rooftrollen retained VLAN 10, 5/6 GHz, MLO and required PMF;
  Rooftrollen_IoT retained VLAN 50, 2.4 GHz and its separate security settings.
  Both PSKs and security fields matched production in memory without printing
  credentials. The networks remained third-party VLAN-only with no DHCP server.
- Turkey country code 792, diagnostics disabled and native backup settings
  matched production. Both verification sessions logged out.
- The restored origin CA and certificate passed hostname verification, and
  HTTPS through the restored nginx origin returned HTTP 200.

The recovery controller was stopped and its container verified stopped before
cleanup. The temporary VM, boot volume, port and security group were deleted;
their OpenStack API lookups returned HTTP 404. The additional plaintext restore
staging directory on production was removed. The normal backup staging archive
and encrypted local migration checkpoint remain available. Production
`uosserver`, nginx and UnPoller are active, the backup unit reports success,
and the daily timer is enabled.

Native Network configuration-only backups run daily at **01:00 Europe/Istanbul**
(22:00 UTC on the preceding date), correcting the earlier UTC schedule note.
`autobackup_10.6.106_20260926_2200_1790460000018.unf` exists at 20,992 bytes;
the separate pre-upgrade `10.5.67.unf` also exists. The full offsite archive,
rather than a configuration-only `.unf`, was used for the booted restore above.

## Remaining acceptance checks

1. Verify a real 6-GHz or MLO client association. The owner has accepted the
   improved speeds; retain the approved 1 Gb/s Ethernet limit.
2. Join each WLAN with real clients and prove the expected VLAN address, IoT
   restrictions, Home Assistant discovery/control and administration VPN access
   from outside the LAN. Qualify 6 GHz separately in the Turkey domain.

Repository validation passed: the cloud configuration check, 38 network tests,
five backup ordering/failure tests, 43 credential activation tests, formatting
and secret scanning. The final OpenTofu plan reported no changes for the live
controller resources.

The B2 enrollment additionally passed `cloud-configuration` and
`services-activation-contract`, including the lifecycle-response normalization
regressions. The deployed backup unit now provisions a root-only Restic cache
directory, removing the systemd environment's missing-home cache warning.

## Second AP preparation — 2026-10-05

The owner supplied Ethernet MAC `A4:F8:FF:8E:53:5C` for a second U7 Pro Max
connected directly to the CCR2004 through a UniFi 30 W PoE+ adapter.

- Live inspection found `ether5` disconnected and absent from all bridges.
  It now belongs to `bridge-lan`, with PVID 90, tagged VLANs 10/50, ingress
  filtering enabled, and edge mode enabled. Other VLAN memberships were
  preserved and all inventory-defined memberships passed read-back checks.
- The static-only management DHCP server now reserves `10.21.90.7` for this
  MAC. Only this lease receives `infra-unifi-inform`, forced DHCP option 43
  with raw value `01040a15287f`, pointing to `10.21.40.127:8080`.
- The existing routed inform/STUN rules already permit management-VLAN APs.
  A separate administration-VPN SSH rule was added for `.7`.
- The controller's Neutron security group now admits inform TCP 8080 and STUN
  UDP 3478 from `.7/32`. Existing rules were retained and both new rules were
  read back. `imports-ap2.tf` records their IDs for the next GitOps apply so
  OpenTofu imports the pre-staged rules instead of creating duplicates.
- UniFi OS and nginx were active, with inform/STUN sockets listening. The
  original AP was Connected at `.6`, and both existing WLANs were enabled
  and assigned to the All APs group.
- The router apply completed without failures. All 46 network automation tests,
  Ansible syntax validation, YAML validation and OpenTofu formatting passed.

The second AP was not connected during this verification: `ether5` reported
`no-link`, and its reservation was `waiting`, last seen `never`. Adoption,
radio widths/channel selection, negotiated link speed and real-client VLAN
and coverage checks remain pending physical connection.

## Second AP adoption — 2026-10-05

After the owner connected and powered the AP, DHCP option 43 discovered the
expected MAC `A4:F8:FF:8E:53:5C` at `10.21.90.7`. Layer-3 adoption completed,
and the controller name is now **U7 Pro Max 2**.

- Both devices are adopted in the native All APs group. The new AP inherited
  `Rooftrollen` on third-party VLAN 10 with 5/6 GHz, WPA3, required PMF and MLO;
  `Rooftrollen_IoT` references third-party VLAN 50 on 2.4 GHz with WPA2-AES.
  The existing WLAN configuration and first AP's radio settings were retained.
- The new AP's factory firmware `7.0.48.15574` was updated to `8.7.11.19419`,
  matching the first AP. The initial controller upgrade requests did not start
  an update. The explicit official U7PROMAX firmware URL completed the update;
  its size `65191739` and SHA-256
  `f55f221433b4fe3eace4438cf93e5ab313138928a26c2d6cf0ffaf10f653fb4d` matched
  the artifact recorded for the original AP.
- Native adoption assigned `http://unifi:8080/inform`. The router now owns the
  exact local A record `unifi -> 10.21.40.127`, TTL one hour, with subdomain
  matching disabled. Its scoped `unifi-dns` apply and resolution proof passed.
  The new AP reconnected using that inform URL after both the firmware update
  and a subsequent software restart.
- Radio read-back showed 2.4 GHz channel 6 at 20 MHz, 5 GHz channel 100 at
  80 MHz, and 6 GHz channel 37 at 160 MHz. All three radios reached RUN and the
  three expected WLAN interfaces were up. These channel blocks are separate
  from the original AP's observed channels 11/40/85 at the same widths. The
  5-GHz radio performs a DFS radar check after startup before transmitting.
- A real trusted client associated on the new AP's 5-GHz and later 6-GHz radio,
  with address `10.21.10.103` and reported VLAN 10. Client byte counters
  increased. This proves trusted client forwarding; no new room coverage,
  throughput, MLO negotiation or real IoT-client test was performed remotely.
- The new AP initially negotiated **1 Gb/s full duplex**. After the firmware
  restart, both RouterOS and UniFi reported **100 Mb/s full duplex**. RouterOS
  retained automatic negotiation and advertised gigabit; the link partner
  advertised only 10/100 Mb/s. Restarting negotiation on only `ether5` and
  one software restart of only this AP did not restore gigabit. The owner
  subsequently completed a full PoE-adapter power cycle; its fresh uptime and
  continued 100-Mb/s link were verified. The later investigation below tests
  firmware and PHY behavior without assuming that the cable is the cause.
- The original AP remained Connected, firmware 8.7.11, with its existing
  1-Gb/s full-duplex uplink throughout the second AP's configuration.
- All **47** network automation tests and Ansible syntax validation passed.
  YAML validation passed with line-length warnings; OpenTofu formatting and
  `git diff --check` passed. Monitoring's existing AP discovery and site-wide
  disconnection alert cover both devices without a per-MAC rule change.

## Ethernet investigation on both APs — 2026-10-05

The owner reopened the original AP's 2.5-Gb/s issue together with the new AP's
100-Mb/s downshift. SSH diagnostics used the original AP's pinned RSA key. The
new AP's RSA key matched the fingerprint enrolled in the authenticated HTTPS
controller (`SHA256:aiVjs1/rTF7FtF1rNV8P3BaFicmQk3SfNNfkFukPyOU`); that public
key is now recorded in `deployments/homelab/ssh-host-keys.json`.

- Both APs are board revision 6, with the `nss-dp` Ethernet driver and external
  QCA8081 PHY (`0x004dd101`, PHY address 20). Both report automatic negotiation
  and support/advertise 1 and 2.5 Gb/s. EEE is already disabled on both APs and
  on the original AP's Omada profile. Disabling EEE therefore cannot explain
  or fix this observed configuration.
- On 8.7.11, the new AP's native `ethtool -S eth0` identifies the controller's
  776 receive errors as `rx_crc_err`, rather than generic software drops.
  Router-side FCS counters are zero. CRC errors do not identify which element
  of the Ethernet path is faulty.
- The exact official U7PROMAX 8.6.11 release was verified against Ubiquiti's
  firmware catalog before installing it on each AP, one at a time. Its SHA-256
  is `bde9ddea1628b2813fd2c7514c27e5245014ef5005cf04e01734e5d5a63b5def` and
  size is 64833923 bytes. WLAN/VLAN/radio configuration survived both updates.
- The new AP initially linked at 1 Gb/s on 8.6.11, with zero CRC errors. After
  about two minutes its kernel recorded repeated 1-Gb/s links followed by
  physical link loss, then a 100-Mb/s link. The transient gigabit connection is
  not a successful fix. At the stable 100-Mb/s rate, 20 gateway probes passed
  with zero loss.
- On 8.6.11 the original AP still failed an automatic 2.5-Gb/s test. A port-6
  STP-edge test and a fixed-2.5-Gb/s/full-duplex test with flow control also
  failed. Native logs show repeated `PHY Link up speed: 2500` followed by link
  loss. The switch's blocking transitions accompany these physical link
  changes; an edge-port setting did not resolve them. Each test restored
  port 6 to 1 Gb/s full duplex and restored the original profile, then verified
  SSH and zero-loss gateway probes.
- Gigabit-only advertisement on CCR2004 `ether5`, with negotiation still
  enabled, did not produce a sustained link. Reapplying gigabit-only
  advertisement in the new AP's native driver also produced short-lived
  gigabit links and subsequent downshift. Both sides' original settings were
  restored. The AP driver does not support `ethtool -r` or the PHY downshift
  tunable; its master/slave setter requires an unavailable netlink interface.
- A final new-AP comparison with official U7PROMAX 8.0.49 also yielded a
  100-Mb/s link. Its image matched catalog SHA-256
  `a503d36a83b4cf7a48927ca603b3106fcdb90b622f720175002f7f6b71047985` and size
  45200745 bytes. Twenty gateway probes and five internet probes passed with
  zero loss at 100 Mb/s. Firmware differences therefore have not produced a
  sustained higher-speed link on this Ethernet path.

Primary-source research supports investigating firmware/PHY interoperability,
but does not establish the cause of this installation:

- [Ubiquiti's 8.7.11 release](https://community.ui.com/releases/42b6f9d9-3dba-4cda-bde1-b8157edc1299)
  includes an Ethernet negotiation improvement for fixed-speed switch ports.
  [First-hand U7 Pro Max reports](https://community.ui.com/questions/af53b148-b666-4239-a2e0-6a2ec989a1f2?parentReplyIds=61225d15-f72a-473a-9bb1-824c16228f85&replyId=f9802ef4-eeb9-4083-b5a9-bf5e4c8e1fde)
  also describe 2.5-Gb/s failures and recovery at 1 Gb/s, with mixed results on
  firmware changes. Reports about U7 Pro XG/XGS are different hardware and
  cannot establish a Pro Max defect.
- [MikroTik's Ethernet documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/8323191/Ethernet)
  requires auto-negotiation for gigabit/NBASE-T copper. Tests restricted the
  advertised rate rather than disabling negotiation.
- [TP-Link's hardware-v3.0 firmware 3.0.29 release notes](https://static.tp-link.com/upload/firmware/2026/202608/20260814/SG3210XHP-M2(UN)_v3.0_3.0.29%20Build%2020260804.pdf)
  apply to this SG3210XHP-M2 hardware, unlike the separate v3.20 firmware. The
  listed fix is Layer-3 forwarding throughput; it does not promise an AP PHY
  negotiation fix. The switch remains on 3.0.0 Build 20230725 Rel.71176.

The owner subsequently replaced the second AP's cable and requested that work
on the original AP's 2.5-Gb/s issue stop. Its working 1-Gb/s port setting and
original profile remain in place; further physical isolation is deferred by
the owner. Firmware restoration is cleanup of the temporary diagnostic
downgrade, without further link experiments.

Final read-back after that cable replacement:

- Both APs are Connected on the original/current official 8.7.11.19419 release,
  with all three radios RUN. The first AP's temporary 8.6.11 downgrade was
  restored through the controller's cached-firmware upgrade. Port 6 remains
  1 Gb/s full duplex with the original `infra-ap-trunk` profile. Native CRC and
  drop counters are zero, and all 20 gateway probes passed. Its existing auto
  channel settings selected 1/36/85 on final read-back, at 20/80/160 MHz; no
  manual radio changes were made during cleanup.
- The second AP is **1 Gb/s full duplex** on both RouterOS and native AP
  read-back. Its native uptime advanced from 130.68 to 428.73 seconds during
  150 gateway probes with 1472-byte ICMP payloads, spaced two seconds apart.
  All 150 arrived, with zero loss. CRC, overflow and drop counters stayed zero;
  `carrier_changes` stayed at 1, representing only the initial link-up. Native
  logs contain a single 1-Gb/s link-up, with no subsequent physical drop.
  Earlier post-replacement gateway and internet probes also had zero loss.
- CCR2004 `ether5` retains its original automatic negotiation and advertised
  10/100/1000 modes. Its receive/transmit FCS counters remain zero, and its
  historical `rx-error-events=2` did not increase. Both AP DHCP reservations
  are bound to their enrolled MAC addresses.
- The new AP's channels/widths remain 6/20, 100/80 and 37/160. WLAN security,
  VLAN mappings, site country and the all-APs group passed read-back. Trusted
  clients were observed on its 5/6-GHz radios with VLAN-10 addresses, and IoT
  clients on 2.4 GHz with VLAN-50 addresses. This verifies association and
  addressing, without claiming measured room coverage or client throughput.
- The controller's automatic firmware updates remain enabled. The original
  AP's 2.5-Gb/s issue is deferred by the owner. The second AP's higher-speed
  link is verified after the cable replacement; this short observation does
  not establish long-term reliability or isolate a specific cable contact.
