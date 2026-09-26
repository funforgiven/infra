# Migration validation — 2026-09-26

The controller is deployed, but the wireless cutover is **not complete**. The
U7 was adopted and subsequently lost management connectivity. This record
captures observations at 20:40 UTC, not a successful acceptance sign-off.

## Verified deployment

| Area | Observation |
| --- | --- |
| Ownership | UniFi is AP-only. MikroTik retains routing, DHCP, firewall and VPN. Omada retains its switch. |
| Replacement AP | U7 Pro Max `74:F9:2C:3C:99:F7`, on the former EAP670 cable at SG3210XHP-M2 port 6. |
| Port contract | `infra-ap-trunk`: untagged/native VLAN 90, tagged VLANs 10 and 50. Switch reconciliation reports no changes or blockers. |
| Address | Router reservation `10.21.90.6`; old EAP address `10.21.90.4` preserved. |
| Controller | Dedicated retained-volume VM, `192.168.80.12` / `10.21.40.127`; UniFi OS 5.1.42 and Network 10.5.67. Cloud-init completed. |
| Authentication | Generated local owner and separate Network Read Only monitoring user, stored in administrator-only SOPS. Remote access disabled; diagnostics disabled; default automatic updates retained. |
| WLAN configuration | `Rooftrollen` references the third-party VLAN-10 network; `Rooftrollen_IoT` references VLAN 50. Existing PSKs retained. Controller API read-back confirms both references. |
| Origin TLS | Private CA and hostname verification passed against nginx; leaf renewal timer enabled. Services-cluster TCP probe to `192.168.80.12:8443` succeeded. |
| Exporters | Node exporter, controller health textfile and UnPoller running. Read-only polling reports the AP as disconnected. |
| Router access | Narrow inform/STUN, private setup/SSH and VPN AP-SSH rules applied. No WAN port forwards added. |

The private DNS record, Envoy HTTPS route, certificate SAN and Prometheus
resources passed local validation and Kubernetes server-side dry runs. They
have **not been activated**: publishing the repository changes to `origin/main`
is awaiting explicit approval after automatic approval review rejected the
push. `https://unifi.fahrican.com` is therefore not yet a verified access path.
The native private recovery UI is on `10.21.40.127:11443`.

## AP connectivity failure

The controller recorded adoption completion at 20:02:51 UTC. Its stored inform
URL is `http://10.21.40.127:8080/inform`. Its last reported firmware is
`7.0.48.15574`; no firmware upgrade completion was observed. It is currently
offline, and SSH at its reserved address is unavailable. The controller has the
new device SSH credential, but authentication with that credential on the AP
has not been verified.

Router logs show the AP releasing its lease after adoption, then repeatedly
discovering DHCP. A packet capture shows a correctly addressed DHCP offer with
the matching transaction ID; it contains no subsequent request/acknowledgment.
The switch learns the AP MAC on VLAN 90. The precise cause is unresolved.

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

Obtain the physical LED state before selecting the next recovery step. Do not
infer that the AP is forwarding either WLAN merely from its adopted flag.
For immediate wireless rollback, reconnect the EAP670 to this same port 6; its
old address and Omada WLAN objects remain available.

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

1. Recover the AP's management address and verify Connected state, the inform
   endpoint and the managed SSH credential.
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
