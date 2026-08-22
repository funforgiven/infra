# Home Assistant route

Home Assistant runs as a dedicated HAOS appliance, not in Kubernetes. The
existing NixOS VM remains live until the migration gate passes. This layer
declaratively bridges the stable private address 192.168.80.10:8123 into the
services Gateway and publishes only home.fahrican.com.

Keep the Git platform selector on `nixos` until a full encrypted native backup,
its emergency kit, and an isolated HAOS restore are qualified. The migration
then replaces only the VM attachment, retains the protected legacy Cinder root,
and restores the backup during HAOS onboarding. Configure the provider NIC and
operator-LAN route documented in the hosts root, trust only `192.168.80.0/24`
for forwarded headers, and confirm the pending HTTP settings through
`https://home.fahrican.com`. Enroll Home Assistant's native Backblaze B2 backup
location with the existing prefix-scoped key, then require encrypted daily
backups and a post-cutover restore before retiring the legacy volume. These
appliance-state changes are registered in `manual-exceptions.yaml`.
