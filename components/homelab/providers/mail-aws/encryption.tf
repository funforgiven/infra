# State and plans are committed encrypted; `nix run .#tofu` supplies the
# passphrase from secrets/opentofu-state.sops.yaml. See ../README.md.
variable "state_passphrase" {
  type      = string
  sensitive = true
}

terraform {
  encryption {
    key_provider "pbkdf2" "state" {
      passphrase = var.state_passphrase
    }

    method "aes_gcm" "state" {
      keys = key_provider.pbkdf2.state
    }

    state {
      method   = method.aes_gcm.state
      enforced = true
    }

    plan {
      method   = method.aes_gcm.state
      enforced = true
    }

    remote_state_data_sources {
      default {
        method = method.aes_gcm.state
      }
    }
  }
}
