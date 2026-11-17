mock_provider "cloudflare" {}

override_data {
  target = data.cloudflare_zone.fahrican
  values = { zone_id = "0123456789abcdef0123456789abcdef" }
}

variables {
  mail_enabled            = true
  resend_records_json     = "[{\"type\":\"TXT\",\"name\":\"resend._domainkey\",\"value\":\"test-key\",\"record\":\"DKIM\"}]"
  matrix_wan_ipv4_address = "203.0.113.20"
}

run "paused_declines_mail_without_advertising_released_ip" {
  command = plan

  variables {
    mail_enabled = false
  }

  assert {
    condition     = cloudflare_dns_record.mail_exchange.content == "." && cloudflare_dns_record.mail_exchange.priority == 0 && length(cloudflare_dns_record.mail_hosts) == 0 && output.mail_ipv4_address == null
    error_message = "Paused mail must publish Null MX and must not retain public mail A records."
  }

  assert {
    condition     = cloudflare_dns_record.apex_spf.content == "v=spf1 -all" && cloudflare_dns_record.mta_sts == null && cloudflare_dns_record.tls_reports == null && cloudflare_dns_record.mail_spf == null
    error_message = "Paused mail must not authorize the released EIP or advertise unavailable mail transport policies."
  }

  assert {
    condition     = length(cloudflare_dns_record.matrix_public) == 5 && length(cloudflare_dns_record.resend_verification) == 1 && cloudflare_dns_record.netbird.content == "203.0.113.20"
    error_message = "Pausing mail must preserve Matrix, NetBird and Resend verification records."
  }
}

run "active_requires_mail_address" {
  command         = plan
  expect_failures = [var.mail_ipv4_address]
}

run "resumed_publishes_new_address" {
  command = plan

  variables {
    mail_ipv4_address = "203.0.113.10"
  }

  assert {
    condition     = cloudflare_dns_record.mail_exchange.content == "mail.fahrican.com" && cloudflare_dns_record.mail_exchange.priority == 10 && cloudflare_dns_record.mail_hosts["mail"].content == "203.0.113.10"
    error_message = "Resumed mail must publish its new EIP and normal MX."
  }
}
