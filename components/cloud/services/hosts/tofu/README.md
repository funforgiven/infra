# Services hosts

This OpenTofu root creates the persistent OpenStack hosts that need capabilities
which do not fit the Kubernetes services cluster:

- Hermes receives a private services-network port and a fixed provider-LAN
  floating address for administration.
- Home Assistant is dual-homed. Its private address is used by the Kubernetes
  gateway, while its fixed provider-LAN port preserves local discovery traffic.
- Both hosts boot from retained Cinder volumes. Destruction of instances,
  volumes, fixed ports, and the Hermes floating address is blocked by lifecycle
  policy.

The root accepts only a full Git revision. Matching Glance images must have been
created by the promote-service-images flake app, which verifies a clean,
SSH-signed commit and records the source revision and SHA-256 as image
properties.

Activation is deliberately two-step:

1. Merge and sign the NixOS image configuration.
2. From a services-project OpenStack shell, run
   nix run .#promote-service-images.
3. Replace the all-zero image_revision in wave 83 with that full commit.
4. Review the resulting OpenTofu plan.
5. Remove the Terraform resource suspension only after backup and restore
   checks pass, then resume wave 83.

The controller uses the existing administrative runtime Secret, while the
provider explicitly re-scopes authentication to the services project. No
credential or generated guest secret is accepted as an OpenTofu variable.
