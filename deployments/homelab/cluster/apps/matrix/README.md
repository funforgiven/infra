# Private Matrix community

Synapse, Matrix Authentication Service (MAS), Element Web and the encrypted
alert relay serve a closed community: federation, remote media, registration,
guests and URL previews are off, and members are ZITADEL users holding the
Matrix project's `matrix-member` role (first login provisions them through
MAS). Synapse, MAS and relay configuration, signing keys and the bot identity
live in `runtime.sops.yaml`; after editing it outside `matrix-admin`, restart
the workloads that mount the changed keys (`runtime-rollouts.yaml`).

## Backups and recovery

PostgreSQL (`synapse` and `mas`) is backed up by Barman Cloud like the other
CloudNativePG databases. The live cluster was created empty, so rebuilding it
from the archive means switching `bootstrap` in `database.yaml` from `initdb`
to `recovery` first (the comment there has the exact stanza). Velero snapshots
only the media and relay volumes ([backups](../../infrastructure/backups/README.md)).

Keep the Flux stage suspended until the database, media and relay state are
restored. The relay snapshot in `relay/backups` holds the SQLite queue, the
crypto store of bot device `INFRA_ALERTS` and an encrypted canary; move the
recovered databases to the root of the relay volume and verify them offline
before starting the relay. **Never enroll the bot device against an empty
crypto store**: replacing it is a planned identity change that every
recipient must re-verify. Start PostgreSQL, MAS, Synapse, then the relay;
compare the bot fingerprint and test decryption, SSO, media and push before
reopening routes. Members' encrypted history depends on their own Element
recovery keys.

Two isolated checks run unattended:

- `matrix-restore/postgres-restore-test` recovers the Barman archive into a
  disposable cluster with no WAL archiver and checks both databases.
- The monthly restore drill restores the media and relay volumes into
  `matrix-restore` behind a Cilium deny-all and runs `restore-verify`
  (`restore.py`), which decrypts the canary with the recovered session.

## Alert relay and devices

Alertmanager and enrolled hosts post to the relay, which delivers only to
approved devices and never falls back to plaintext. Device changes pause
delivery until approved; the queue stays durable. Compare a recipient's
Ed25519 session key (Element: Settings → Encryption → Advanced) over a trusted
channel, then:

```sh
nix run .#matrix-admin -- approve-device --user @NAME:matrix.fahrican.com \
  --device DEVICE_ID --fingerprint 'ED25519 KEY'
```

Enroll a host producer with `configure-alerting --phase dual --host NAME`.
`rollout.json` records the Telegram cutover: alerts still go to both Telegram
and Matrix (critical/error also by email). After seven days of verified dual
delivery, run `qualify --mobile-and-recovery-checked` from outside the LAN,
`configure-alerting --phase matrix` within a day, deploy, then
`retire-telegram` and revoke the bot through BotFather.

## Image

`nix build .#matrix-runtime-image` builds the one image every workload uses;
`nix run .#matrix-qualify-local` runs a disposable end-to-end test. After a
passing test, `nix run .#publish-image -- result` pushes it; pin the printed
digest in `kustomization.yaml`. The `matrix-registry` pull secrets
(`registry.sops.yaml` for `matrix`, `registry-restore.sops.yaml` for
`matrix-restore`) hold a `forge-runner` registry login; change them with
`sops edit` when that credential rotates.
