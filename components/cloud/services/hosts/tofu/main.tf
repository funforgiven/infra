terraform {
  required_version = ">= 1.12.1, < 1.13.0"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "= 3.4.0"
    }
  }
}

provider "openstack" {
  # The controller receives the existing administrative credential Secret,
  # which may itself be scoped to the admin project. Explicitly request the
  # services project without persisting or minting another credential.
  tenant_id           = ""
  tenant_name         = "services"
  project_domain_name = "Default"
}

locals {
  tags = ["managed-by-opentofu", "platform-services"]
}

# The owner authorized retirement of the empty standalone Home Assistant.
# Kubernetes now owns application state; remove the VM, both boot volumes,
# dedicated ports and security groups, without a legacy restore dependency.

removed {
  from = openstack_networking_secgroup_v2.service_ssh

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.service_ssh

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.service_icmp

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.service_node_exporter

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_v2.home_assistant_private

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.home_assistant_private_http

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_v2.home_assistant_provider

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.home_assistant_provider_ssh

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.home_assistant_provider_http

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.home_assistant_provider_mdns

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.home_assistant_provider_ssdp

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_secgroup_rule_v2.home_assistant_provider_icmp

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_port_v2.home_assistant_services

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_port_v2.home_assistant_provider

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_blockstorage_volume_v3.home_assistant_root

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_blockstorage_volume_v3.home_assistant_os_root

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_compute_instance_v2.home_assistant

  lifecycle {
    destroy = true
  }
}

# Hermes is retired. These blocks explicitly destroy its cloud resources when
# the reviewed services-hosts plan is applied.
removed {
  from = openstack_compute_instance_v2.hermes

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_floatingip_v2.hermes

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_networking_port_v2.hermes

  lifecycle {
    destroy = true
  }
}

removed {
  from = openstack_blockstorage_volume_v3.hermes_root

  lifecycle {
    destroy = true
  }
}
