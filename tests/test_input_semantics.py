"""SEMANTIC input tests. They FAIL until you implement validate_input_semantics()."""
import unittest

from tests.helpers import ORG_FILES, clone, org
from planner.validate import validate_input_semantics, validate_structure


class TestInputSemantics(unittest.TestCase):
    def test_all_sample_orgs_pass(self):
        for name in ORG_FILES:
            with self.subTest(org=name):
                validate_input_semantics(org(name))

    def test_non_strict_ipv4_block_is_rejected(self):
        bad = clone(org("org_small"))
        bad["ipv4_block"] = "10.10.0.5/23"          # host bits set
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_impossible_ipv4_octet_is_rejected(self):
        bad = clone(org("org_small"))
        bad["ipv4_block"] = "10.10.300.0/23"
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_ipv6_prefix_that_is_not_48_is_rejected(self):
        bad = clone(org("org_small"))
        bad["ipv6_prefix"] = "2001:db8:1000::/56"
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_duplicate_site_names_are_rejected(self):
        bad = clone(org("org_medium"))
        bad["sites"][1]["name"] = bad["sites"][0]["name"]
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_duplicate_router_names_are_rejected(self):
        bad = clone(org("org_medium"))
        bad["sites"][1]["router"] = bad["sites"][0]["router"]
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_duplicate_subnet_name_inside_a_site_is_rejected(self):
        bad = clone(org("org_medium"))
        bad["sites"][0]["subnets"][1]["name"] = bad["sites"][0]["subnets"][0]["name"]
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_same_subnet_name_in_different_sites_is_fine(self):
        # "Staff" exists in several sites of org_medium and must stay legal.
        validate_input_semantics(org("org_medium"))

    def test_link_to_unknown_site_is_rejected(self):
        bad = clone(org("org_small"))
        bad["links"][0]["b"] = "Nowhere"
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_link_from_a_site_to_itself_is_rejected(self):
        bad = clone(org("org_small"))
        bad["links"][0]["b"] = bad["links"][0]["a"]
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_duplicate_link_in_either_direction_is_rejected(self):
        bad = clone(org("org_small"))
        bad["links"].append({"name": "again", "a": bad["links"][0]["b"], "b": bad["links"][0]["a"]})
        with self.assertRaises(ValueError):
            validate_input_semantics(bad)

    def test_disconnected_site_is_rejected(self):
        bad = clone(org("org_medium"))
        bad["links"] = bad["links"][:1]              # Branch2 is now unreachable
        with self.assertRaisesRegex(ValueError, "(?i)connect|isolat|reach"):
            validate_input_semantics(bad)

    def test_smallest_valid_input_already_meets_the_baseline(self):
        smallest = {
            "organization": "minimum",
            "ipv4_block": "10.0.0.0/24",
            "ipv6_prefix": "2001:db8::/48",
            "sites": [
                {"name": "A", "router": "R1", "subnets": [{"name": "L", "hosts": 1, "growth_pct": 0}]},
                {"name": "B", "router": "R2", "subnets": [{"name": "L", "hosts": 1, "growth_pct": 0}]},
            ],
            "links": [{"name": "A-B", "a": "A", "b": "B"}],
        }
        validate_structure(smallest, "input")
        validate_input_semantics(smallest)
        total = sum(len(s["subnets"]) for s in smallest["sites"]) + len(smallest["links"])
        self.assertEqual(total, 3)
        # Why rule 7 can never fail once the structure check passes: the schema forces at least
        # 2 sites, at least 1 LAN per site and at least 1 link, so the smallest valid input
        # already has 2 routers and 2 + 1 = 3 subnets. The rule is a safety net, not a filter.


if __name__ == "__main__":
    unittest.main()