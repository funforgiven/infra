# NixOS physical servers and independent mail

`deployments/homelab/hosts/` declares pecorino, taleggio and asiago as NixOS/K3s
servers with embedded etcd, preserved SSH identities, dedicated SOPS recipient,
25 Gb/s LACP/VLAN networking and mirrored-SATA disko. Their six NVMe disks are
outside disko and belong to Rook-Ceph. Home automation runs as Kubernetes pods;
UniFi retains a supported Ubuntu guest managed by KubeVirt. Mail remains on its
independent aarch64 AWS NixOS host.

The installation and credential-seeding commands are in
[RUNBOOK.md](../../../docs/migration/RUNBOOK.md). Required independent exports,
database recovery, guest and IoT state are in
[DATA-MIGRATION.md](../../../docs/migration/DATA-MIGRATION.md).
The migration branch performs no live installation or enrollment by itself.

Each physical server takes K3s etcd snapshots and sends them to the declared
off-server Restic prefix using the preserved B2 credential and dedicated etcd
password. New repository initialization is an explicit future step; the backup
service deliberately has `initialize=false`. Recovery requires the snapshot,
matching K3s token, TLS/bootstrap state and host identities together. Test a
fresh backup and independent restore before qualifying this path.

The retained service credential tools still enroll the declared native UniFi
and independent mail backup/monitoring profiles. Read
[secret recovery](../../../secrets/README.md) before changing credentials.
Matrix/Telegram host alerts, node-exporter textfiles and application backup
qualification remain part of the target observability configuration.
