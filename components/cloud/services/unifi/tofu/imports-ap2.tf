# These narrowly scoped rules were pre-staged live before the second AP was
# connected. Import them on the next GitOps apply instead of creating duplicate
# Neutron rules. Remove these blocks once that apply has recorded both IDs.
import {
  to = openstack_networking_secgroup_rule_v2.ingress["inform_ap2"]
  id = "a7cc9e7b-8429-4bf8-80bb-86c0bb957a1f"
}

import {
  to = openstack_networking_secgroup_rule_v2.ingress["stun_ap2"]
  id = "0ec6414a-317a-4f52-b858-572ea0622b71"
}
