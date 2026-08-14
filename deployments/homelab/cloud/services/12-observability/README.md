# Services observability activation

Prometheus and Alertmanager are isolated from the undercloud monitoring stack so
a services-cluster failure cannot overload or alter OpenStack monitoring.

The services bootstrap reconciler derives the bot Secret and Alertmanager
values from SOPS ciphertext in memory; no token or chat identifier is edited
into this layer. The infrastructure bot must not be shared with Hermes or the
media workflow. Resume the services-observability wave before the backup
controller so Velero backup failures, missing backups, and capacity alerts are
visible from the beginning.
