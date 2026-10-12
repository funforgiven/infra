# Wallos

Wallos runs as a single-replica StatefulSet at
<https://wallos.fahrican.com>. The route is restricted to the LAN and
administration WireGuard network. Normal sign-in uses ZITADEL; Wallos
requires a verified email claim and links only pre-created local accounts.
The intended owner completes the one-time local registration described below
before federated sign-in begins.

## First login

Wallos does not offer OIDC until its first local user exists. Treat deployment
and first registration as one controlled bootstrap: while the database has no
users, the first registrant becomes user ID 1 and the application administrator.
The exact registration route is therefore restricted to the trusted
administration workstation at `10.21.10.20/32` and the administration
WireGuard network. From either source, open <https://wallos.fahrican.com>
immediately after the workload becomes ready and register the intended owner
using the same verified email as that owner's ZITADEL account and a unique,
high-entropy password kept in the password manager. On the resulting login
page, choose ZITADEL; the matching verified email binds the OIDC identity to
the owner. Verify the linked email and admin access before entering any
financial data.

The OIDC client is reconciled by the identity OpenTofu root. Its client ID and
secret move directly from the undercloud output Secret to the services
cluster's `wallos-runtime` Secret; neither value is committed to Git.
The undercloud reconciler runs at minute 17 every two hours UTC; trigger an
on-demand Job from `services-cluster-reconcile-v1` when an initial rollout
cannot wait for that cadence. A rotated secret file is read on requests, but a
recreated client ID is an environment value and requires a Wallos rollout after
the runtime Secret is refreshed.

Wallos performs a local logout because its OIDC implementation does not send
the client or ID-token hint ZITADEL requires for a reliable federated logout;
ending the ZITADEL browser session remains a separate operation.

Automatic OIDC user creation is disabled. For another authorized user, the
Wallos administrator must first create a local account with that person's
verified ZITADEL email and a unique, high-entropy local password; their first
OIDC login then links the account.

`OIDC_DISABLE_PASSWORD_LOGIN` hides the password form and registration link,
but Wallos 5.4.5 still accepts a valid password submitted directly to
`login.php`. The gateway confines that POST to the trusted administration
workstation and administration WireGuard network. Treat the retained bootstrap
password as a live recovery credential. If ZITADEL is unavailable or the
client configuration is broken, connect from either trusted source,
temporarily set the option to `"false"` in `wallos.yaml` to reveal the form,
reconcile, and use that password; restore the UI restriction after recovery.

## Storage and backup

The `wallos-database` and `wallos-logos` PVCs use Cinder `rbd1` storage. The
claims opt out of Flux pruning so a manifest rename or temporary service
removal cannot delete the financial data while the `finance` namespace remains;
deleting the namespace still deletes its claims. After verifying the expected
schema, the backup sidecar creates an atomic SQLite native backup every six
hours. The Velero pre-backup hook creates and integrity-checks another native
backup immediately before Kopia copies both PVCs off-cluster.

For an isolated restore, create a disposable `finance-restore` namespace with
a deny-all NetworkPolicy. Restore the `finance` namespace without routes,
SecurityPolicies, Services, Pods, StatefulSets, NetworkPolicies, or Secrets,
and use `finance-restore-modifiers` so Cinder provisions isolated volumes.

```console
kubectl create namespace finance-restore
kubectl label namespace finance-restore \
  pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/enforce-version=v1.35 --overwrite
kubectl -n finance-restore apply -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
EOF
velero restore create <restore-name> \
  --from-backup <backup-name> \
  --include-namespaces finance \
  --include-cluster-resources=false \
  --namespace-mappings finance:finance-restore \
  --exclude-resources httproutes.gateway.networking.k8s.io,securitypolicies.gateway.envoyproxy.io,services,pods,statefulsets.apps,networkpolicies.networking.k8s.io,secrets \
  --resource-modifier-configmap finance-restore-modifiers \
  --wait
```

Mount `wallos-database`, then verify `backups/wallos.db` with:

```console
sqlite3 /restore/db/backups/wallos.db 'PRAGMA integrity_check;'
```

Require exactly `ok`. Inspect the uploaded-logo tree separately. For a live
recovery, first make and reconcile a signed maintenance commit that sets the
Wallos StatefulSet's declared replicas to zero, then verify that `wallos-0` is
gone. Preserve the failed database, copy the verified native backup to
`wallos.db`, restore the logos PVC if needed, and check database ownership and
integrity again. Restore the declared replica only in a second signed commit
after those checks succeed, then wait for the StatefulSet to become ready. Do
not rely on an imperative scale or child-Kustomization suspension: the parent
GitOps reconciliation can overwrite either during recovery.

## Container security boundary

The upstream Wallos image starts nginx, PHP-FPM, and dcron from one root
supervisor and changes file ownership on every start. The `finance` namespace
therefore enforces the Pod Security `baseline` profile while auditing and
warning against `restricted`. The container cannot escalate privileges, uses
the runtime-default seccomp profile, receives no service-account token, and
keeps only the six capabilities its upstream startup requires. Network policy
allows ingress solely from the services Gateway and limits egress to cluster
DNS, the private ZITADEL endpoint, public HTTPS, and submission-SMTP ports.
The legacy Fixer provider sends its API key over cleartext HTTP and is therefore
blocked; use Wallos's HTTPS APILayer currency provider.

The catch-all application route and HTTP redirect are limited to LAN/WireGuard
clients. A higher-precedence `/db` route denies every request because upstream
nginx does not protect all SQLite journal and in-progress backup filenames.
More-specific routes confine registration and password POSTs to the trusted
administration workstation and administration WireGuard network. A separate
exact HTTPS route exposes only `/health.php` to the in-cluster blackbox monitor;
the endpoint returns the fixed text `OK` and the services Gateway address is
not Internet-routable. HTTPS responses set a host-only HSTS policy; Wallos
5.4.5 does not set `Secure` on its session and remember-me cookies, so the first
visit must be HTTPS and the application must remain confined to these trusted
networks.
