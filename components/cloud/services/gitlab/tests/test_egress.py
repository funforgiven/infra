"""Exercise CI egress boundaries, including every private subnet and IPv4 edge."""

import ipaddress
import json
from pathlib import Path
import unittest


class EgressTests(unittest.TestCase):
    def setUp(self):
        self.networks = [ipaddress.ip_network(value) for value in json.loads(
            (Path(__file__).resolve().parents[1] / "runners-tofu/internet-ipv4.json").read_text()
        )]

    def allowed(self, address):
        return any(ipaddress.ip_address(address) in net for net in self.networks)

    def test_private_and_metadata_ranges_cannot_escape_via_web_rules(self):
        for cidr in ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                     "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
                     "0.0.0.0/8", "224.0.0.0/3", "198.18.0.0/15"]:
            blocked = ipaddress.ip_network(cidr)
            for net in self.networks:
                self.assertFalse(net.overlaps(blocked), (net, blocked))

    def test_public_download_endpoints_remain_reachable(self):
        for address in ["1.1.1.1", "8.8.8.8", "140.82.112.3", "20.190.128.1",
                        "104.18.32.7", "162.159.200.1"]:
            self.assertTrue(self.allowed(address), address)

    def test_boundaries_and_no_overlapping_rules(self):
        for index, net in enumerate(self.networks):
            self.assertFalse(any(net.overlaps(other) for other in self.networks[index+1:]))
        for address in ["9.255.255.255", "11.0.0.0", "172.15.255.255", "172.32.0.0"]:
            self.assertTrue(self.allowed(address), address)
        for address in ["10.0.0.0", "10.255.255.255", "172.16.0.0", "172.31.255.255"]:
            self.assertFalse(self.allowed(address), address)


if __name__ == "__main__":
    unittest.main()
