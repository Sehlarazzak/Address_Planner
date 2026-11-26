"""Tests for planner/labsetup.py. Docker is faked, so these run anywhere."""
import unittest
from types import SimpleNamespace

from tests.helpers import plan
from planner.labsetup import host_setup_commands, run_host_setup


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.commands = host_setup_commands(plan(), "lab1")

    def test_four_commands_per_host(self):
        self.assertEqual(len(self.commands), 3 * 4)      # 3 LAN hosts

    def test_commands_target_the_right_container(self):
        first = self.commands[0]
        self.assertEqual(first[:3], ["docker", "exec", "clab-lab1-H-A-LAN1"])

    def test_first_host_gets_the_expected_addresses_and_gateways(self):
        joined = [" ".join(c) for c in self.commands[:4]]
        self.assertIn("ip addr replace 10.10.0.2/25 dev eth1", joined[0])
        self.assertIn("ip -6 addr replace 2001:db8:1000:1000::2/64 dev eth1", joined[1])
        self.assertIn("ip route replace default via 10.10.0.1", joined[2])
        self.assertIn("ip -6 route replace default via 2001:db8:1000:1000::1", joined[3])

    def test_uses_replace_so_rerunning_never_fails(self):
        for cmd in self.commands:
            self.assertIn("replace", cmd)
            self.assertNotIn("add", cmd)


class TestRun(unittest.TestCase):
    def test_no_failures_when_docker_succeeds(self):
        ok = lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        self.assertEqual(run_host_setup(plan(), "lab1", runner=ok), [])

    def test_failures_are_reported_with_the_reason(self):
        def bad(cmd, **kw):
            return SimpleNamespace(returncode=2, stdout="", stderr="Cannot find device \"eth1\"\n")
        failures = run_host_setup(plan(), "lab1", runner=bad)
        self.assertEqual(len(failures), 12)
        self.assertEqual(failures[0]["detail"], 'Cannot find device "eth1"')
        self.assertIn("docker exec clab-lab1-H-A-LAN1", failures[0]["command"])


if __name__ == "__main__":
    unittest.main()
