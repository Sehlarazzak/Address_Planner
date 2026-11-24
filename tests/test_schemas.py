"""STRUCTURE tests. These already pass. Read them, then ADD the 3 TODO tests at the bottom."""
import unittest

from tests.helpers import ORG_FILES, clone, org, plan
from planner.validate import validate_structure


class TestInputStructure(unittest.TestCase):
    def test_all_sample_orgs_are_structurally_valid(self):
        for name in ORG_FILES:
            with self.subTest(org=name):
                validate_structure(org(name), "input")

    def test_missing_required_field_is_rejected(self):
        bad = clone(org("org_small"))
        del bad["ipv4_block"]
        with self.assertRaisesRegex(ValueError, "ipv4_block"):
            validate_structure(bad, "input")

    def test_negative_growth_is_rejected(self):
        bad = clone(org("org_small"))
        bad["sites"][0]["subnets"][0]["growth_pct"] = -5
        with self.assertRaises(ValueError):
            validate_structure(bad, "input")

    def test_unexpected_field_is_rejected(self):
        bad = clone(org("org_small"))
        bad["colour"] = "blue"
        with self.assertRaisesRegex(ValueError, "colour"):
            validate_structure(bad, "input")

    def test_ipv6_prefix_must_be_a_slash_48(self):
        bad = clone(org("org_small"))
        bad["ipv6_prefix"] = "2001:db8:1000::/56"
        with self.assertRaises(ValueError):
            validate_structure(bad, "input")

    def test_sample_sizes_match_the_proposal(self):
        def lans(o):
            return sum(len(s["subnets"]) for s in o["sites"])
        self.assertEqual(lans(org("org_small")), 3)
        self.assertEqual(lans(org("org_medium")), 6)
        self.assertEqual(lans(org("org_large")), 10)
        sample = org("org_sample_15")
        self.assertEqual(lans(sample) + len(sample["links"]), 15)  # 12 LANs + 3 links


class TestPlanStructure(unittest.TestCase):
    def test_example_plan_is_structurally_valid(self):
        validate_structure(plan(), "plan")

    def test_plan_subnet_needs_an_ipv6_prefix(self):
        bad = clone(plan())
        del bad["subnets"][0]["ipv6_cidr"]
        with self.assertRaisesRegex(ValueError, "ipv6_cidr"):
            validate_structure(bad, "plan")

    def test_interface_type_must_be_lan_or_link(self):
        bad = clone(plan())
        bad["subnets"][0]["type"] = "wifi"
        with self.assertRaises(ValueError):
            validate_structure(bad, "plan")

    # ---- TODO (you write these; each is 3-5 lines) ------------------------------------
   

    def test_todo_ipv4_prefixlen_above_30_is_rejected(self):
        bad = clone(plan())
        bad["subnets"][0]["ipv4_prefixlen"] = 31
        with self.assertRaises(ValueError):
            validate_structure(bad, "plan")

    def test_todo_ipv6_cidr_that_is_not_a_slash_64_is_rejected(self):
        bad = clone(plan())
        bad["subnets"][0]["ipv6_cidr"] = "2001:db8:1000:1000::/63"
        with self.assertRaises(ValueError):
            validate_structure(bad, "plan")

    def test_todo_plan_with_one_router_is_rejected(self):
        bad = clone(plan())
        bad["routers"] = bad["routers"][:1]
        with self.assertRaises(ValueError):
            validate_structure(bad, "plan")

if __name__ == "__main__":
    unittest.main()
