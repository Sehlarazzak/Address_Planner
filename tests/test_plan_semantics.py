"""SEMANTIC plan tests = your overlap detector.

Each test takes a plan, breaks ONE thing (or sets up a valid layout), and checks behavior.
"""
import unittest

from planner.validate import validate_plan_semantics
from tests.helpers import clone, plan


def subnet(p, sid):
    return next(s for s in p["subnets"] if s["id"] == sid)


def iface(p, router, name):
    r = next(r for r in p["routers"] if r["name"] == router)
    return next(i for i in r["interfaces"] if i["name"] == name)


class TestPlanSemantics(unittest.TestCase):
    def test_good_plan_passes(self):
        validate_plan_semantics(plan())

    def test_valid_plan_with_ipv4_sites_and_link_block_passes(self):
        p = clone(plan())
        p["ipv4_block"] = "10.10.0.0/22"
        p["ipv4_sites"] = {
            "A": "10.10.0.0/23",
            "B": "10.10.2.0/24",
        }
        p["ipv4_link_block"] = "10.10.3.0/29"
        p["subnets"] = [
            {
                "id": "A-LAN1",
                "site": "A",
                "name": "lan1",
                "type": "lan",
                "hosts_requested": 100,
                "growth_pct": 0,
                "hosts_required": 100,
                "ipv4_cidr": "10.10.0.0/25",
                "ipv4_prefixlen": 25,
                "ipv4_usable": 126,
                "ipv6_cidr": "2001:db8:1000:1000::/64",
            },
            {
                "id": "B-LAN1",
                "site": "B",
                "name": "lan1",
                "type": "lan",
                "hosts_requested": 50,
                "growth_pct": 0,
                "hosts_required": 50,
                "ipv4_cidr": "10.10.2.0/26",
                "ipv4_prefixlen": 26,
                "ipv4_usable": 62,
                "ipv6_cidr": "2001:db8:1000:2000::/64",
            },
            {
                "id": "A-B",
                "site": "A",
                "name": "ab",
                "type": "link",
                "hosts_requested": 2,
                "growth_pct": 0,
                "hosts_required": 2,
                "ipv4_cidr": "10.10.3.0/30",
                "ipv4_prefixlen": 30,
                "ipv4_usable": 2,
                "ipv6_cidr": "2001:db8:1000:f000::/64",
            },
        ]
        p["routers"] = [
            {
                "name": "R1",
                "site": "A",
                "interfaces": [
                    {"name": "eth1", "subnet_id": "A-LAN1", "ipv4": "10.10.0.1", "ipv6": "2001:db8:1000:1000::1"},
                    {"name": "eth2", "subnet_id": "A-B", "ipv4": "10.10.3.1", "ipv6": "2001:db8:1000:f000::1"},
                ],
            },
            {
                "name": "R2",
                "site": "B",
                "interfaces": [
                    {"name": "eth1", "subnet_id": "B-LAN1", "ipv4": "10.10.2.1", "ipv6": "2001:db8:1000:2000::1"},
                    {"name": "eth2", "subnet_id": "A-B", "ipv4": "10.10.3.2", "ipv6": "2001:db8:1000:f000::2"},
                ],
            },
        ]
        validate_plan_semantics(p)

    # --- IPv4 --------------------------------------------------------------------------
    def test_ipv4_subnet_outside_the_block_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-B")["ipv4_cidr"] = "192.168.0.224/30"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_overlapping_ipv4_subnets_are_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN2")["ipv4_cidr"] = "10.10.0.64/26"
        subnet(bad, "A-LAN2")["ipv4_prefixlen"] = 26
        with self.assertRaisesRegex(ValueError, "(?i)overlap"):
            validate_plan_semantics(bad)

    def test_non_strict_ipv4_cidr_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN2")["ipv4_cidr"] = "10.10.0.130/26"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_prefixlen_field_must_match_the_cidr(self):
        bad = clone(plan())
        subnet(bad, "A-LAN1")["ipv4_prefixlen"] = 24
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_subnet_too_small_for_required_hosts_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN1")["hosts_required"] = 127
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_lan_outside_its_ipv4_site_block_is_rejected(self):
        bad = clone(plan())
        bad["ipv4_block"] = "10.10.0.0/22"
        bad["ipv4_sites"] = {"A": "10.10.0.0/24", "B": "10.10.1.0/24"}
        subnet(bad, "A-LAN1")["ipv4_cidr"] = "10.10.1.0/25"
        subnet(bad, "A-LAN1")["ipv4_prefixlen"] = 25
        with self.assertRaisesRegex(ValueError, "(?i)site block"):
            validate_plan_semantics(bad)

    def test_link_outside_ipv4_link_block_is_rejected(self):
        bad = clone(plan())
        bad["ipv4_block"] = "10.10.0.0/22"
        bad["ipv4_sites"] = {"A": "10.10.0.0/24", "B": "10.10.1.0/24"}
        bad["ipv4_link_block"] = "10.10.2.0/29"
        bad["subnets"] = [
            {
                "id": "A-LAN1",
                "site": "A",
                "name": "lan1",
                "type": "lan",
                "hosts_requested": 50,
                "growth_pct": 0,
                "hosts_required": 50,
                "ipv4_cidr": "10.10.0.0/26",
                "ipv4_prefixlen": 26,
                "ipv4_usable": 62,
                "ipv6_cidr": "2001:db8:1000:1000::/64",
            },
            {
                "id": "B-LAN1",
                "site": "B",
                "name": "lan1",
                "type": "lan",
                "hosts_requested": 50,
                "growth_pct": 0,
                "hosts_required": 50,
                "ipv4_cidr": "10.10.1.0/26",
                "ipv4_prefixlen": 26,
                "ipv4_usable": 62,
                "ipv6_cidr": "2001:db8:1000:2000::/64",
            },
            {
                "id": "A-B",
                "site": "A",
                "name": "ab",
                "type": "link",
                "hosts_requested": 2,
                "growth_pct": 0,
                "hosts_required": 2,
                "ipv4_cidr": "10.10.3.0/30",
                "ipv4_prefixlen": 30,
                "ipv4_usable": 2,
                "ipv6_cidr": "2001:db8:1000:f000::/64",
            },
        ]
        bad["routers"] = [
            {
                "name": "R1",
                "site": "A",
                "interfaces": [
                    {"name": "eth1", "subnet_id": "A-LAN1", "ipv4": "10.10.0.1", "ipv6": "2001:db8:1000:1000::1"},
                    {"name": "eth2", "subnet_id": "A-B", "ipv4": "10.10.3.1", "ipv6": "2001:db8:1000:f000::1"},
                ],
            },
            {
                "name": "R2",
                "site": "B",
                "interfaces": [
                    {"name": "eth1", "subnet_id": "B-LAN1", "ipv4": "10.10.1.1", "ipv6": "2001:db8:1000:2000::1"},
                    {"name": "eth2", "subnet_id": "A-B", "ipv4": "10.10.3.2", "ipv6": "2001:db8:1000:f000::2"},
                ],
            },
        ]
        with self.assertRaisesRegex(ValueError, "(?i)link[_ ]block"):
            validate_plan_semantics(bad)

    def test_overlapping_ipv4_site_blocks_are_rejected(self):
        bad = clone(plan())
        bad["ipv4_block"] = "10.10.0.0/22"
        bad["ipv4_sites"] = {"A": "10.10.0.0/23", "B": "10.10.1.0/24"}
        with self.assertRaisesRegex(ValueError, "(?i)site block overlap"):
            validate_plan_semantics(bad)

    def test_ipv4_link_block_overlapping_site_block_is_rejected(self):
        bad = clone(plan())
        bad["ipv4_block"] = "10.10.0.0/22"
        bad["ipv4_sites"] = {"A": "10.10.0.0/24", "B": "10.10.1.0/24"}
        bad["ipv4_link_block"] = "10.10.1.128/25"
        with self.assertRaisesRegex(ValueError, "(?i)link[_ ]block.*overlap|overlap"):
            validate_plan_semantics(bad)

    def test_lan_site_missing_from_ipv4_sites_is_rejected(self):
        bad = clone(plan())
        bad["ipv4_block"] = "10.10.0.0/22"
        bad["ipv4_sites"] = {"B": "10.10.1.0/24"}
        with self.assertRaisesRegex(ValueError, "(?i)missing from ipv4_sites"):
            validate_plan_semantics(bad)

    # --- IPv6 --------------------------------------------------------------------------
    def test_ipv6_subnet_outside_the_48_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN1")["ipv6_cidr"] = "2001:db8:2000:1000::/64"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_duplicate_ipv6_subnets_are_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN2")["ipv6_cidr"] = subnet(bad, "A-LAN1")["ipv6_cidr"]
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_lan_outside_its_sites_52_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN1")["ipv6_cidr"] = "2001:db8:1000:2005::/64"
        with self.assertRaisesRegex(ValueError, "(?i)site|52"):
            validate_plan_semantics(bad)

    def test_link_outside_the_link_block_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-B")["ipv6_cidr"] = "2001:db8:1000:1fff::/64"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    # --- interfaces --------------------------------------------------------------------
    def test_interface_pointing_at_missing_subnet_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R1", "eth1")["subnet_id"] = "does-not-exist"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_interface_ipv4_outside_its_subnet_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R1", "eth1")["ipv4"] = "10.10.1.1"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_interface_ipv4_on_network_address_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R1", "eth1")["ipv4"] = "10.10.0.0"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_interface_ipv4_on_broadcast_address_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R1", "eth1")["ipv4"] = "10.10.0.127"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_interface_ipv6_outside_its_subnet_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R1", "eth1")["ipv6"] = "2001:db8:1000:1001::1"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_duplicate_ipv4_address_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R2", "eth2")["ipv4"] = iface(bad, "R1", "eth3")["ipv4"]
        with self.assertRaisesRegex(ValueError, "(?i)duplicate|twice|already"):
            validate_plan_semantics(bad)

    def test_duplicate_ipv6_address_is_rejected(self):
        bad = clone(plan())
        iface(bad, "R2", "eth2")["ipv6"] = iface(bad, "R1", "eth3")["ipv6"]
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_link_with_only_one_end_is_rejected(self):
        bad = clone(plan())
        bad["routers"][1]["interfaces"] = [i for i in bad["routers"][1]["interfaces"]
                                           if i["subnet_id"] != "A-B"]
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_lan_with_two_gateways_is_rejected(self):
        bad = clone(plan())
        bad["routers"][1]["interfaces"].append(
            {"name": "eth3", "subnet_id": "A-LAN1", "ipv4": "10.10.0.2", "ipv6": "2001:db8:1000:1000::2"})
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_todo_adjacent_subnets_are_NOT_an_overlap(self):
        import ipaddress

        p = plan()
        site_name = next(iter(p["ipv6_sites"]))
        site_52 = ipaddress.IPv6Network(p["ipv6_sites"][site_name], strict=True)
        sixties = list(site_52.subnets(new_prefix=64))
        net6_1, net6_2 = sixties[0], sixties[1]

        p["ipv4_block"] = "10.10.0.0/24"
        p["subnets"] = [
            {
                "id": "s1",
                "site": site_name,
                "name": "lan1",
                "type": "lan",
                "hosts_requested": 100,
                "growth_pct": 0,
                "hosts_required": 100,
                "ipv4_cidr": "10.10.0.0/25",
                "ipv4_prefixlen": 25,
                "ipv4_usable": 126,
                "ipv6_cidr": str(net6_1),
            },
            {
                "id": "s2",
                "site": site_name,
                "name": "lan2",
                "type": "lan",
                "hosts_requested": 50,
                "growth_pct": 0,
                "hosts_required": 50,
                "ipv4_cidr": "10.10.0.128/26",
                "ipv4_prefixlen": 26,
                "ipv4_usable": 62,
                "ipv6_cidr": str(net6_2),
            },
        ]
        p["routers"] = [
            {
                "name": "r1",
                "site": site_name,
                "interfaces": [
                    {
                        "name": "eth1",
                        "subnet_id": "s1",
                        "ipv4": "10.10.0.1",
                        "ipv6": str(net6_1[1]),
                    },
                    {
                        "name": "eth2",
                        "subnet_id": "s2",
                        "ipv4": "10.10.0.129",
                        "ipv6": str(net6_2[1]),
                    },
                ],
            }
        ]
        validate_plan_semantics(p)

    def test_todo_ipv4_subnet_equal_to_the_whole_block_overlapping_others(self):
        bad = plan()
        bad["ipv4_block"] = "10.10.0.0/24"
        bad["subnets"] = [
            {
                "id": "whole",
                "site": "A",
                "name": "all",
                "type": "lan",
                "hosts_requested": 100,
                "growth_pct": 0,
                "hosts_required": 100,
                "ipv4_cidr": "10.10.0.0/24",
                "ipv4_prefixlen": 24,
                "ipv4_usable": 254,
                "ipv6_cidr": "2001:db8:1000:1000::/64",
            },
            {
                "id": "sub",
                "site": "A",
                "name": "part",
                "type": "lan",
                "hosts_requested": 10,
                "growth_pct": 0,
                "hosts_required": 10,
                "ipv4_cidr": "10.10.0.0/28",
                "ipv4_prefixlen": 28,
                "ipv4_usable": 14,
                "ipv6_cidr": "2001:db8:1000:1001::/64",
            },
        ]
        bad["routers"] = [
            {
                "name": "r1",
                "site": "A",
                "interfaces": [
                    {
                        "name": "eth1",
                        "subnet_id": "whole",
                        "ipv4": "10.10.0.1",
                        "ipv6": "2001:db8:1000:1000::1",
                    },
                    {
                        "name": "eth2",
                        "subnet_id": "sub",
                        "ipv4": "10.10.0.2",
                        "ipv6": "2001:db8:1000:1001::1",
                    },
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "(?i)overlap"):
            validate_plan_semantics(bad)


if __name__ == "__main__":
    unittest.main()