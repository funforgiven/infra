# NetBird service access

NetBird gives enrolled personal devices HTTPS access to a fixed set of private
services. It is **not** the infrastructure recovery path: MikroTik's native
WireGuard profile, direct management addresses, router keys and the AWS mail
tunnel stay outside NetBird and must keep working without Kubernetes, ZITADEL
or NetBird. An outage only interrupts new VPN logins and service-panel access.

## Ownership

- Flux: the combined server (singleton, `Recreate`; the community control plane
  is not made HA by adding replicas), STUN DaemonSet, private service gateway
  and routes.
- CloudNativePG: PostgreSQL with Barman Cloud WAL and daily base backups.
- NetBird OpenTofu (`components/homelab/providers/netbird`): account settings,
  the disabled default policy, the identity provider, groups, private DNS zones
  and the HTTPS policy. It owns the `private-services` group's identity; the
  NetBird Kubernetes operator owns its membership and the routing peers.
- Identity OpenTofu: the ZITADEL project and OIDC client. Only users granted the
  project's `netbird-services` role can enroll.

## Access boundaries

`netbird.fahrican.com` publishes only OAuth, management/signal gRPC, relay and
instance status; no dashboard. The REST API (`netbird-api.fahrican.com`) is
private to the administrator workstation and native WireGuard.

The service gateway has only a ClusterIP and accepts HTTPS solely from the
labelled routing pods. The only policy lets enrolled devices initiate TCP 443
to that gateway: no lateral peer traffic, management VLANs or exit routing.
The built-in all-to-all policy must stay disabled; OpenTofu imports it so a
dashboard edit cannot re-enable full mesh.

`components/homelab/providers/netbird/service-hosts.json` is the one list of
exposed hosts: OpenTofu creates their NetBird DNS zones and
`render_routes.py` copies their LAN HTTPRoutes and SecurityPolicies onto the
NetBird gateway as `access/routes.generated.yaml`. Gateway API cannot attach
one route to both gateways with different admission rules, so the copy is
generated rather than shared. The renderer replaces only LAN source-address
checks (the NetBird gateway admission replaces them) and fails closed on any
other authorization condition. Regenerate after changing a source route:

```sh
python components/homelab/services/netbird/render_routes.py
```

A unit test fails while the generated file is stale.

Routing pods need IPv4 forwarding in their own network namespace; a short
privileged init container sets those namespaced sysctls without host access.
Operator 0.8.0 uses a DNS zone's name as its record suffix, so the zone name
must equal its domain.

## Credentials

Automation PATs for OpenTofu and the operator expire after 365 days
(`credentials-monitoring.yaml` alerts 30 days ahead). Run
`nix run .#netbird-admin -- rotate-credentials`, commit the SOPS files and the
operator rollout annotation, verify reconciliation, then revoke the old tokens.
It needs `secrets/netbird-bootstrap.yaml`, which holds the bootstrap owner and
the service users' current tokens.

## Recovery

The database recovers from Barman Cloud: a recreated `netbird-postgres`
bootstraps from the archive automatically. A rebuilt cluster cannot archive
into a non-empty folder, so bump the archiver `serverName` and point the
`backup` external cluster at the previous one. Recovery also needs the
SOPS-encrypted `server/runtime.sops.yaml` (database password, store
encryption key, cookie key, relay secret) and `server/backup.sops.yaml`.

The weekly `postgres-restore-test` CronJob in the isolated `netbird-restore`
namespace (shared `components/homelab/cnpg-restore-test`, assertions in
`server/restore-test/check.sql`) recovers the archive into a disposable cluster
with no WAL archiver, runs the checks, then deletes it. Never point a test
cluster's archiver at the production prefix.

A start from an empty database (no archive) means a new NetBird deployment:
every device re-enrolls. Its one-off setup tooling is in Git history.

## Relay health probe

NetBird 0.80.0's combined server answers `/health` with HTTP 503 and
`listeners:null`, because the relay shares the HTTP server. The
`netbird_relay` Blackbox module therefore requires `certificate_valid:true` and
accepts that known empty listener registration; any other failure still fails.
Recheck this on upgrade
([healthcheck.go](https://github.com/netbirdio/netbird/blob/v0.80.0/relay/healthcheck/healthcheck.go)).
