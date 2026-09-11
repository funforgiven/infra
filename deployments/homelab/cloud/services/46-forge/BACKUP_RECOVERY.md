# Online backup recovery — 2026-09-10

The retired backup sidecar held Forgejo stopped while compressing and hashing
its complete data volume. On September 10 the window lasted from 20:19:51 to
20:28:10 UTC. Launcher requests received HTTP 503; per-Job alert identities
then produced a new notification for successive one-minute retries, even when
later controller executions succeeded.

Controller failure alerts now aggregate by CronJob and clear when a newer
execution succeeds. Atollion execution failures retain a separate aggregate
alert. Promtool tests exercise failure/retry turnover, recovery, suspension,
missing previous success, and multiple concurrent application failures.

## Live online export

The first online export used a Cinder/CSI point-in-time snapshot of the existing
Forgejo data volume. The source pod and all its containers remained unchanged:

- Pod UID: `02df006f-2a6f-4bbc-b35d-4479bcd23bcf`.
- Forgejo container running since September 8, 22:17:52 UTC.
- Snapshot UID: `a3b2a351-044b-4adc-a433-c73c8ced3e79`.
- Snapshot captured September 10, 21:14:06 UTC.
- Archive completed 21:18:40 UTC.
- Controller ran 21:13:21–21:19:18 UTC, including temporary storage cleanup.
- No temporary snapshot PVC, PV or VolumeSnapshot remained after completion.

Archive: `forgejo-20260910T211406Z-ff5dd529.tar`, 9,336,811,520 bytes.
SHA-256: `ebdc4f81d70c1082afdd67770cb960cc4a8e8e7308ae08429c4b9009001be7c9`.
The disposable clone recovered/checkpointed SQLite's WAL before checking its
integrity and creating the uncompressed archive. At 22:18 UTC, Prometheus
reported a minimum of 1 for both pod readiness and Forgejo's HTTP metric
scrapes over the preceding 70 minutes, covering the online rollout. No Forgejo
alerts were firing.

The retained backup volume fell from 86,172,475,392 bytes (80.25 GiB) to
59,861,090,304 bytes (55.75 GiB). It now retains the new archive and the previous
known-good compressed archive. Windows/macOS golden images and GitLab/migration
recovery material were preserved. Rust caches and active runners were untouched.

The six-hour schedule is `13 */6 * * *`, enabled with `Forbid` concurrency.
Forgejo uses `OnDelete` upgrades. Its mounted old bootstrap ConfigMap
`forge-bootstrap-k74hh66dmb` is retained and contains the verified new backup
files. The migration bridge holds the old timer's maintenance lock while its
metrics thread stays running; no container restart was needed. A later planned
replacement starts the metrics-only process and no longer needs this bridge.

The offsite qualification also exposed an existing global-policy mismatch:
Velero used `defaultVolumesToFsBackup: true`, so `backup-volumes: backups`
alone did not exclude the live `data`, `tmp`, or `control` volumes. The September
10 daily backup copied 6,059,804,590 bytes of live data in addition to the
63,372,643,705-byte archive volume. Its incremental uploads were 3,550,773,318
and 16,819,001,278 bytes respectively. Explicit live-volume exclusions now
make both the existing pod and future pod templates select only recovery data.

## Offsite validation

The corrected application backup is `forge-online-proof-20260910215157`.
Its single PodVolumeBackup contains 9,339,519,979 bytes: the completed archive,
manifest and Atollion migration evidence. The staged source pod references
only its disposable volume, so PVC discovery cannot pull in the live Forgejo
pod. This proof explicitly opts into that volume and excludes its temporary
unpacked verification directory using `.kopiaignore`.

The isolated restore `forge-online-proof-20260910215157-verified` was successfully
qualified in `forge-restore`. The verification checks archive SHA-256,
SQLite integrity, the active ZITADEL source, repository metadata, successful
Actions history, artifact bytes, Git integrity and Atollion migration refs.
This application-only proof does not requalify the unchanged native images.

The volume transfer completed 22:29:41 UTC after 18m 01s. Both the database and Git verifiers passed on the downloaded data. This verifies the new snapshot archive through Backblaze, rather than just its local staging copy.

At 22:34:44 UTC, the temporary source and restore pods, PVCs, PVs and ConfigMaps had been removed. The superseded broad diagnostic backup was also removed through Velero. The qualified narrow backup remains retained for 30 days. The production Forgejo pod and all its container identities remained unchanged. Sanitized detailed evidence is retained privately at `~/.local/state/forge-online-backup-20260910/`.

A read-only B2 object-version listing at 22:17 UTC measured 96,363,680,930
current bytes and 82,784,767 noncurrent bytes under
`services/kubernetes/kopia/forge/`. These bucket bytes include the old retained
recovery points and the transition proof; the local 80.25 → 55.75 GiB reduction
is not a claim that B2 has already shrunk. The superseded broad diagnostic
backup `forge-online-proof-20260910213239` is removed through a Velero
DeleteBackupRequest, never by manually deleting shared Kopia objects.

Offsite retention remains 30 days for daily backups and 90 days for weekly
backups. Kopia can deduplicate stable chunks in the new tar archives. Existing
compressed chunks remain referenced until their older backups expire and
repository maintenance reclaims them; local pruning does not immediately shrink
the Backblaze bucket. Hidden B2 object versions also have their own 30-day
lifecycle. Golden images remain a substantial fixed recovery source.

Full `nix flake check --accept-flake-config --no-write-lock-file -L` passed,
including 126 Forge tests and the Promtool cases. All published fixes use signed
conventional commits. The six unrelated modified files in the shared infra
checkout were verified unchanged by SHA-256 before and after its fast-forward.

## Scheduled follow-up — 2026-09-11

The first automatic six-hour backup ran at 00:13 UTC and succeeded at
00:17:16 UTC: 4m 16s including cleanup. Its snapshot was captured at 00:13:04
and the archive completed at 00:16:34. The new archive is
`forgejo-20260911T001304Z-2103dea8.tar`, SHA-256
`7822447187de4699518f07b7c9c52ec99059ba8565135e2ed4f535cd6e81dfd4`.
SQLite integrity passed on the clone. Local retention now contains the two
completed online archives; the final legacy gzip application archive was
pruned by the normal successful-export policy. Retained native images and
migration recovery sources were preserved.

At 00:59 UTC, local backup usage was 61,140,389,888 bytes (56.94 GiB), including
application data added since the first export. Forgejo's pod and all container
identities remained unchanged, with no maintenance request or pause marker.
The Actions queue was empty, all three latest workflows had passed, and no
Forgejo alerts were firing. Both relevant Flux reconciliations were healthy
at `c1cf1991ec40b0024c723a52acfb3d0a415160ae`.

A subsequent B2 listing measured 96,428,167,238 current bytes and 83,551,783
noncurrent bytes. This remains retained historical data, not a measured
reduction in bucket usage. The new automatic archive had not yet reached the
next scheduled offsite backup, so it is not a second offsite-restore proof.
The earlier completed Backblaze restore remains the qualification for the
online archive format.
