resource "cloudflare_dns_record" "netbird" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "netbird.fahrican.com"
  type    = "A"
  content = var.matrix_wan_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Homelab NetBird coordination and relay; services remain private"
}

resource "cloudflare_dns_record" "netbird_api" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "netbird-api.fahrican.com"
  type    = "A"
  content = local.services_gateway_address
  ttl     = 300
  proxied = false
  comment = "Private NetBird API for declarative administration"
}
