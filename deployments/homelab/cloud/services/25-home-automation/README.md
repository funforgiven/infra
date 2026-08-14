# Home Assistant route

Home Assistant runs on its dedicated NixOS VM, not in Kubernetes. This layer
declaratively bridges the stable private address 192.168.80.10:8123 into the
services Gateway and publishes only home.fahrican.com. The NixOS service trusts
forwarding headers solely from the services subnet.

Keep the Flux wave suspended until the VM has a qualified off-site Restic
backup, the first isolated restore succeeds, and the Gateway can reach the
private endpoint. UI-only Home Assistant integration enrollment remains the
documented exception in manual-exceptions.yaml and must be followed by a state
backup.
