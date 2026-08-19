import ipaddress
import unittest

from reconcile_services_operator_network import address_cidr


class OperatorNetworkTest(unittest.TestCase):
    def test_uses_one_host_cidr_for_each_address_family(self) -> None:
        self.assertEqual(address_cidr(ipaddress.ip_address("192.0.2.10")), "192.0.2.10/32")
        self.assertEqual(address_cidr(ipaddress.ip_address("2001:db8::10")), "2001:db8::10/128")


if __name__ == "__main__":
    unittest.main()
