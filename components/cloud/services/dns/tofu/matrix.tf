variable "matrix_wan_ipv4_address" {
  description = "Static homelab public IPv4; empty until Matrix enrollment configures DNS"
  type        = string
  default     = ""

  validation {
    condition     = var.matrix_wan_ipv4_address == "" || can(cidrhost("${var.matrix_wan_ipv4_address}/32", 0))
    error_message = "Matrix WAN address must be an IPv4 address."
  }
}

resource "cloudflare_dns_record" "matrix_public" {
  for_each = var.matrix_wan_ipv4_address == "" ? toset([]) : toset([
    "matrix.fahrican.com", "matrix-auth.fahrican.com", "element.fahrican.com", "chat.fahrican.com", "auth.cloud.fahrican.com",
  ])
  zone_id = data.cloudflare_zone.fahrican.zone_id
  name    = each.value
  type    = "A"
  content = var.matrix_wan_ipv4_address
  ttl     = 300
  proxied = false
  comment = "Git-managed public Matrix endpoint; federation disabled"
}
