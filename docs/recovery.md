# Disaster recovery

What must survive, and the order to bring things back. Component procedures
are linked rather than repeated.

## Material that must exist outside this machine

- The personal age key (`~/.config/sops/age/keys.txt`). It decrypts every SOPS
  file, including the OpenTofu state passphrase, the cluster host and Flux age
  identities, and the Backblaze restore credentials. Without it nothing below
  works. See [secrets](../secrets/README.md).
- The Git repository (GitHub, plus any clone). It holds all configuration, all
  ciphertext and the encrypted OpenTofu state.
- Backblaze bucket `fahrican-cloud-recovery`: CloudNativePG archives, Velero
  backups, per-host Restic repositories (etcd and host identities) and the mail
  host's backups. Never re-initialise a repository or reuse a Barman server
  name over existing data.

## Order

1. **Network.** The router and switches keep their configuration; if not, use
   the rescue paths in [network](network.md), then re-run the playbook and the
   Omada reconciler.
2. **Hosts.** Reinstall one host at a time from the flake with its age identity
   and SSH host key ([servers](../components/nix/servers/README.md)). A
   reinstalled host rejoins etcd and Ceph; keep quorum.
3. **Whole cluster** (only if etcd and Ceph are both lost): below.
4. **Data.** Restore each held stage's data, then resume it:
   PostgreSQL recovers from Barman, volumes from Velero
   ([backups](../deployments/homelab/cluster/infrastructure/backups/README.md)).
   App runbooks list their own invariants (Matrix bot device, Thread network,
   UniFi controller identity).
5. **Providers.** OpenTofu state is in Git; `nix run .#tofu -- ROOT plan` must
   show no changes before anything is applied
   ([providers](../components/homelab/providers/README.md)).

## Rebuilding the cluster

Once all three hosts run, copy the admin kubeconfig from the first server and
point it at the API VIP (`cluster.apiVip` in `deployments/homelab/hosts/inventory.json`).
Flux cannot start without a CNI, so install Cilium first with exactly the
chart and values of its HelmRelease:

```sh
cd deployments/homelab/cluster/infrastructure/cilium
kubectl apply -f vendor/
digest="$(yq 'select(.kind == "OCIRepository").spec.ref.digest' release.yaml)"
helm upgrade --install cilium "oci://quay.io/cilium/charts/cilium@$digest" \
  --namespace kube-system --values values.yaml --wait --timeout 20m
kubectl wait nodes --all --for=condition=Ready --timeout=20m
```

Install Flux, deliver `cluster.flux_age_identity` from `secrets/kubernetes.yaml`
as the `flux-system/sops-age` Secret through stdin, and bootstrap the recovery
overlay instead of the normal root:

```sh
kubectl apply -f deployments/homelab/cluster/bootstrap/flux/gotk-components.yaml
kubectl -n flux-system wait deployment/source-controller --for=condition=Available --timeout=10m
kubectl apply -k deployments/homelab/recovery
```

The overlay creates Ceph, observability and stateful app stages suspended.
Release them in dependency order with `flux resume kustomization NAME` after
their data is restored and checked; Flux does not re-suspend a resumed stage.
When everything runs, `kubectl apply -k deployments/homelab/cluster` returns
the root to the normal path.

A rebuilt CloudNativePG cluster must recover from its archive and then archive
under a new server name; each database manifest explains how.
