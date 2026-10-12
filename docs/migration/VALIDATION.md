# Migration validation evidence

All checks described here operate on the prepared worktree. None apply resources
to a live Kubernetes cluster, provider or physical host.

## Manifest and schema validation

The full offline run passed with 33 Kustomize entrypoints, 29 acyclic Flux
stages and 1,194 validated resources across those entrypoints and twelve pinned
Helm renders. Entry points share resources, so 1,194 is a validation count,
not a count of unique deployed objects. Helm rendered 443 resources. There were
zero failures and zero missing-schema exemptions.

`deployments/homelab/validation/schemas.json.gz` contains official Kubernetes
1.36.4 OpenAPI definitions, the pinned charts' CRDs, Calico 3.33 native v3 CRDs
and the KubeVirt 1.9.0 versioned API Swagger. `sources.json` records immutable
references and hashes. KubeVirt test-fixture CRDs are excluded because they
can silently replace current API definitions with stale/minimal schemas.

To refresh public schemas and a chart cache from repository root, with Python
PyYAML/requests, Helm, Kustomize and SOPS available:

```sh
python components/homelab/validation/refresh.py --cache /tmp/homelab-migration-validation
python components/homelab/validation/validate.py \
  --helm-cache /tmp/homelab-migration-validation --decrypt
```

Only public pinned upstream data is downloaded. SOPS values and rendered Secret
payloads stay in subprocess memory/stdin; the public cache does not contain
decrypted Helm values or rendered manifests. Failure reports include resource,
field and validator, and suppress diagnostics that could interpolate values.

The Nix `homelab-manifests` check uses the committed schema bundle and validates
native/embedded resources, the dependency graph, storage-class references and
the recovery holds without needing secret decryption or network downloads.
Optional null dictionary fields are treated as omitted API fields, while
required missing fields still fail. Kubernetes int-or-string formats accept
both their legal types. Object fields are strict where the schema defines
properties and does not explicitly preserve unknown fields.

The ZITADEL chart references an external Kubernetes values-schema definition.
Refresh pins that source to commit `817113f21a2733311cbc3e992bb44ffe1c416c54`
and SHA-256 `428559f7d50d8624ce29ea144ba079309a025168e8bb7714e954dcb80d50cd9a`.
It creates a derived chart cache with self-contained JSON references, preserving
original chart/dependency archives and recording original/derived schema hashes
in `sources.json`. Full Helm values validation stays enabled, and the latest
full run passes inside the network-restricted sandbox without remote schema
fetches. Tests cover nested/local reference scope, literal `$ref` properties,
unknown sources, checksum mismatch and dependency archive preservation.

The generated migration transfer manifests separately passed strict schema
validation for 106 resources: all captured source claim export Pods, supported
file restore Pods/new direct-CSI claims, and UniFi's filesystem-claim transfer.
Four retained TLS/account Secrets exported and validated offline from the actual
encrypted source archive, including mode 0600 and overwrite refusal. These
checks do not execute transfers or change Pod Security labels. The native
validator also requires the initial recovery Ceph hold before NVMe reuse.

Offline schema checks do not execute admission webhooks/CEL validation, create
CRDs, test CNI/kernel/firmware behavior, bind storage or prove application restore
integrity. The future live runbook requires these separate qualifications.

The Matrix/AudioMuse database-only bootstrap helper passed strict validation
with the actual encrypted runtime inputs: eleven resources across two bundles,
mode 0600 and overwrite refusal. Its dependencies come from the exact Kustomize
result, preserving generated script names and pinned images. No cluster calls
or application writers are included. The expanded credential renderer exercised
all retained client outputs from the actual preserved identity state in a
no-write run. Regression checks preserve signing/session keys and unrelated
providers and reject incomplete outputs before writes.

Vendor checks now verify every local installation asset against `vendors.json`.
The independent snapshot controller/v1 CRDs and enabled RBD snapshot policy are
required by semantic validation; a CSI sidecar alone does not satisfy that check.
Physical CI placement rejects remaining CAPI constraints. These dependency
checks supplement API schemas; actual snapshots/restores and Linux workflows
remain future live qualification.

## Service and provider checks

The retained suites pass: network automation 48, Forgejo/Linux CI 104,
Valheim 7, home automation 14, UniFi 5, independent mail 26, NetBird 10 and
Matrix 25 tests. The offline recovery/validation helpers pass 25 tests. Matrix tests include the real matrix-nio E2E dependency.
Credential enrollment passed all 46 tests again after the current recovery changes.

All four provider configurations passed `tofu init -backend=false -input=false`
and `tofu validate` with their exact locked provider versions. No plan/apply or
backend access occurred. Export of all four preserved states verified nonempty
lineage/version, owner-only file mode and refusal to overwrite an existing file.

## Nix and remaining qualification

The latest evaluations pass for pecorino, taleggio, asiago, parmigiano and
independent aarch64 mail-aws, including the new mail-admin source allowlist.
All three host disko exports select only their inventoried SATA pair.
`nix flake check --no-build --all-systems` passes, and the x86_64
`homelab-configuration` check builds successfully (manifests, all 273 retained
service/network/recovery tests, provider formatting, RouterOS syntax and shell checks).
Documentation/operations cleanup and final repository acceptance remain in
progress; these checks do not establish deployment or restore readiness.
PiKVM access, motherboard USB boot, boot from either mirrored SATA member,
network MTUs/LACP, new Ceph formation, all off-server backups and application
restores remain future live qualifications.

The full repository formatter passed. The working-tree and Git-history secret
scans passed with no leaks across 851 source commits; output was redacted.
These checks are reproducible through the documented Nix commands and do not
change live systems. Final source-recapture tooling and the complete acceptance
audit remain outstanding.

## Final capture and reference checks

The repository source capture qualified against the actual frozen source using
read-only APIs. It encrypted 742 source Secrets/ConfigMaps and preserved all
18 required runtime/state inputs; the complete volume/cloud/certificate counts
match the prepared inventory. Nine artifact hashes and 0600/0700 modes verified.
All four fresh provider states retain their lineages, and all four TLS/account
seed resources pass the existing offline checks. Manila export enumeration
explicitly requests API microversion 2.9. Nine regression cases cover pagination,
microversion preservation, incomplete APIs, private-field exclusion, file modes,
overwrite refusal and absent completion markers on failure.

The source-to-target audit verifies all 798 dispositions and existing target
paths. Current Markdown guides have no missing repository links. Historical
source records are labelled; optional host enrollment is consolidated under
credentials. This capture qualifies configuration/metadata preservation, not
application-data backups or a target deployment.

Final broad verification passed on 2026-10-12 after the source capture and
credential/documentation cleanup. All-system flake checking, five host and four
disko evaluations, the combined Nix check with 273 tests, 46 enrollment tests,
four offline provider validations, the full 1,194-instance native/Helm validation
and both secret scans passed. No missing schemas or local guide links remain.
The original main checkout remains clean at 8d5f130; no live configuration,
PiKVM, data-transfer or disk operation occurred.
