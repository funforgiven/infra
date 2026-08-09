# Kubernetes bootstrap

Kubespray owns only the initial three-node Kubernetes, etcd, containerd,
kube-vip, and Cilium installation. Flux is the continuous owner of the
platform resources installed after that bootstrap boundary.

The inventory keeps every node address on VLAN 20. kube-vip owns only
`10.21.20.128:6443`. Cilium owns active Service L2 announcements; MetalLB is an
inactive, mutually exclusive rollback implementation. Cilium uses native
routing through `bond0.20`, admits the Manila NFS Service through `br-manila`,
uses pod MTU 1500, enables socket load balancing, and replaces kube-proxy. It
must not select VLANs 30-32.
ConfigMap changes roll the agent DaemonSet with at most one unavailable agent,
preserving networking on the other two nodes.

Host automation owns `systemd-resolved`; `resolvconf_mode: none` prevents
Kubespray from competing for the host resolver configuration. Kubernetes DNS
remains Kubespray-managed.

## Runner

Kubespray 2.31 requires Ansible Core 2.18 and must not run from the repository's
newer general-purpose Ansible environment. Run the exact upstream container
recorded in `../versions.yaml` with rootless Podman, host networking, and
`--pull=never` after pulling its digest explicitly.

Mount only these read-only inputs:

- `../hosts` at `/inventory`;
- `/run/secrets/github-ssh-key`;
- the three `/run/secrets/cloud-host-*-ubuntu-console-password` files; and
- `/run/secrets/undercloud-kube-encrypt-token`; and
- `/etc/ssh/ssh_known_hosts`.

The encryption key is stable SOPS ciphertext in Git and a private sops-nix
runtime file. Kubespray's other generated files are ephemeral under
`/run/kubespray`; use a control-plane host's root-owned admin kubeconfig for
bootstrap and recovery. Never mount the whole `/run/secrets` directory or write
generated credentials into this repository.

The mutation boundary is Kubespray's `cluster.yml`. Before it runs, require the
pinned container's inventory graph, SSH ping, Ansible syntax check, and an
unused `10.21.20.128` address. Run with host-key checking explicitly enabled;
the upstream container's relaxed SSH defaults are not accepted here. On an
existing cluster, pass `-e upgrade_cluster_setup=true` when changing control
plane configuration so kubeadm rewrites the static pod manifests. A normal
idempotent `cluster.yml` run renders supporting files but does not replace an
unchanged-version API server manifest.

## Acceptance

Playbook success alone is insufficient. The wave closes only after:

- all three nodes are Ready and all three etcd members are healthy;
- the API is ready through `https://10.21.20.128:6443`;
- exactly one node owns `10.21.20.128/32` on `bond0.20` and the kube-vip lease
  has one holder;
- the API VIP survives loss of its current owner;
- no kube-proxy DaemonSet exists;
- Cilium reports native routing, MTU 1500, socket load balancing, and
  kube-proxy replacement;
- Cilium health and cross-node connectivity pass; and
- VLANs 30-32 retain their existing direct, jumbo-MTU paths.
