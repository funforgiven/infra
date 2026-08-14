# Backup controller activation

This wave remains suspended until an off-site S3-compatible bucket and a
dedicated write-only workload credential exist. Before activation:

1. Replace the invalid bucket and endpoint sentinels in velero.yaml.
2. Add velero-object-storage.sops.yaml containing only a cloud key in the
   official AWS credentials-file format, encrypted for the services Flux age
   identity and the offline administrator.
3. Add that SOPS document to kustomization.yaml.
4. Remove the HelmRelease suspension, then resume the controller wave.
5. Confirm the BackupStorageLocation is Available.
6. Resume the policy wave, run an on-demand backup, and complete an isolated
   restore qualification before any stateful application wave is resumed.

Filesystem backup is selected so recovery does not depend on the source Cinder
control plane or its snapshots. Object lock, lifecycle retention, and a second
administrative credential belong at the bucket provider.
