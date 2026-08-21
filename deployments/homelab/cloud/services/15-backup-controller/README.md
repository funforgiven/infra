# Backup controller activation

The existing retained Backblaze B2 bucket is shared with undercloud recovery,
with `services/kubernetes/` as this controller's isolated prefix. The services
bootstrap reconciler reads the Git-managed non-secret destination ConfigMap and
renders the official AWS credentials file from SOPS ciphertext on a
memory-backed volume.

Resume the controller wave only after the services cluster is Ready. Confirm the
BackupStorageLocation is Available, resume the policy wave, run an on-demand
backup, and complete the isolated restore qualification before any stateful
application wave is resumed.

Filesystem backup is selected so recovery does not depend on the source Cinder
control plane or its snapshots. Object lock, lifecycle retention, and a second
administrative credential remain at Backblaze.

The AWS object-store plugin is temporarily pinned by immutable amd64 digest to
the official upstream `main` image built on 2026-08-14. It contains upstream
commit `8dbd6b8`, which omits the empty `x-amz-tagging` header that Backblaze B2
rejects. Replace this pin with the first compatible tagged release containing
that commit. Backblaze's documented compatibility setting also disables SDK
request checksums; transport integrity and Kopia repository integrity checks
remain enabled.
