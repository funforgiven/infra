# Services hosts

This OpenTofu root creates the persistent OpenStack hosts that need capabilities
which do not fit the Kubernetes services cluster:

- Hermes receives a private services-network port and a fixed provider-LAN
  floating address for administration.
- Home Assistant is dual-homed. Its private address is used by the Kubernetes
  gateway, while its fixed provider-LAN port preserves local discovery traffic.
  The NixOS root remains rollback media while a separate Home Assistant OS root
  becomes active only through the explicit `home_assistant_platform` cutover.
- Persistent volumes, fixed ports, and the Hermes floating address are protected
  from destruction. The Home Assistant instance is intentionally replaceable so
  OpenTofu can move those retained ports between retained boot volumes.

The root accepts only a full Git revision. The promotion app verifies a clean,
SSH-signed commit, builds the matching Hermes image, and imports the pinned
official HAOS 18.2 QCOW2 only after verifying its archive SHA-256. Both artifacts
are private, protected, and carry their source digests as Glance properties.

Image promotion and host activation are deliberately separate:

1. Merge and sign the NixOS image configuration.
2. From a services-project OpenStack shell, run
   nix run .#promote-service-images.
3. Verify the promoted image and record its full signed revision as a candidate.
4. Leave wave 83's active image revision unchanged until a separate migration
   has staged runtime credentials and a recovery-tested retained root.

The promotion command never edits the active revision. Changing that value on
an already provisioned host would ask OpenTofu to replace a protected boot
volume; it is therefore not an image-publication step and must be implemented as
an explicit retained-volume migration. HAOS uses its own retained root and the
platform selector below, so publishing HAOS does not alter the running NixOS VM.

## Home Assistant OS cutover

Keep `home_assistant_platform = nixos` while preparing the migration. Create a
native full encrypted Home Assistant backup, download its emergency kit, and
restore that backup into an isolated HAOS instance. Run the promotion app and
verify that the protected `haos-18.2` image has the pinned source digest.

Only then change the Git variable to `haos`. OpenTofu stops and replaces the VM,
retains both boot volumes and both fixed ports, and boots HAOS without cloud-init
or guest credentials. Restore the verified native backup during onboarding. The
services-network port obtains `192.168.80.10` through Neutron DHCP. Configure the
provider-LAN NIC once through HAOS with `10.21.40.120/24` and route
`10.21.10.0/24` through `10.21.40.1`; this unavoidable appliance-state exception
is tracked in the repository.

After restore, configure the native Backblaze B2 backup location with bucket
`fahrican-cloud-recovery`, prefix `services/hosts/home-assistant/`, and the
existing independently scoped Home Assistant application key. Enable encrypted
daily automatic backups, retain at least 14, perform another isolated restore,
and only then retire the NixOS rollback volume and Restic contract in a separate
reviewed change.

The controller uses the existing administrative runtime Secret, while the
provider explicitly re-scopes authentication to the services project. No
credential or generated guest secret is accepted as an OpenTofu variable.
