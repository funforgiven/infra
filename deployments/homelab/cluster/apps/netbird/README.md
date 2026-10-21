# NetBird service access

NetBird provides authenticated access to selected HTTPS services.
MikroTik's native `wg-admin` is the infrastructure recovery path. Router keys,
administrator peers, management routes and the AWS mail backend tunnel stay
outside NetBird.

## Components and ownership

| Component | Owner | State |
| --- | --- | --- |
| ZITADEL project, service-user grant and OIDC client | Identity OpenTofu | ZITADEL PostgreSQL |
| NetBird combined server 0.80.0 | Flux | PostgreSQL; cryptographic keys in SOPS |
| Coturn 4.18.0 STUN workers | Flux DaemonSet | None; STUN only, TURN disabled |
| PostgreSQL 18, three instances | CloudNativePG | Three `ceph-block` volumes, synchronous replica |
| PostgreSQL recovery | Barman Cloud plugin | Continuous WAL and daily base backups in B2 |
| Account settings, disabled default policy, IdP, groups, DNS and HTTPS policy | NetBird OpenTofu | NetBird PostgreSQL |
| Network and routing peers | NetBird Kubernetes operator 0.8.0 | Reconciled Kubernetes resources and NetBird API |
| Private service gateway and application routes | Flux | Kubernetes configuration |

The server is a singleton with `Recreate` updates. The community
control plane is not made highly available by adding replicas. PostgreSQL has
three instances with one required synchronous standby. Controller replacement
does not discard enrolled devices, IdP signing keys, groups or policies.

Each PostgreSQL instance has a 16 GiB volume and a 2 GiB replication-slot WAL
budget, so an offline replica cannot retain an unlimited local backlog.

The operator owns membership of the `private-services` resource group; OpenTofu
owns its identity. Neither controller also owns the other's network resources.
The operator's experimental Gateway API integration and automatic policy
creation are disabled.

STUN runs on every node with MetalLB local endpoints, keeping client source
addresses, separately from the singleton controller. `netbird-stun.fahrican.com`
uses UDP 3478. Routing pods resolve the coordination and STUN names to their
separate local gateway addresses; their connections stay within the homelab.
The operator's DNS zone name must equal its domain because version 0.8.0 uses
the name as the generated record suffix. The 0.80.0 client must also be allowed
to set its initial configuration before enrollment.

Routing peers enable IPv4 forwarding and loose reverse-path filtering in their
own pod network namespaces. A short privileged init container sets these
namespaced sysctls without host mounts or host namespaces. The running NetBird
containers are unprivileged, with a read-only root filesystem and limited
network capabilities. Readiness also checks that forwarding remains enabled.
Replicas of the same revision require different nodes; a new revision may
overlap the old one during rolling updates.

## Access boundaries

`netbird.fahrican.com` exposes only OAuth, management/signaling gRPC, relay,
WebSocket proxying and the read-only instance-status endpoint. It has no server
dashboard. The authenticated REST API uses `netbird-api.fahrican.com`, resolved
to the private gateway and limited to the administrator workstation and
native WireGuard network. Initial setup is
performed through an authenticated Kubernetes port-forward.

The ZITADEL project denies unassigned users. The owner's everyday `funforgiven`
account and the emergency account receive its `netbird-services` role. A device
authenticating as either user may initiate TCP 443 to the private gateway. There are no grants for peer
input, lateral client traffic, management VLANs, arbitrary cluster addresses or
internet exit routing. The built-in all-to-all policy is disabled before the
external identity provider or routing peers are enabled and is then managed by
OpenTofu.

The gateway has a ClusterIP at `172.24.0.80`, with no LoadBalancer or NodePort.
Its ingress NetworkPolicy accepts HTTPS only from the labeled NetBird routing
pods in `netbird-routing`. Application login is still required. The LAN
gateway's IP restrictions are unchanged.

`render_routes.py` derives the selected application routes, preserving request
rules, header filtering, authentication backends and unconditional path denials.
It substitutes the NetBird gateway's admission boundary for LAN IP
checks, and fails closed when a new authorization condition needs review. Run:

```sh
python components/homelab/services/netbird/render_routes.py
python -m unittest discover -s components/homelab/services/netbird/tests -v
```

Cilium enforces the standard Kubernetes ingress/egress allowlists and default
deny. Backend gateway selectors keep in-cluster HTTPS working after service
translation.

NetBird uses individual DNS zones for the selected service hostnames. Public
mail/JMAP, SMTP, the rest of `fahrican.com`, and normal LAN DNS are unaffected.
At home, ordinary LAN access works with NetBird disconnected. An active NetBird
client uses the local routing peers when connectivity permits; no dependency
on cached tunnels is assumed during an outage.

## Enrollment

Run commands from the repository root with the personal age identity available.
`nix run .#matrix-access -- cluster -- COMMAND` runs a command with the cluster
kubeconfig; its kubeconfig lives only in memory.

1. Run `nix run .#netbird-admin -- prepare`. This creates SOPS-encrypted runtime
   keys and a local bootstrap credential, keeping existing keys on rerun.
2. Run `nix run .#matrix-access -- cluster -- nix run .#netbird-admin -- backup-credentials`.
   It uses the cluster B2 writer only inside its `services/kubernetes/` prefix.
   NetBird uses the auxiliary `plugins/netbird/postgresql/` child prefix accepted
   by Velero's storage layout; an arbitrary top-level child makes Velero reject
   the entire backup location. It does not use AWS mail credentials.
3. Reconcile the identity provider, controllers, database and server. Verify
   PostgreSQL and the first Barman backup before enrolling devices. Write the
   NetBird OIDC client into `deployments/homelab/credentials/netbird-policy/identity.sops.yaml`
   with `render-cluster-credentials --identity-outputs-stdin` (see the
   [credentials README](../../../credentials/README.md)).
4. Run `nix run .#matrix-access -- cluster -- kubectl -n netbird port-forward service/netbird-server 18080:8080`.
   In another terminal, run `nix run .#netbird-admin -- bootstrap`. It binds the
   bootstrap account to `netbird.selfhosted` before enabling SSO, closes the
   default mesh policy and saves distinct automation tokens as ciphertext in
   `netbird-policy/credentials.sops.yaml` and `operator/token.sops.yaml`.
5. Apply the NetBird OpenTofu policy, then reconcile the operator and access
   Kustomizations.
6. Verify client enrollment, permitted HTTPS, denied lateral/management access,
   private API denial from outside, and router recovery access. Run
   `netbird-admin close-bootstrap` after ZITADEL login is verified, then commit
   and reconcile the closed bootstrap configuration.

Bootstrap binds `netbird.selfhosted` before enabling SSO and refuses multiple
accounts; an account split cannot be fixed by changing peer expiry.

Automation PATs expire after 365 days. Before expiry, run
`nix run .#netbird-admin -- rotate-credentials`, commit the resulting SOPS files
and operator rollout annotation, and verify reconciliation before revoking the
old tokens. Device keys and addresses are managed by NetBird; they do not
require individual RouterOS peer edits.

Personal SSO peers have no periodic login or inactivity expiry. A signed-in
device stays enrolled until removed or its access is revoked.

## Connecting a personal device

In the NetBird Linux or Android app, select the self-hosted management server
`https://netbird.fahrican.com`, then sign in with the ZITADEL owner
identity. On Linux the equivalent CLI command is:

```sh
netbird up --management-url https://netbird.fahrican.com
```

Use the normal service URLs: `https://mail-admin.fahrican.com`,
`https://home.fahrican.com`, `https://music.fahrican.com`, and the other selected
hosts above. NetBird supplies the private DNS and routes. Keep the native
MikroTik WireGuard profile separately for infrastructure recovery.

## Recovery

### Infrastructure access

Keep the native MikroTik WireGuard configuration and direct management addresses
on the administrator device. Infrastructure SSH and PiKVM must remain usable
without Kubernetes DNS, ZITADEL, NetBird or a private application gateway.
The router and home internet must still be reachable for remote recovery.
Keep the MikroTik recovery interface and administrator peer enabled; disconnect
the client tunnel when it is not needed. Disabling the router-side peer would
require another working access path to re-enable emergency access. One recovery
profile is sufficient when used on one device at a time. Keep an encrypted copy
available outside the homelab; simultaneous clients should have their
own peers. The administrator peer is labelled `parmigiano`, but the
label alone does not identify the physical device holding its private key.

NetBird database recovery uses the Barman archive at
`s3://fahrican-cloud-recovery/services/kubernetes/plugins/netbird/postgresql/` with the
SOPS-encrypted database password, store encryption key, cookie key and relay
secret from this repository. Restore to an isolated CloudNativePG cluster
first, using a different destination prefix for its own WAL archive. Inspect
accounts, groups and the disabled default policy before switching the server
to that database. Never point a restore-test cluster's WAL writer at
the production archive.

Run the repeatable backup and isolated restore check from the repository root:

```sh
nix run .#matrix-access -- cluster -- nix run .#netbird-admin -- restore-check
```

It creates a fresh base backup, waits for its final WAL segment to be archived,
and restores into a disposable namespace. It compares configuration counts,
identity connector and signing-key state, checks the event schema, and verifies
that the default mesh policy is disabled. It removes its namespace and volume
afterwards. The restored cluster has no WAL writer or application ingress.
Production PostgreSQL switches WAL at least every 60 seconds when active;
successful archival still depends on connectivity to Backblaze.

Public SMTP and JMAP terminate in AWS and do not depend on this control plane.
An outage can interrupt new VPN logins, reconnections and service-panel access.
The native MikroTik tunnel is the supported recovery route.

## Relay health monitoring

The relay probe uses the `netbird_relay` Blackbox Exporter module. In the pinned
NetBird 0.80.0 combined server, `/health` reports HTTP 503 with `listeners:null`
because the relay uses the shared HTTP server instead of standalone listeners.
The same endpoint still checks the public relay WebSocket connection and TLS.
The probe requires `certificate_valid:true` and accepts either a healthy status
or the known empty listener registration. A failed public connection, invalid
certificate, malformed response, other HTTP error or unreachable health endpoint
still fails the probe. Recheck this workaround when upgrading NetBird.

The upstream implementation is in
[`relay/healthcheck/healthcheck.go`](https://github.com/netbirdio/netbird/blob/v0.80.0/relay/healthcheck/healthcheck.go)
and [`relay/healthcheck/ws.go`](https://github.com/netbirdio/netbird/blob/v0.80.0/relay/healthcheck/ws.go).
