# Backup controller activation

OpenTofu owns the retained R2 bucket. The services bootstrap reconciler reads
its non-secret outputs and renders the official AWS credentials file from SOPS
ciphertext on a memory-backed volume. No bucket, account, endpoint, or
credential placeholder is edited into this layer.

Resume the controller wave only after the R2 root is Ready. Confirm the
BackupStorageLocation is Available, resume the policy wave, run an on-demand
backup, and complete the isolated restore qualification before any stateful
application wave is resumed.

Filesystem backup is selected so recovery does not depend on the source Cinder
control plane or its snapshots. Object lock, lifecycle retention, and a second
administrative credential belong at the bucket provider.
