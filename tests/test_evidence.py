"""Tests for planner/evidence.py. Docker is faked, so these run anywhere."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.helpers import plan
from planner.evidence import collect_evidence, evidence_commands


def fake(returncode=0, stdout="output\n", stderr=""):
    return lambda cmd, **kw: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.commands = evidence_commands(plan(), "lab1")
        self.names = [name for name, _ in self.commands]

    def test_four_vtysh_files_per_router(self):
        for router in ("R1", "R2"):
            for suffix in ("ip_route", "ipv6_route", "ospf_neighbors", "ospf6_neighbors"):
                self.assertIn(f"{router}_{suffix}.txt", self.names)

    def test_traceroutes_go_from_the_first_host_to_a_host_on_another_site(self):
        # mini plan: sites A (two LANs) and B (one LAN) -> exactly one remote target
        traces = [n for n in self.names if n.startswith("traceroute_")]
        self.assertEqual(sorted(traces), ["traceroute_H-A-LAN1_to_H-B-LAN3_ipv4.txt",
                                          "traceroute_H-A-LAN1_to_H-B-LAN3_ipv6.txt"])

    def test_commands_target_the_lab_containers_and_addresses(self):
        by_name = dict(self.commands)
        self.assertEqual(by_name["R1_ip_route.txt"],
                         ["docker", "exec", "clab-lab1-R1", "vtysh", "-c", "show ip route"])
        self.assertEqual(by_name["traceroute_H-A-LAN1_to_H-B-LAN3_ipv4.txt"],
                         ["docker", "exec", "clab-lab1-H-A-LAN1", "traceroute", "-n", "10.10.0.194"])
        self.assertIn("-6", by_name["traceroute_H-A-LAN1_to_H-B-LAN3_ipv6.txt"])

    def test_three_sites_add_a_branch_to_branch_trace(self):
        from planner.allocator import allocate
        from planner.validate import load_json
        from tests.helpers import DATA
        medium = allocate(load_json(DATA / "org_medium.json"))
        names = [n for n, _ in evidence_commands(medium, "lab1")]
        traces = [n for n in names if n.startswith("traceroute_")]
        self.assertEqual(len(traces), 6)       # 3 site pairs x IPv4 and IPv6

    def test_file_names_are_unique(self):
        self.assertEqual(len(self.names), len(set(self.names)))


class TestCollect(unittest.TestCase):
    def test_saves_every_output_and_the_plan(self):
        with tempfile.TemporaryDirectory() as d:
            results = collect_evidence(plan(), d, "lab1", runner=fake())
            self.assertTrue(all(r["ok"] for r in results))
            self.assertEqual((Path(d) / "R1_ip_route.txt").read_text(), "output\n")
            self.assertEqual(json.loads((Path(d) / "plan.json").read_text()), plan())
            self.assertEqual(len(results), 2 * 4 + 2)

    def test_failures_are_reported_and_marked_in_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            results = collect_evidence(plan(), d, "lab1",
                                       runner=fake(returncode=1, stdout="", stderr="No such container: x\n"))
            self.assertTrue(all(not r["ok"] for r in results))
            self.assertEqual(results[0]["detail"], "No such container: x")
            self.assertIn("[command failed]", (Path(d) / "R1_ip_route.txt").read_text())


if __name__ == "__main__":
    unittest.main()
