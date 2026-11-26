"""Tests for planner/configgen.py: plan -> FRR configs + containerlab topology."""
import ipaddress
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.helpers import clone, plan
from planner.configgen import build_model, default_lab_name, render_all, slug


class TestBuildModel(unittest.TestCase):
    def setUp(self):
        self.model = build_model(plan())

    def test_counts_for_the_mini_plan(self):
        self.assertEqual(len(self.model["routers"]), 2)
        self.assertEqual(len(self.model["hosts"]), 3)       # one test host per LAN
        self.assertEqual(len(self.model["links"]), 4)       # 3 host cables + 1 router-router link

    def test_router_ids_are_unique(self):
        ids = [r["router_id"] for r in self.model["routers"]]
        self.assertEqual(len(set(ids)), len(ids))

    def test_host_addresses_are_inside_the_lan_and_not_the_gateway(self):
        for host in self.model["hosts"]:
            net4 = ipaddress.IPv4Interface(host["ipv4_cidr"]).network
            net6 = ipaddress.IPv6Interface(host["ipv6_cidr"]).network
            a4, a6 = ipaddress.IPv4Address(host["ipv4"]), ipaddress.IPv6Address(host["ipv6"])
            self.assertIn(a4, net4)
            self.assertIn(a6, net6)
            self.assertNotIn(a4, (net4.network_address, net4.broadcast_address))
            self.assertNotEqual(str(a4), host["gw4"])
            self.assertNotEqual(str(a6), host["gw6"])

    def test_host_skips_the_gateway_when_gateway_is_dot_2(self):
        moved = clone(plan())
        moved["routers"][0]["interfaces"][0]["ipv4"] = "10.10.0.2"   # R1 eth1 gateway
        host = next(h for h in build_model(moved)["hosts"] if h["subnet_id"] == "A-LAN1")
        self.assertEqual(host["ipv4"], "10.10.0.1")

    def test_every_router_interface_is_cabled_exactly_once(self):
        endpoints = [e for link in self.model["links"] for e in link]
        self.assertEqual(len(endpoints), len(set(endpoints)))
        for router in self.model["routers"]:
            for iface in router["interfaces"]:
                self.assertIn(f"{router['name']}:{iface['name']}", endpoints)

    def test_every_endpoint_names_a_real_node(self):
        nodes = {r["name"] for r in self.model["routers"]} | {h["name"] for h in self.model["hosts"]}
        for link in self.model["links"]:
            for endpoint in link:
                self.assertIn(endpoint.split(":")[0], nodes)

    def test_link_with_one_end_is_rejected(self):
        bad = clone(plan())
        bad["routers"][1]["interfaces"] = [i for i in bad["routers"][1]["interfaces"]
                                           if i["subnet_id"] != "A-B"]
        with self.assertRaises(ValueError):
            build_model(bad)


class TestHelpers(unittest.TestCase):
    def test_slug_keeps_only_safe_characters(self):
        self.assertEqual(slug("A LAN 1!"), "A-LAN-1")
        self.assertEqual(slug("A-LAN1"), "A-LAN1")

    def test_default_lab_name_is_safe_and_short(self):
        name = default_lab_name(plan())
        self.assertRegex(name, r"^[a-z0-9-]+$")
        self.assertLessEqual(len(name), 30)


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.written = render_all(plan(), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_expected_files_exist(self):
        for router in ("R1", "R2"):
            self.assertTrue((self.out / "configs" / router / "frr.conf").is_file())
            self.assertTrue((self.out / "configs" / router / "daemons").is_file())
        self.assertTrue((self.out / "topology.clab.yml").is_file())
        self.assertEqual(len(self.written), 7)       # 2 routers x 3 files + topology

    def test_frr_conf_has_the_plan_addresses(self):
        text = (self.out / "configs" / "R1" / "frr.conf").read_text()
        self.assertIn("hostname R1", text)
        self.assertIn("ip address 10.10.0.1/25", text)
        self.assertIn("ipv6 address 2001:db8:1000:1000::1/64", text)
        self.assertIn("ip address 10.10.0.225/30", text)
        self.assertIn("router ospf6", text)

    def test_lan_interfaces_are_passive_and_links_are_point_to_point(self):
        text = (self.out / "configs" / "R1" / "frr.conf").read_text()
        stanzas = {s.split("\n")[0].strip(): s for s in text.split("interface ")[1:]}
        self.assertIn("ip ospf passive", stanzas["eth1"])
        self.assertNotIn("point-to-point", stanzas["eth1"])
        self.assertIn("ip ospf network point-to-point", stanzas["eth3"])
        self.assertNotIn("passive", stanzas["eth3"])

    def test_frr_conf_turns_forwarding_on_for_both_families(self):
        # The first deployment showed zebra defaulting to "no ipv6 forwarding", which blocked all routing.
        text = (self.out / "configs" / "R1" / "frr.conf").read_text()
        self.assertIn("\nip forwarding\n", text)
        self.assertIn("\nipv6 forwarding\n", text)

    def test_vtysh_conf_exists_and_is_mounted(self):
        self.assertTrue((self.out / "configs" / "R1" / "vtysh.conf").is_file())
        data = yaml.safe_load((self.out / "topology.clab.yml").read_text())
        self.assertIn("configs/R1/vtysh.conf:/etc/frr/vtysh.conf", data["topology"]["nodes"]["R1"]["binds"])

    def test_hosts_are_configured_by_labsetup_not_by_containerlab_exec(self):
        data = yaml.safe_load((self.out / "topology.clab.yml").read_text())
        for name in ("H-A-LAN1", "H-A-LAN2", "H-B-LAN3"):
            self.assertNotIn("exec", data["topology"]["nodes"][name])

    def test_daemons_enable_ospf_for_both_families(self):
        text = (self.out / "configs" / "R1" / "daemons").read_text()
        self.assertIn("ospfd=yes", text)
        self.assertIn("ospf6d=yes", text)
        self.assertIn("zebra=yes", text)

    def test_topology_is_valid_yaml_with_all_nodes_and_links(self):
        data = yaml.safe_load((self.out / "topology.clab.yml").read_text())
        nodes = data["topology"]["nodes"]
        self.assertEqual(set(nodes), {"R1", "R2", "H-A-LAN1", "H-A-LAN2", "H-B-LAN3"})
        self.assertEqual(len(data["topology"]["links"]), 4)
        self.assertIn("configs/R1/frr.conf:/etc/frr/frr.conf", nodes["R1"]["binds"])

    def test_images_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            render_all(plan(), d, frr_image="example/frr:1", host_image="example/host:2")
            text = (Path(d) / "topology.clab.yml").read_text()
        self.assertIn("image: example/frr:1", text)
        self.assertIn("image: example/host:2", text)


if __name__ == "__main__":
    unittest.main()
