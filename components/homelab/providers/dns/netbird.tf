resource "cloudflare_dns_record" "netbird" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "netbird.fahrican.com"
  type    = "A"
  content = var.matrix_wan_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Homelab NetBird coordination and relay; services remain private"
}

resource "cloudflare_dns_record" "netbird_stun" {
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = "netbird-stun.fahrican.com"
  type    = "A"
  content = var.matrix_wan_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Stateless homelab NetBird STUN workers"
}

moved {
  from = cloudflare_dns_record.netbird_api
  to   = cloudflare_dns_record.private_services["netbird-api"]
}
