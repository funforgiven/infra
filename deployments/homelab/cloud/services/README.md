# Self-hosted services

This directory is the Flux root for the `services-v1` Magnum cluster. Application
workloads are kept outside the OpenStack undercloud and the CAPI management
cluster so their failures and resource use cannot consume control-plane
capacity.

## Placement

| Location | Workloads |
| --- | --- |
| OpenStack undercloud | Keystone, Magnum, Cinder, Manila, Octavia, and undercloud Flux controllers |
| Services Kubernetes cluster | Media applications, databases, Envoy Gateway, monitoring, and Velero |
| Home Assistant VM | Current NixOS installation; retained HAOS image and volume for the planned cutover |
| AWS Frankfurt | Stalwart mail, RDS PostgreSQL, S3 message storage, and CloudWatch monitoring |

The OpenStack `public` network is RFC1918 provider space. Floating addresses
provide routed LAN access, not direct Internet exposure. Public DNS records are
explicitly declared; application routes remain reachable only from the LAN and
administration WireGuard network.

## Service catalog

| Service | Placement | Access and authentication |
| --- | --- | --- |
| Navidrome | Services cluster | `https://music.fahrican.com`; native Navidrome/Subsonic accounts |
| SFTPGo | Services cluster | `https://upload.fahrican.com`; ZITADEL OIDC for the WebClient |
| Beets | Services cluster | No direct user endpoint; imports accepted uploads into the media library |
| AudioMuse | Services cluster | `https://audiomuse.fahrican.com`; LAN/WireGuard only, with ZITADEL OIDC |
| Home Assistant | Dedicated VM | `https://home.fahrican.com`; native local account and MFA |
| Stalwart mail | AWS appliance | Native mail accounts; public mail protocols and web administration |
| Prometheus and Alertmanager | Services cluster | Administrative monitoring; Alertmanager uses the infrastructure Telegram bot |
| Velero | Services cluster | Filesystem backups to the service-specific Backblaze prefix |

ZITADEL is used where an application supports a suitable browser OIDC flow.
Protocol clients retain their native authentication: Navidrome keeps Subsonic
credentials, Home Assistant keeps its supported local account, and mail clients
use Stalwart credentials.

## Operations

Flux dependency ordering is declared in [`waves.yaml`](waves.yaml). Do not copy
that order into a manual activation sequence or use live suspension as lasting
configuration.

- Credential rotation, provider reconciliation, image promotion, host backup
  initialization, and HAOS cutover: [service operations](ACTIVATION.md)
- Telegram alert-bot creation and target enrollment: [Telegram bootstrap](TELEGRAM.md)
- Purchased-media import and recovery: [media workflow](40-media/README.md)
- Backup and isolated restore behavior: [backup policy](16-backup-policy/README.md)
- AWS mail operation and recovery:
  [mail runbook](../../../../components/cloud/services/mail-aws/README.md)

The services Gateway, certificate, routes, monitoring, and backup policies are
reconciled from this Flux root. Provider-created identifiers and credentials are
written to SOPS documents by their focused reconcilers; they are not hand-edited
into workload manifests.
