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

Both undercloud waves are committed with `spec.suspend: true`. Before resuming
them, all of the following must be true:

1. `services-flux-bootstrap` is valid SOPS ciphertext and decrypts only for the
   undercloud Flux identity and the offline administrator.
2. The foundation OpenTofu plan contains only the reviewed project, quota,
   flavor, and networking resources.
3. The Magnum template image and Kubernetes checksum still match
   `versions.yaml`.
4. The services workload root builds locally and its encrypted secrets can be
   decrypted by the dedicated services Flux identity.
5. Backups and restore qualifications are present before stateful applications
   accept production data.

Resume `wave81-services-foundation` first. Resume
`wave82-services-cluster` only after the Terraform resource is Ready. The
cluster reconciler keeps its kubeconfig on a memory-backed volume and bootstraps
Flux from signed commits.
