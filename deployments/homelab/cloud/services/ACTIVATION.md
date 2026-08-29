# Service operations

The services platform is already enabled. Flux and OpenTofu reconcile its
committed configuration; do not use `flux resume` or edit a live Kubernetes
Secret as a persistent change.

This guide covers the remaining manual operations: enrolling or rotating
provider credentials, reconciling provider-created values, initializing a new
Restic repository, promoting host images, and completing the Home Assistant OS
migration.

Run commands from the repository root in the flake-locked environment unless a
procedure says otherwise.

## Credential handling

Externally issued credentials enter through an ignored, mode-`0600` file named
`KEY.key`. Put exactly one value in the file. Do not paste a credential into a
command argument, shell history, chat, log, or tracked file.

The accepted intake names and their issuers are documented in
[`../../../../secrets/README.md`](../../../../secrets/README.md). Enroll one
value with:

```sh
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake KEY
```

The command verifies the file type and mode, writes the value to its declared
SOPS document, and truncates the intake file after successful encryption.

To enter a value interactively without placing it in a command argument:

```sh
nix run .#enroll-services-credential -- KEY
```

Locally generated passwords and cookie secrets do not have intake files. Rotate
one declared generated value with:

```sh
nix run .#generate-services-credential -- --rotate KEY
```

Review only ciphertext structure and diff statistics. Never print a decrypted
document to inspect the result.

## Factorio credentials

Factorio's public matching service needs the host account name and the service
token from that account's profile. The game password is also an external value
because it must remain available in the password manager for sharing with
friends. Put each value in its correspondingly named mode-`0600` intake file,
then enroll it without placing the value in shell history:

Log into the Factorio account from the game client first, then close the game
and open `player-data.json`. Copy only `service-username` into
`FACTORIO_USERNAME.key` and `service-token` into `FACTORIO_TOKEN.key`. The
default client file is:

- Linux: `~/.factorio/player-data.json`;
- Windows: `%APPDATA%\\Factorio\\player-data.json`;
- macOS: `~/Library/Application Support/factorio/player-data.json`.

Steam Cloud may also keep a copy under its app ID `427520`, but prefer the
Factorio user-data path. Never use the account password as the token.

`FACTORIO_GAME_PASSWORD.key` is one-way intake: enrollment truncates it after
successful encryption. Preserve the generated value separately in the password
manager or the ignored mode-`0600` `FACTORIO_FRIENDS_PASSWORD.key` handoff file
before enrollment. Share only that game password with players; never share the
matching-service token.

```sh
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake FACTORIO_USERNAME
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake FACTORIO_TOKEN
nix run .#enroll-services-credential -- \
  --from-file --intake-directory /absolute/path/to/intake FACTORIO_GAME_PASSWORD
```

Use at least 12 characters for the game password. The generated RCON password
is already stored as SOPS ciphertext; it is never shared, and RCON remains
bound to pod loopback. Public visibility requires player verification, so every
player must use a client authenticated to a valid Factorio account in addition
to knowing the shared game password. After the ciphertext is committed and the
services-cluster reconciler has delivered `factorio-runtime`, apply the
Git-declared RouterOS port-forward surface. This reconciles the Factorio WAN
destination NAT/filter pair, its local-LAN NAT-reflection/filter pair, and the
provider-to-WAN discovery source-port pin, plus the existing Syncthing forwards
idempotently:

```sh
cd components/cloud/network-automation
ansible-playbook reconcile-routeros.yaml \
  --limit core_router --tags wan-port-forwards
```

Wait for the `factorio` StatefulSet and LoadBalancer address, then verify a
public-browser or direct connection to `10.21.40.123:34197` and one real WAN
connection from outside the site. Friends find `Fahrican Space Age` in the
public game browser, authenticate their Factorio client, and enter the
separately shared password. Confirm that a local-LAN client can join through
the public listing as proof of the scoped NAT reflection. Do not accept the
deployment until an on-demand `services-daily` backup and the isolated restore
qualification both succeed.

## Provider reconciliation

### Backblaze

The Backblaze reconciler uses a temporary master application key to create the
declared prefix-restricted writers and store the returned credentials as SOPS
ciphertext. Give it an intake directory containing the two mode-`0600`
`B2_MASTER_*` files:

```sh
nix run .#reconcile-services-backblaze -- apply \
  --bootstrap-directory /absolute/path/to/intake
```

It clears the master files only after the declared keys and bucket policy have
been reconciled successfully. Cluster and host writers remain independent and
cannot cross their assigned prefixes.

### Telegram

Bot creation and token rotation remain manual BotFather operations. Follow
[`TELEGRAM.md`](TELEGRAM.md), enroll the infrastructure bot token, send the
required `/activate` message in its private alert group, and then run:

```sh
nix run .#reconcile-services-telegram -- apply
```

Use `apply --rediscover` only when intentionally moving the bot to a new alert
group.

### Resend and AWS mail

After the Resend domain is verified and its administrator key is enrolled:

```sh
nix run .#reconcile-services-resend -- apply
```

This creates or rotates the domain-scoped sending key and records the provider
DNS data used by the service DNS controller. Publish the resulting sending key
to the AWS mail appliance with:

```sh
nix run .#publish-aws-mail-resend
```

Then require the Stalwart reconciler to converge and repeat the external mail
checks in the [AWS mail runbook](../../../../components/cloud/services/mail-aws/README.md).

## Initialize a host Restic repository

Run this once for a new empty host prefix after its Backblaze writer and Restic
password are encrypted:

```sh
nix run .#initialize-services-restic -- check
nix run .#initialize-services-restic -- apply
```

The initializer creates only the repository metadata and verifies it through
Restic. It does not create another application key. Afterward, enroll the
declared host profiles over the pinned SSH identity:

```sh
nix run .#enroll-service-host-secrets -- SSH_TARGET PROFILE
```

Run the first backup and restore it to an isolated temporary host before placing
stateful data on the service. The scheduled NixOS backup uses the same
prefix-restricted writer.

## Promote service-host images

Image promotion requires a clean, SSH-signed commit and services-project
OpenStack credentials:

```sh
nix run .#promote-service-images
```

The command builds and imports the Home Assistant NixOS image for the signed
revision and verifies the pinned official HAOS image. Promotion does not change
the revision or boot volume used by the running host. Make host replacement or
volume cutover a separate reviewed change with a tested recovery path.

Before changing host inputs, evaluate the repository and build the image locally:

```sh
nix flake check --no-build --accept-flake-config
nix build .#home-assistant-openstack-image --no-link --accept-flake-config
```

## Home Assistant OS cutover

The active selector remains `nixos` until all preparation and recovery checks
below pass.

1. Create a full encrypted native Home Assistant backup and download its
   emergency kit.
2. Restore that backup into an isolated HAOS instance and verify the integrations
   and representative history required for recovery.
3. Promote and verify the pinned HAOS image.
4. Change `home_assistant_platform` to `haos` in
   [`../undercloud/83-services-hosts/tofu.yaml`](../undercloud/83-services-hosts/tofu.yaml).
   Review the plan: it must retain both fixed ports and both protected boot
   volumes while replacing only the VM attachment.
5. Restore the tested backup during HAOS onboarding.
6. Configure the provider-LAN interface as `10.21.40.120/24` with a route to
   `10.21.10.0/24` through `10.21.40.1`. The private services-network address is
   supplied by Neutron DHCP.
7. Configure forwarded headers for only `192.168.80.0/24`, confirm the pending
   HTTP setting through `https://home.fahrican.com`, and verify local hardware
   discovery.
8. Configure encrypted daily native backups in the existing Backblaze bucket
   under `services/hosts/home-assistant/` with the Home Assistant-specific key.
9. Complete another isolated restore from a post-cutover backup.

Keep the old NixOS root volume until the post-cutover restore succeeds. Retire
the old volume and Restic configuration only in a separate change. The provider
NIC, onboarding state, HTTP proxy setting, and UI-only integrations are appliance
state; back them up after each accepted change.

## Verification

After credential, provider, or image changes, run the focused repository checks
before committing:

```sh
nix build .#checks.x86_64-linux.cloud-configuration \
  --no-link --accept-flake-config
nix build .#checks.x86_64-linux.services-activation-contract \
  --no-link --accept-flake-config
```

Review the SOPS diff as ciphertext, verify the promoted image revision, and keep
the working tree clean. Service health, backup availability, and an isolated
restore are still required before accepting application data.
