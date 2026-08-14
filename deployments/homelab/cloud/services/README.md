# Self-hosted services platform

This directory is the Flux root for the Magnum workload cluster named
`services-v1`. It is intentionally separate from the OpenStack undercloud and
the CAPI management cluster: application failures, upgrades, browser workloads,
and media jobs cannot consume control-plane capacity.

## Placement and trust boundaries

| Boundary | Placement | Initial workloads |
| --- | --- | --- |
| OpenStack control plane | Existing undercloud | Keystone, Magnum, Cinder, Manila, Octavia, Flux controllers |
| Services Kubernetes | Magnum, three 2-vCPU/4-GiB masters and two 4-vCPU/12-GiB workers | Karakeep, SearXNG, databases, Navidrome, acquisition workflow, monitoring |
| Agent VM | Dedicated NixOS VM in the `services` project | Hermes Agent, Telegram conversation bot, Codex OAuth state |
| Home automation VM | Dedicated NixOS VM in the `services` project | Home Assistant and hardware/LAN integrations |
| Mail edge | Dedicated Hetzner NixOS VM | Stalwart ingress and Resend-backed outbound delivery |

The OpenStack `public` network is RFC1918 provider space. Magnum floating IPs
therefore provide routed LAN reachability, not Internet exposure. Public HTTP
endpoints are explicit DNS allow-list entries; all other routes remain private.

## Retrieval policy

Karakeep full-text search is the only knowledge retrieval layer in the initial
deployment. Vector databases, embeddings, Hindsight, and other semantic-memory
services are deferred until Karakeep's own retrieval is satisfactory or measured
usage demonstrates that a separate layer is justified.

## Activation gates

All mutation waves remain suspended until credentials and immutable artifacts
pass the machine-checked contract. Follow [ACTIVATION.md](ACTIVATION.md); the
cluster reconciler keeps its kubeconfig and rendered credentials on
memory-backed volumes, discovers provider identifiers from controller outputs,
and bootstraps Flux only from signed `main` commits.
