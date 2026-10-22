# Service DNS

Public Cloudflare records for `fahrican.com`.

- Private application names point at the routed-LAN services Gateway. The
  address is not Internet-routable; publishing it publicly keeps one name per
  service for LAN, NetBird and router-VPN clients.
- Mail records follow the AWS mail EIP, read from the `mail-aws` state, so they
  cannot drift from the instance.
- Matrix, its auth hosts and NetBird resolve to the homelab's static WAN
  address. Change `homelab_wan_ipv4_address` together with
  `deployments/homelab/network/mail-admin-vpn.json` and the NetBird
  network policy if the ISP address changes.
- Resend issues its own verification records; pass them as
  `TF_VAR_resend_records_json` (the JSON array from the Resend dashboard or
  API). The Cloudflare token comes from the environment and never enters state.

Enable the mail PTR (`enable_reverse_dns` in `mail-aws`) only after forward DNS
resolves to the EIP. Bump the `_mta-sts` policy ID whenever the served MTA-STS
policy changes.
