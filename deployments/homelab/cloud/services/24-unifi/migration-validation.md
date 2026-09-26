# Migration validation — 2026-09-26

The controller and AP are online using a **temporary 1 Gb/s Ethernet limit** on
switch port 6. Automatic 2.5 Gb/s negotiation does not sustain connectivity on
the current cable/switch path, including after updating the AP to 8.7.11. This
record includes recovery, wireless and gateway checks through 23:25 UTC. The owner
accepted retaining 1 Gb/s for now; final wireless throughput and offsite-recovery
acceptance remain pending.

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
  scrape, and the AP-metrics alert cleared. The backup-stale alert remains
  pending because no offsite backup has succeeded.
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
`mld0` interface. A client MLO association and final speed result still require
verification; enabling the feature alone does not prove either.

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

This is **not an offsite backup or a booted restore test**. The B2 master intake
files are empty, so the separate prefix-scoped UniFi writer and initial offsite
backup remain pending. No successful offsite-backup metric was fabricated.
Native Network configuration-only backups are scheduled daily at 01:00 UTC;
the first scheduled file has not yet been verified. Follow the isolated restore
procedure in the runbook after enrollment, keeping the restored controller
unable to contact production APs.

## Remaining acceptance checks

1. Retest throughput after the width/security changes and verify a real 6-GHz
   or MLO client association. Retain the approved 1 Gb/s Ethernet limit.
2. Refill the B2 master intake privately, reconcile the restricted writer, run
   the first offsite backup and complete an isolated restore with login/site
   verification.
3. Join each WLAN with real clients and prove the expected VLAN address, IoT
   restrictions, Home Assistant discovery/control and administration VPN access
   from outside the LAN. Qualify 6 GHz separately in the Turkey domain.

Repository validation passed: the cloud configuration check, 38 network tests,
five backup ordering/failure tests, 43 credential activation tests, formatting
and secret scanning. The final OpenTofu plan reported no changes for the live
controller resources.
