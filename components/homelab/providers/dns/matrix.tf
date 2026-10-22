locals {
  # Static PPPoE address of the homelab router; also in
  # deployments/homelab/network/mail-admin-vpn.json.
  homelab_wan_ipv4_address = "31.223.15.252"
}

resource "cloudflare_dns_record" "matrix_public" {
  for_each = toset([
    "matrix.fahrican.com", "matrix-auth.fahrican.com", "element.fahrican.com", "chat.fahrican.com", "auth.cloud.fahrican.com",
  ])
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = each.value
  type    = "A"
  content = local.homelab_wan_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Git-managed public Matrix endpoint; federation disabled"
}
