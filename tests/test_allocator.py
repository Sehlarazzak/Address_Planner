import copy
import ipaddress
import unittest
from pathlib import Path

from planner.allocator import allocate
from planner.validate import load_json, validate_plan_semantics, validate_structure
from planner.vlsm import required_hosts, required_prefix

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class TestAllocator(unittest.TestCase):
    def test_org_small_known_cidrs_and_routers(self):
        data = load_json(DATA_DIR / "org_small.json")
        plan = allocate(data)

        validate_structure(plan, "plan")
        validate_plan_semantics(plan)

        router_names = {r["name"] for r in plan["routers"]}
        self.assertEqual(router_names, {"R1", "R2"})

        by_id = {s["id"]: s for s in plan["subnets"]}
        # Verify expected LAN & link CIDRs for org_small
        for site in data["sites"]:
            s_name = site["name"]
            s_block = ipaddress.IPv4Network(plan["ipv4_sites"][s_name], strict=True)
            for lan in site["subnets"]:
                sid = f"{s_name}:{lan['name']}"
                sub = by_id[sid]
                needed = required_hosts(lan["hosts"], lan["growth_pct"])
                expected_plen = required_prefix(needed)
                self.assertEqual(sub["ipv4_prefixlen"], expected_plen)
                self.assertTrue(ipaddress.IPv4Network(sub["ipv4_cidr"], strict=True).subnet_of(s_block))

    def test_all_sample_orgs_pass_structure_and_semantics(self):
        sample_files = sorted(DATA_DIR.glob("org_*.json"))
        self.assertGreater(len(sample_files), 0)

        for path in sample_files:
            with self.subTest(sample=path.name):
                data = load_json(path)
                plan = allocate(data)
                validate_structure(plan, "plan")
                validate_plan_semantics(plan)
                self.assertIn("metrics", plan)
                self.assertIn("allocation_time_ms", plan["metrics"])
                self.assertGreater(plan["metrics"]["allocation_time_ms"], 0)

    def test_every_subnet_is_smallest_prefix_that_fits(self):
        data = load_json(DATA_DIR / "org_medium.json")
        plan = allocate(data)

        for sub in plan["subnets"]:
            plen = sub["ipv4_prefixlen"]
            needed = sub["hosts_required"]
            self.assertGreaterEqual((1 << (32 - plen)) - 2, needed)
            if plen < 30:
                smaller_usable = (1 << (32 - (plen + 1))) - 2
                self.assertLess(smaller_usable, needed)

    def test_largest_first_within_each_site_and_site_blocks_non_overlapping(self):
        data = load_json(DATA_DIR / "org_large.json")
        plan = allocate(data)

        site_nets = {
            name: ipaddress.IPv4Network(cidr, strict=True)
            for name, cidr in plan["ipv4_sites"].items()
        }
        net_list = list(site_nets.values())
        for i, n1 in enumerate(net_list):
            for n2 in net_list[i + 1 :]:
                self.assertFalse(n1.overlaps(n2))

        for site_name, s_block in site_nets.items():
            site_lans = [s for s in plan["subnets"] if s["type"] == "lan" and s["site"] == site_name]
            prefixes = [s["ipv4_prefixlen"] for s in site_lans]
            self.assertEqual(prefixes, sorted(prefixes))
            for s in site_lans:
                self.assertTrue(ipaddress.IPv4Network(s["ipv4_cidr"], strict=True).subnet_of(s_block))

        if "ipv4_link_block" in plan:
            link_block = ipaddress.IPv4Network(plan["ipv4_link_block"], strict=True)
            for s in plan["subnets"]:
                if s["type"] == "link":
                    self.assertTrue(ipaddress.IPv4Network(s["ipv4_cidr"], strict=True).subnet_of(link_block))

    def test_small_ipv4_block_raises_exhausted(self):
        tiny = copy.deepcopy(load_json(DATA_DIR / "org_small.json"))
        tiny["ipv4_block"] = "10.10.0.0/29"
        with self.assertRaisesRegex(ValueError, "(?i)exhausted"):
            allocate(tiny)


if __name__ == "__main__":
    unittest.main()