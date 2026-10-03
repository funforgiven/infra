# NetBird service access

NetBird provides authenticated access to explicitly selected HTTPS services.
MikroTik's native `wg-admin` remains the independent infrastructure recovery
path. Router keys, administrator peers, management routes and the existing
AWS mail backend tunnel are not migrated into NetBird.

## Components and ownership

| Component | Owner | State |
| --- | --- | --- |
| ZITADEL project, service-user grant and OIDC client | Identity OpenTofu | Existing ZITADEL PostgreSQL |
| NetBird combined server 0.80.0 | Flux | PostgreSQL; cryptographic keys in SOPS |
| PostgreSQL 18, three instances | CloudNativePG | Three Cinder volumes, synchronous replica |
| PostgreSQL recovery | Barman Cloud plugin | Continuous WAL and daily base backups in B2 |
| Account settings, disabled default policy, IdP, groups, DNS and HTTPS policy | NetBird OpenTofu | NetBird PostgreSQL |
| Network and routing peers | NetBird Kubernetes operator 0.8.0 | Reconciled Kubernetes resources and NetBird API |
| Private service gateway and application routes | Flux | Kubernetes configuration |

The server is intentionally a singleton with `Recreate` updates. The community
control plane is not made highly available by adding replicas. PostgreSQL has
three instances with one required synchronous standby. Controller replacement
does not discard enrolled devices, IdP signing keys, groups or policies.

The operator owns membership of the `private-services` resource group; OpenTofu
owns its identity. Neither controller also owns the other's network resources.
The operator's experimental Gateway API integration and automatic policy
creation are disabled.

## Access boundaries

`netbird.fahrican.com` exposes only OAuth, management/signaling gRPC, relay,
WebSocket proxying and the read-only instance-status endpoint. It has no server
dashboard. The authenticated REST API uses `netbird-api.fahrican.com`, resolved
to the existing private gateway and limited to the administrator workstation,
native WireGuard network and undercloud controller hosts. Initial setup is
performed through an authenticated Kubernetes port-forward.

The ZITADEL project denies unassigned users. Initially only the existing owner
identity receives its `netbird-services` role. A device authenticating as that
user may initiate TCP 443 to the private gateway. There are no grants for peer
input, lateral client traffic, management VLANs, arbitrary cluster addresses or
internet exit routing. The built-in all-to-all policy is disabled before the
external identity provider or routing peers are enabled and is then managed by
OpenTofu.

The gateway has a ClusterIP at `172.24.0.80`, with no LoadBalancer or NodePort.
Its ingress NetworkPolicy accepts HTTPS only from the labeled NetBird routing
pods in `netbird-routing`. Application login remains required. The source LAN
gateway's IP restrictions are unchanged.

`render_routes.py` derives the selected application routes, preserving request
rules, header filtering, authentication backends and unconditional path denials.
It substitutes the NetBird gateway's admission boundary for existing LAN IP
checks, and fails closed when a new authorization condition needs review. Run:

```sh
python components/cloud/services/netbird/render_routes.py
python components/cloud/services/netbird/render_network.py
python -m unittest discover -s components/cloud/services/netbird/tests -v
```

Magnum installs a global Calico egress Allow at order 20. The generated Calico
policies enforce the same NetBird egress allowlists at order 15 and end in Deny.
The ingress NetworkPolicies remain enforced normally. Regenerate the Calico
files whenever their Kubernetes NetworkPolicy sources change.

NetBird uses individual DNS zones for the selected service hostnames. Public
mail/JMAP, SMTP, the rest of `fahrican.com`, and normal LAN DNS are unaffected.
At home, ordinary LAN access works with NetBird disconnected. An active NetBird
client uses the local routing peers when connectivity permits; no dependency
on cached tunnels is assumed during an outage.

## Enrollment

Run commands from the repository root with the personal age identity available.
The `matrix-access` helper is the existing general homelab access wrapper; its
kubeconfig and OpenStack credentials live only in memory.

1. Run `nix run .#netbird-admin -- prepare`. This creates SOPS-encrypted runtime
   keys and a local bootstrap credential, preserving existing keys on rerun.
2. Through the services access wrapper, run `netbird-admin backup-credentials`.
   It reuses the existing service-cluster B2 writer only inside its existing
   `services/kubernetes/` prefix. NetBird uses the separate `netbird/postgresql/`
   child prefix; it does not use AWS mail credentials.
3. Reconcile the identity application, controllers, database and server. Verify
   PostgreSQL and the first Barman backup before enrolling devices.
4. Through undercloud access, run `netbird-admin identity-credentials` to save
   the two new ZITADEL outputs to the encrypted policy input.
5. Use `kubectl -n netbird port-forward service/netbird-server 18080:8080` from
   the services access wrapper. Run `netbird-admin bootstrap` locally. It closes
   the default mesh policy and saves distinct automation tokens as ciphertext.
6. Add the encrypted credential files to their Kustomizations and enable the
   policy wave. After its plan converges, enable the operator and access waves.
7. Verify client enrollment, permitted HTTPS, denied lateral/management access,
   private API denial from outside, and router recovery access. Run
   `netbird-admin close-bootstrap` after ZITADEL login is verified, then commit
   and reconcile the closed bootstrap configuration.

Automation PATs expire after 365 days. Before expiry, run
`nix run .#netbird-admin -- rotate-credentials`, commit the resulting SOPS files
and operator rollout annotation, and verify reconciliation before revoking the
old tokens. Device keys and addresses are managed by NetBird; they do not
require individual RouterOS peer edits.

## Recovery

Keep the native MikroTik WireGuard configuration and direct management addresses
on the administrator device. Infrastructure SSH and PiKVM must remain usable
without Kubernetes DNS, ZITADEL, NetBird or a private application gateway.
The router and home internet must still be reachable for remote recovery.

NetBird database recovery uses the Barman archive at
`s3://fahrican-cloud-recovery/services/kubernetes/netbird/postgresql/` with the
SOPS-encrypted database password, store encryption key, cookie key and relay
secret from this repository. Restore to an isolated CloudNativePG cluster
first, using a different destination prefix for its own WAL archive. Inspect
accounts, groups and the disabled default policy before switching the server
to that database. Never point a restore qualification cluster's WAL writer at
the production archive.

Public SMTP and JMAP terminate in AWS and do not depend on this control plane.
An outage can interrupt new VPN logins, reconnections and service-panel access.
The native MikroTik tunnel is the supported recovery route.
