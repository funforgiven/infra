# Mail edge

This OpenTofu root reserves a stable Hetzner IPv4 address, configures reverse
DNS, creates a protected CX23 server in Helsinki, enables provider backups, and
attaches a least-open inbound firewall. It initially boots Debian only as the
documented nixos-anywhere installation substrate.

The NixOS disk layout and Stalwart service are the authoritative host
configuration. After the suspended OpenTofu plan is reviewed and applied:

1. Confirm the new server contains no state that must be retained.
2. Run nix run .#nixos-anywhere with --flake .#mail-edge and the reported IPv4
   target. This repartitions the server and is destructive by design.
3. Enroll the SOPS host identity and the Stalwart and Resend runtime
   credentials without placing plaintext in Git or OpenTofu state.
4. Run the first encrypted Stalwart backup and restore it into an isolated host.
5. Through the private management interface, add the domain, initial mailbox,
   aliases, and application passwords described by the redacted desired
   directory inventory. Make additive changes only and back up immediately.
6. Publish DNS only after SMTP, TLS, SPF, DKIM, DMARC, inbound delivery, and
   Resend relay checks pass.

The OpenTofu lifecycle and Hetzner delete/rebuild protections deliberately
block casual replacement. The management CIDR sentinel in wave 84 must be
replaced with an explicit operator network before activation.

Stalwart is pinned to the latest release compatible with the NixOS module.
That release predates the safe declarative directory apply interface. The
temporary manual bootstrap is therefore recorded as
stalwart-directory-bootstrap in manual-exceptions.yaml. Do not build an
automatic delete-and-recreate reconciler on the legacy principal API: account
identifier changes can detach stored mail. Migrate this inventory to the
supported declarative apply workflow as soon as the compatible module lands.
