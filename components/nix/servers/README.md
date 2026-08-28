# Service hosts

This component defines the NixOS service hosts and their shared backup and
alerting modules. The current Home Assistant host is built from this flake.
Mail uses the separate AWS configuration under
`components/cloud/services/mail-aws/`.

The service accounts use the pinned SSH key and have no login password.

## Deploy host secrets

Provider credentials are first stored as SOPS ciphertext. Locally generated
passwords are written directly to SOPS. To install one declared profile on a
host, run:

```sh
nix run .#enroll-service-host-secrets -- SSH_TARGET PROFILE
```

The command decrypts only the selected profile and streams mode-`0400` files to
the host over SSH. It does not put values in command arguments. Available
profiles and credential-rotation procedures are documented in the
[service operations guide](../../../deployments/homelab/cloud/services/ACTIVATION.md).

## Off-site backups

Each stateful NixOS host declares its Restic paths and retention in Nix. The
backup unit starts only when these root-owned files exist:

- `/var/lib/backup-bootstrap/repository`
- `/var/lib/backup-bootstrap/password`
- `/var/lib/backup-bootstrap/environment`

Every host has a separate Backblaze application key restricted to its own
prefix in the `fahrican-cloud-recovery` bucket. Initialize a new empty prefix
once, then run and restore the first backup before placing important data on the
host:

```sh
nix run .#initialize-services-restic -- check
nix run .#initialize-services-restic -- apply
```

The timer runs daily and retains 14 daily, 8 weekly, 12 monthly, and 3 yearly
snapshots.

After the HAOS migration, Home Assistant uses its native encrypted backups.
Keep the old Restic path and NixOS root volume until an isolated HAOS restore has
succeeded.

## Alerts

Service hosts expose node and systemd metrics on TCP 9100 to the services
subnet. A successful Restic run updates a node-exporter textfile metric; the
services cluster alerts if the exporter is unavailable or the last successful
backup is older than 26 hours.

Critical units also have a local `OnFailure` Telegram notifier. Its dedicated
profile installs the infrastructure bot token and chat ID at:

- `/var/lib/monitoring-bootstrap/bot-token`
- `/var/lib/monitoring-bootstrap/chat-id`

The AWS mail appliance uses public protocol probes and CloudWatch alarms instead
of this host profile.
