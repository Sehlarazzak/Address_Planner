"""IPv6 allocator tests (Sehla). They FAIL until planner/ipv6_alloc.py is implemented."""
import unittest
from ipaddress import IPv6Network

from tests.helpers import ROOT, org  # noqa: F401  (ROOT sets sys.path)
from planner.ipv6_alloc import allocate_64s, carve_site_blocks, interface_address

PREFIX = "2001:db8:1000::/48"
SITES = ["HQ", "Site2", "Site3", "Site4"]


class TestCarveSiteBlocks(unittest.TestCase):
    def test_sites_get_one_52_each_numbered_from_1(self):
        blocks, _ = carve_site_blocks(PREFIX, SITES)
        self.assertEqual(blocks["HQ"], IPv6Network("2001:db8:1000:1000::/52"))
        self.assertEqual(blocks["Site2"], IPv6Network("2001:db8:1000:2000::/52"))
        self.assertEqual(blocks["Site3"], IPv6Network("2001:db8:1000:3000::/52"))
        self.assertEqual(blocks["Site4"], IPv6Network("2001:db8:1000:4000::/52"))

    def test_link_block_is_f000_52(self):
        _, links = carve_site_blocks(PREFIX, SITES)
        self.assertEqual(links, IPv6Network("2001:db8:1000:f000::/52"))

    def test_blocks_never_overlap_and_stay_inside_the_48(self):
        blocks, links = carve_site_blocks(PREFIX, SITES)
        everything = list(blocks.values()) + [links]
        parent = IPv6Network(PREFIX)
        for i, a in enumerate(everything):
            self.assertTrue(a.subnet_of(parent))
            for b in everything[i + 1:]:
                self.assertFalse(a.overlaps(b))

    def test_site_order_follows_input_order(self):
        blocks, _ = carve_site_blocks(PREFIX, ["Z", "A"])
        self.assertEqual(blocks["Z"], IPv6Network("2001:db8:1000:1000::/52"))
        self.assertEqual(blocks["A"], IPv6Network("2001:db8:1000:2000::/52"))

    def test_fourteen_sites_is_the_maximum(self):
        names = [f"s{i}" for i in range(14)]
        blocks, _ = carve_site_blocks(PREFIX, names)
        self.assertEqual(blocks["s13"], IPv6Network("2001:db8:1000:e000::/52"))
        with self.assertRaises(ValueError):
            carve_site_blocks(PREFIX, names + ["one-too-many"])

    def test_prefix_must_be_a_slash_48(self):
        with self.assertRaises(ValueError):
            carve_site_blocks("2001:db8:1000::/56", SITES)

    def test_prefix_must_be_strict_and_ipv6(self):
        with self.assertRaises(ValueError):
            carve_site_blocks("2001:db8:1000:1::/48", SITES)      # host bits set
        with self.assertRaises(ValueError):
            carve_site_blocks("10.0.0.0/8", SITES)

    def test_duplicate_site_names_are_rejected(self):
        with self.assertRaises(ValueError):
            carve_site_blocks(PREFIX, ["HQ", "HQ"])


class TestAllocate64s(unittest.TestCase):
    BLOCK = IPv6Network("2001:db8:1000:1000::/52")

    def test_first_three_are_consecutive(self):
        got = allocate_64s(self.BLOCK, 3)
        self.assertEqual([str(n) for n in got], [
            "2001:db8:1000:1000::/64", "2001:db8:1000:1001::/64", "2001:db8:1000:1002::/64"])

    def test_zero_gives_empty_list(self):
        self.assertEqual(allocate_64s(self.BLOCK, 0), [])

    def test_a_52_holds_exactly_4096(self):
        self.assertEqual(len(allocate_64s(self.BLOCK, 4096)), 4096)
        with self.assertRaises(ValueError):
            allocate_64s(self.BLOCK, 4097)

    def test_negative_count_is_rejected(self):
        with self.assertRaises(ValueError):
            allocate_64s(self.BLOCK, -1)

    def test_block_longer_than_64_is_rejected(self):
        with self.assertRaises(ValueError):
            allocate_64s(IPv6Network("2001:db8:1000:1000::/80"), 1)

    def test_every_result_is_a_64_inside_the_block(self):
        for n in allocate_64s(self.BLOCK, 50):
            self.assertEqual(n.prefixlen, 64)
            self.assertTrue(n.subnet_of(self.BLOCK))


class TestInterfaceAddress(unittest.TestCase):
    NET = IPv6Network("2001:db8:1000:1000::/64")

    def test_gateway_is_index_1(self):
        self.assertEqual(interface_address(self.NET, 1), "2001:db8:1000:1000::1")

    def test_second_link_end_is_index_2(self):
        self.assertEqual(interface_address(self.NET, 2), "2001:db8:1000:1000::2")

    def test_result_has_no_prefix_length(self):
        self.assertNotIn("/", interface_address(self.NET, 1))

    def test_index_zero_is_rejected(self):
        with self.assertRaises(ValueError):
            interface_address(self.NET, 0)

    def test_index_outside_subnet_is_rejected(self):
        with self.assertRaises(ValueError):
            interface_address(self.NET, 2 ** 64)

    def test_end_to_end_with_the_sample_org(self):
        data = org("org_sample_15")
        blocks, link_block = carve_site_blocks(
            data["ipv6_prefix"], [site["name"] for site in data["sites"]])
        allocated = []
        for site in data["sites"]:
            block = blocks[site["name"]]
            nets = allocate_64s(block, len(site["subnets"]))
            for net in nets:
                self.assertTrue(net.subnet_of(block))      # LAN stays inside its site /52
            allocated += nets
        link_nets = allocate_64s(link_block, len(data["links"]))
        for net in link_nets:
            self.assertTrue(net.subnet_of(link_block))     # links stay inside the link block
        allocated += link_nets
        self.assertEqual(len(allocated), 15)               # 12 LANs + 3 links
        self.assertEqual(len(set(allocated)), 15)          # all 15 /64s are distinct


if __name__ == "__main__":
    unittest.main()