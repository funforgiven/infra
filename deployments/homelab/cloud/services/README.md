# Self-hosted services platform

This directory is the Flux root for the Magnum workload cluster named
`services-v1`. It is intentionally separate from the OpenStack undercloud and
the CAPI management cluster: application failures, upgrades, browser workloads,
and media workloads cannot consume control-plane capacity.

## Placement and trust boundaries

| Boundary | Placement | Initial workloads |
| --- | --- | --- |
| OpenStack control plane | Existing undercloud | Keystone, Magnum, Cinder, Manila, Octavia, Flux controllers |
| Services Kubernetes | Magnum, three 2-vCPU/4-GiB masters and two 4-vCPU/12-GiB workers | Navidrome, SFTPGo, Beets, databases, backup, monitoring |
| Agent VM | Dedicated NixOS VM in the `services` project | Hermes Agent, Telegram conversation bot, direct OpenAI API runtime |
| Home automation VM | Dedicated HAOS appliance in the `services` project (migration is gated while NixOS remains live) | Home Assistant and hardware/LAN integrations |
| Mail platform | Dedicated AWS Frankfurt appliance with managed PostgreSQL and S3 | Stalwart ingress and Resend-backed outbound delivery |

The OpenStack `public` network is RFC1918 provider space. Magnum floating IPs
therefore provide routed LAN reachability, not Internet exposure. Public HTTP
endpoints are explicit DNS allow-list entries; all other routes remain private.

## Search and memory policy

No search engine, external knowledge store, vector database, embeddings, or
Hindsight service is deployed. Hermes disables its web toolset and autonomous
memory globally; add a retrieval layer only after a concrete need justifies its
operational and security cost.

## Human identity policy

ZITADEL is the central human identity provider wherever an application offers
a compatible native OIDC flow. The existing central Grafana at
`https://grafana.cloud.fahrican.com` uses ZITADEL; the services cluster
intentionally does not deploy a second Grafana.

Protocol and device clients keep application-native authentication when OIDC
would break their supported flow. Hermes has no human web login: its private
Telegram bot admits only the discovered allowed user, while its OpenAI key
authenticates the model API. Alertmanager sends
through the separate infrastructure bot and exposes no Telegram login.
Navidrome keeps native credentials for Subsonic clients such as Symfonium,
Home Assistant keeps its supported local account and MFA flow, and the pinned
Stalwart release keeps mail-client and recovery credentials. SFTPGo uses native
ZITADEL OIDC for its WebClient while its emergency administrator remains a
separate generated credential. These are deliberate boundaries, not a second IdP;
reassess native OIDC during application upgrades without placing an auth proxy
in front of protocol endpoints.

## Activation gates

All mutation waves remain suspended until credentials and immutable artifacts
pass the machine-checked contract. Follow [ACTIVATION.md](ACTIVATION.md); the
BotFather-specific identity steps are in [TELEGRAM.md](TELEGRAM.md). The
cluster reconciler keeps its kubeconfig and rendered credentials on
memory-backed volumes, discovers provider identifiers from controller outputs,
and bootstraps Flux only from signed `main` commits.
