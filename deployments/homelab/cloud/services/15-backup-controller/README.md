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
