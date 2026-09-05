# GitLab recovery

Restore the **same GitLab version and edition** as the archive: currently
GitLab 19.3.1 EE / chart 10.3.1. Restore a completed archive and its matching
`secrets.json` together. Rails encryption keys are essential for decrypting
stored tokens and protected application data. Git alone and a database dump
cannot reconstruct them.

The retained Restic snapshot contains `SHA256SUMS`, the native archive,
`secrets.json`, `backend-config/`, `bootstrap/`, `backend-image.txt`, and
`versions.txt`. Obtain the Restic password and prefix-scoped B2 reader credentials
through the existing encrypted runtime contract. Restore into a new owner-only
directory and verify `sha256sum --check --strict SHA256SUMS` there. Keep encryption
keys and SMTP/OIDC credentials out of command arguments and logs.

For production disaster recovery:

1. Freeze GitLab writes and pause runners. Suspend the application Flux wave and
   the native backup schedule during restoration. Preserve the damaged data
   volume; create fresh recovery volumes rather than overwriting the only copy.
2. Recreate the private OpenStack project/network and cluster from signed Git if
   needed. Restore the independent Flux age/signing secrets. Rebuild the data VM
   using the recorded image and restore its configuration/bootstrap bundle.
3. Restore the recorded Rails, shell, registry and other application encryption
   secrets before starting the chart. Preserve application key names. Reconcile
   current storage, TLS, SMTP and OIDC connection credentials separately if their
   endpoints or credentials have changed.
4. Prepare empty PostgreSQL and Gitaly storage, with matching versions, and empty
   private object buckets. Install the same chart with webservice and Sidekiq
   scaled to zero, autoscaling disabled, and the backup schedule suspended. The
   toolbox, database, Redis, Gitaly and object store must be available.
5. Upload the native archive to the recovery backup bucket. Run the official
   toolbox `backup-utility --restore -t BACKUP_ID` against that bucket. The ID is
   the archive name before `_gitlab_backup.tar`. Do not use the old Omnibus-only
   restore procedure for this Helm installation.
6. Run Rails secret, repository, LFS, artifact, upload and registry checks. Resume
   the application and confirm private TLS, ZITADEL login, repository clones and
   pushes, an LFS download, a registry image pull and a canary pipeline. Re-enable
   backups and prove a new off-site Restic snapshot before resuming normal work.

For a restore exercise, prepare a separate `gitlab-recovery` namespace in a
recovery cluster. Give it the label `infra.fahrican.com/purpose=gitlab-recovery`.
All recovery databases, repository storage and S3 services must be within that
namespace, using fresh disks and buckets. Set the application hostname to
`gitlab-restore.invalid`, disable SMTP, OIDC, autoscaling, external integrations
and scheduled backups, and use the recorded Rails encryption secrets with fresh
connection credentials. Never import production S3 connection secrets into the
recovery configuration.

Install namespace-wide default-deny network policies. Allow peers only within the
recovery namespace and CoreDNS on TCP/UDP 53. No external IP blocks, other
namespaces, host networking, privileged containers or host volumes are permitted.
Preload images through the container runtime before the exercise if necessary.
Upload the archive to that isolated S3 service, then run:

```sh
components/cloud/services/gitlab/qualify-restore.sh \
  RECOVERY_CONTEXT BACKUP_ID EXISTING_PRIVATE_REPORT_DIRECTORY
```

The helper checks the namespace and network boundary before invoking the native
restore and integrity checks. Keep GitLab's Flux release reconciliation suspended
throughout the exercise so it cannot change replica counts or connection secrets.
Review the output and additionally verify repository clones and registry pulls.
Only then copy `restore.prom` into the production node exporter's textfile
collector. A checksum verification or a rendered manifest is not a restore test.

The initial deployment is not HA. The practical RPO is up to one day after the
scheduled native/off-site jobs are proven; recovery time must be measured during
the first complete restore exercise. No restore exercise has been certified by
merely adding these files.

Upgrades must follow GitLab's required upgrade stops. Take and verify a fresh
archive/secret pair first, preserve the previous backend image and chart revision,
then update the backend package and chart together according to GitLab's upgrade
instructions. A failed database migration does not make an automatic Helm rollback
safe; recovery can require the pre-upgrade database and repository backup.
