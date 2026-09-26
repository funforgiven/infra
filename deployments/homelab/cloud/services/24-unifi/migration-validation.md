# Migration validation — 2026-09-26

The controller and AP are online using a **temporary 1 Gb/s Ethernet limit** on
switch port 6. Automatic 2.5 Gb/s negotiation does not sustain connectivity on
the current cable/switch path, including after updating the AP to 8.7.11. This
record includes recovery observations through 21:14 UTC; full client and
offsite-recovery acceptance remains pending.

## Verified deployment

| Area | Observation |
| --- | --- |
| Ownership | UniFi is AP-only. MikroTik retains routing, DHCP, firewall and VPN. Omada retains its switch. |
| Replacement AP | U7 Pro Max `74:F9:2C:3C:99:F7`, on the former EAP670 cable at SG3210XHP-M2 port 6. |
| Port contract | `infra-ap-trunk`: untagged/native VLAN 90, tagged VLANs 10 and 50. Switch reconciliation reports no changes or blockers. |
| Physical link | Port 6 at 1 Gb/s full duplex as a temporary workaround. The Omada reconciler preserves physical speed/duplex; the limit is recorded in `unifi-network.yaml`. |
| Address | Router reservation `10.21.90.6`; old EAP address `10.21.90.4` preserved. |
| Controller | Dedicated retained-volume VM, `192.168.80.12` / `10.21.40.127`; UniFi OS 5.1.42 and Network 10.5.67. Cloud-init completed. |
| Authentication | Generated local owner and separate Network Read Only monitoring user, stored in administrator-only SOPS. Remote access disabled; diagnostics disabled; default automatic updates retained. |
| WLAN configuration | `Rooftrollen` references the third-party VLAN-10 network; `Rooftrollen_IoT` references VLAN 50. Existing PSKs retained. Controller API read-back confirms both references. |
| Origin TLS | Private CA and hostname verification passed against nginx; leaf renewal timer enabled. Services-cluster TCP probe to `192.168.80.12:8443` succeeded. |
| Exporters | Node exporter, controller health textfile and UnPoller running. The disconnected-AP metric was observed during the initial failure. |
| Router access | Narrow inform/STUN, private setup/SSH and VPN AP-SSH rules applied. No WAN port forwards added. |

The private DNS record, Envoy HTTPS route, certificate SAN and Prometheus
resources passed local validation and Kubernetes server-side dry runs. They
have **not been activated**: publishing the repository changes to `origin/main`
is awaiting explicit approval after automatic approval review rejected the
push. `https://unifi.fahrican.com` is therefore not yet a verified access path.
The native private recovery UI is on `10.21.40.127:11443`.

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

After recovery, the controller identified the three associated clients on
`Rooftrollen_IoT`; the Android phone was no longer associated, so its browsing
retest is still required. The AP radio inventory showed `Rooftrollen` on
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
Test a known-good short cable on the same port next, then retest automatic speed
with a bounded return to 1 Gb/s if necessary. A switch-wide firmware update
needs a separate maintenance window because it interrupts the other endpoints.

For immediate wireless rollback, reconnect the EAP670 to this same port 6; its
old address and Omada WLAN objects remain available. Restore automatic port
speed when qualifying that rollback if its previous 2.5 Gb/s link is required.

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

1. Confirm phone browsing after the recovery, qualify both WLANs, and resolve
   the temporary 1 Gb/s Ethernet limit using the cable/port/firmware checks above.
2. Publish/reconcile the GitOps changes after approval; verify DNS, Envoy route
   and BackendTLSPolicy conditions, browser login and Prometheus targets/alerts.
3. Refill the B2 master intake privately, reconcile the restricted writer, run
   the first offsite backup and complete an isolated restore with login/site
   verification.
4. Join each WLAN with real clients and prove the expected VLAN address, IoT
   restrictions, Home Assistant discovery/control and administration VPN access
   from outside the LAN. Qualify 6 GHz separately in the Turkey domain.

Repository validation passed: the cloud configuration check, 38 network tests,
five backup ordering/failure tests, 43 credential activation tests, formatting
and secret scanning. The final OpenTofu plan reported no changes for the live
controller resources.
