# Services observability activation

Prometheus and Alertmanager are isolated from the undercloud monitoring stack so
a services-cluster failure cannot overload or alter OpenStack monitoring.

Before activation, create infrastructure-telegram.sops.yaml with a single
bot-token key encrypted for the services Flux identity, add it to this
kustomization, and replace chat_id 0 with the dedicated infrastructure chat's
numeric identifier. The bot must not be shared with Hermes or Home Assistant.

Remove the HelmRelease suspension only after those changes. Resume the
services-observability wave before the backup controller so Velero backup
failures, missing backups, and capacity alerts are visible from the beginning.
