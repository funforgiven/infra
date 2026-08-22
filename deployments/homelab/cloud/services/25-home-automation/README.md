# Home Assistant route

Home Assistant runs on its dedicated NixOS VM, not in Kubernetes. This layer
declaratively bridges the stable private address 192.168.80.10:8123 into the
services Gateway and publishes only home.fahrican.com.

Keep the Flux wave suspended until the VM has a qualified off-site Restic
backup, the first isolated restore succeeds, and the Gateway can reach the
private endpoint. Home Assistant 2026.8 stores HTTP settings in its authenticated
runtime registry and ignores the old YAML settings after one migration. Complete
first-administrator onboarding through the routed provider address, configure
the built-in HTTP settings to trust only `192.168.80.0/24` and use forwarded
headers, then verify and confirm the pending settings through
`https://home.fahrican.com` within the five-minute safety trial. This and UI-only
integration enrollment are documented exceptions in `manual-exceptions.yaml`;
each accepted change must be followed by an encrypted state backup.
