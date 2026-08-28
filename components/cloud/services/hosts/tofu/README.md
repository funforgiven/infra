# Home Assistant host

This OpenTofu root manages the persistent Home Assistant VM, ports, security
groups, and boot volumes in the OpenStack `services` project. The provider uses
the existing administrative credential but explicitly scopes requests to that
project. Credentials and guest secrets are not module inputs or outputs.

The [deployment controller](../../../../../deployments/homelab/cloud/undercloud/83-services-hosts/tofu.yaml)
reconciles every 10 minutes, applies plans automatically, and runs after the
services cluster. It writes the two address outputs below to the
`services-hosts-outputs` Kubernetes Secret. Deleting the controller does not
destroy the OpenStack resources.

The root currently contains `removed` blocks with `destroy = true` for retired
service-host resources. Those blocks deliberately make the next matching plan
destructive. Review that plan before merging a change to the retirement blocks.

## Inputs and images

| Input | Accepted value | Effect |
| --- | --- | --- |
| `image_revision` | Full lowercase 40-character Git commit | Selects the NixOS image and names its root volume |
| `home_assistant_platform` | `nixos` or `haos`; default `nixos` | Selects the boot volume and whether the VM uses a config drive |

`image_revision` selects the private
`nixos-home-assistant-<first 12 revision characters>` image with
`image_role=home-assistant` and the full `image_source_revision`. The HAOS
alternative is `haos-18.2`, with `image_role=home-assistant-os` and
`haos_version=18.2`.

The root reads these images but does not create or delete them. From a clean,
SSH-signed commit, build and upload the revision-matched NixOS image and import
the pinned official HAOS image after verifying its archive digest:

```console
nix run .#promote-service-images
```

Promotion does not change `image_revision` or the active platform. Changing
`image_revision` creates a new image-backed NixOS root and replaces resources
that refer to the old revision; it is not an in-place upgrade. The existing
root is protected from destruction, so prepare and review an explicit retained-
volume migration instead of expecting a routine controller apply to replace it.

## Networking and storage

| Address | Use |
| --- | --- |
| `192.168.80.10` | Services-network ingress and monitoring |
| `10.21.40.120`, MAC `fa:16:3e:80:00:10` | Trusted-LAN administration and local discovery |

Both fixed ports are protected from destruction. The NixOS and HAOS boot
volumes are each 100 GiB and protected from destruction. The VM uses the
`services.worker` flavor, stops before replacement, and never deletes its boot
volume on termination.

Security groups allow:

- SSH and ICMP from `10.21.10.0/24`;
- node-exporter TCP port 9100 from `192.168.80.0/24`;
- Home Assistant TCP port 8123 from both trusted networks; and
- mDNS UDP 5353 and SSDP UDP 1900 on the provider-facing port from
  `10.21.10.0/24`.

The OpenStack `public` network is private provider space; `10.21.40.120` is not
a directly Internet-routed address.

## Home Assistant OS cutover

Changing `home_assistant_platform` from `nixos` to `haos` replaces the VM,
disables its config drive, and attaches the retained HAOS root. Both ports and
both boot volumes remain. The plan should replace only the VM attachment.

Before switching:

1. Create a full encrypted native Home Assistant backup and save its emergency
   kit.
2. Restore the backup into an isolated HAOS instance and verify the required
   integrations and history.
3. Ensure `haos-18.2` has the pinned source digest.

After switching, restore the tested backup during onboarding. Neutron supplies
`192.168.80.10` by DHCP. Configure the provider interface as
`10.21.40.120/24`, add a route to `10.21.10.0/24` through `10.21.40.1`, and
trust forwarded HTTP headers only from `192.168.80.0/24`.

Configure encrypted daily native backups in `fahrican-cloud-recovery` under
`services/hosts/home-assistant/`, retain at least 14, and complete another
isolated restore. Keep the NixOS root until that restore succeeds. The full
procedure is in the [service operations guide](../../../../../deployments/homelab/cloud/services/ACTIVATION.md#home-assistant-os-cutover).

## Outputs

| Output | Value |
| --- | --- |
| `home_assistant_private_address` | `192.168.80.10` |
| `home_assistant_provider_address` | `10.21.40.120` |

## Validate

Run from the repository root before changing the selected revision:

```console
nix flake check --no-build --accept-flake-config
nix build .#home-assistant-openstack-image --no-link --accept-flake-config
```

Check the module without OpenStack credentials:

```console
cd components/cloud/services/hosts/tofu
tofu init -backend=false
tofu validate
```
