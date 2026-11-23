"""SEMANTIC plan tests = your overlap detector. They FAIL until validate_plan_semantics() exists.

Each test takes the good example plan, breaks ONE thing, and expects ValueError.
"""
import unittest

from tests.helpers import clone, plan
from planner.validate import validate_plan_semantics


def subnet(p, sid):
    return next(s for s in p["subnets"] if s["id"] == sid)


def iface(p, router, name):
    r = next(r for r in p["routers"] if r["name"] == router)
    return next(i for i in r["interfaces"] if i["name"] == name)


class TestPlanSemantics(unittest.TestCase):
    def test_good_plan_passes(self):
        validate_plan_semantics(plan())

    # --- IPv4 --------------------------------------------------------------------------
    def test_ipv4_subnet_outside_the_block_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-B")["ipv4_cidr"] = "192.168.0.224/30"
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_overlapping_ipv4_subnets_are_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN2")["ipv4_cidr"] = "10.10.0.64/26"       # sits inside LAN1 10.10.0.0/25
        subnet(bad, "A-LAN2")["ipv4_prefixlen"] = 26
        with self.assertRaisesRegex(ValueError, "(?i)overlap"):
            validate_plan_semantics(bad)

    def test_non_strict_ipv4_cidr_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN2")["ipv4_cidr"] = "10.10.0.130/26"      # host bits set
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_prefixlen_field_must_match_the_cidr(self):
        bad = clone(plan())
        subnet(bad, "A-LAN1")["ipv4_prefixlen"] = 24
        with self.assertRaises(ValueError):
            validate_plan_semantics(bad)

    def test_subnet_too_small_for_required_hosts_is_rejected(self):
        bad = clone(plan())
        subnet(bad, "A-LAN1")["hosts_required"] = 127              # a /25 has only 126 usable
        with self.assertRaises(ValueError):
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
        subnet(bad, "A-LAN1")["ipv6_cidr"] = "2001:db8:1000:2005::/64"   # inside site B's /52
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

    # ---- TODO (you write these) ------------------------------------------------------
    def test_todo_ipv4_subnet_equal_to_the_whole_block_overlapping_others(self):
        self.skipTest("TODO: make one subnet the entire ipv4_block and expect an overlap error")

    def test_todo_adjacent_subnets_are_NOT_an_overlap(self):
        self.skipTest("TODO: confirm 10.10.0.0/25 and 10.10.0.128/26 (touching, not overlapping) "
                      "pass. This guards against an off-by-one in your overlap logic")


if __name__ == "__main__":
    unittest.main()
