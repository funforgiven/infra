# Private Forgejo and Actions

## Forgejo

- Humans sign in through ZITADEL only; `forge-admin` (password in
  `runtime.sops.yaml`) is the local recovery administrator. Admin routes stay
  confined to LAN/WireGuard; CI is denied them.
- Forgejo 15.0.7 formats boolean required claims with Go's `%s`, so the
  bootstrap matches `email_verified` against `%!s(bool=true)`. False or missing
  claims are still rejected. Recheck on every Forgejo upgrade: a mismatch shows
  up as account suspension before account creation.
- `forgejo.ini` reads secrets through `*_URI = file:` keys. `[metrics] TOKEN` has
  no URI form, so the bootstrap container renders `app.ini` with Forgejo's
  `environment-to-ini`. The instance signing key in `signing.sops.yaml` is
  mounted directly. Keep it stable: Forgejo cannot rotate it without breaking
  the verification of earlier merges.
- The StatefulSet uses `OnDelete`, so applying manifests never restarts agents'
  Git/API sessions or running CI. Roll the pod for image or config changes in a
  maintenance window.

## Actions runners

- Trust model: only the init container of a runner Job sees the
  repository-scoped enrollment PAT. It registers a one-job ephemeral runner and
  hands it over through a memory volume. Job code never gets the PAT, a
  Kubernetes token, a Docker socket or private network access. The launcher in
  `forge-control` holds the Job-creating token and the cache broker credential.
  It runs no repository code.
- The build cache gateway exists because the upstream cache server shares
  entries across repositories and refs. The launcher gets a short-lived,
  job-scoped capability from trusted queue metadata. Pull requests can read
  their own caches and the protected-main baseline, but can write neither the
  baseline nor another PR's caches. The cache is disposable and not backed up.
- Images are built by Nix (`forge-linux-runner-image`, `forge-cache-image`) and
  published with `components/homelab/services/forge/publish-image.py result`.
  Pin the printed digest in the manifests.
- `components/homelab/services/forge/qualification.yaml` is the workflow
  committed to `forge-runner/runner-qualification`.
- Drain one node at a time after checking etcd/Ceph quorum and capacity. Let
  builds finish or cancel them, then suspend both launcher CronJobs. Never
  delete data or cache PVCs to unblock a drain. Resume and check a cached build.

## Credentials (manual, from the dev shell)

- `enroll.py` creates Forgejo's local secrets. The OIDC client comes from
  `nix run .#tofu -- identity output -json | nix run .#identity-credentials`.
- `enroll-runners.py` creates the `forge-runner` account, the qualification
  repository and the scoped runner/registry tokens.
- `enroll-agent-sessions.py` renews the Atollion agents' web sessions.

Plaintext stays in pipes; only SOPS ciphertext is written.

## Backup and recovery

`forgejo-data` (SQLite and Git) is in the daily volume snapshots and the
monthly drill runs `git fsck` and an SQLite check on it; see
[backups](../../infrastructure/backups/README.md). To recover, suspend the
`forge` Flux Kustomization, restore the claim, resume Flux and accept only after
HTTP, SSH, OIDC and an Actions run work.
