"""Tests for planner/pingmatrix.py. Docker is faked, so these run anywhere."""
import csv
import tempfile
import time
import unittest
from types import SimpleNamespace

from tests.helpers import plan
from planner.configgen import build_model
from planner.pingmatrix import (build_ping_matrix, pass_rate, ping_command, run_ping_matrix,
                                write_csv)


def fake_runner(fail_when=lambda cmd: False):
    """Pretend to be subprocess.run: returncode 1 when fail_when(cmd) is true, otherwise 0."""
    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=1 if fail_when(cmd) else 0)
    return run


class TestMatrix(unittest.TestCase):
    def test_size_is_hosts_times_hosts_minus_one_times_two_families(self):
        hosts = len(build_model(plan())["hosts"])                    # 3
        self.assertEqual(len(build_ping_matrix(plan())), hosts * (hosts - 1) * 2)   # 12

    def test_no_host_pings_itself(self):
        for entry in build_ping_matrix(plan()):
            self.assertNotEqual(entry["src"], entry["dst"])

    def test_every_pair_is_tested_in_both_families(self):
        pairs = {}
        for e in build_ping_matrix(plan()):
            pairs.setdefault((e["src"], e["dst"]), set()).add(e["family"])
        for families in pairs.values():
            self.assertEqual(families, {"ipv4", "ipv6"})

    def test_targets_are_the_destination_hosts_addresses(self):
        hosts = {h["name"]: h for h in build_model(plan())["hosts"]}
        for e in build_ping_matrix(plan()):
            expected = hosts[e["dst"]]["ipv4" if e["family"] == "ipv4" else "ipv6"]
            self.assertEqual(e["target"], expected)


class TestCommand(unittest.TestCase):
    def test_ipv4_command(self):
        entry = {"src": "H-A-LAN1", "dst": "H-B-LAN3", "family": "ipv4", "target": "10.10.0.194"}
        cmd = ping_command(entry, "lab1")
        self.assertEqual(cmd[:3], ["docker", "exec", "clab-lab1-H-A-LAN1"])
        self.assertIn("-4", cmd)
        self.assertEqual(cmd[-1], "10.10.0.194")

    def test_ipv6_command_uses_the_6_flag(self):
        entry = {"src": "H-A-LAN1", "dst": "H-B-LAN3", "family": "ipv6", "target": "2001:db8::2"}
        self.assertIn("-6", ping_command(entry, "lab1"))


class TestRun(unittest.TestCase):
    def test_all_pass_gives_100_percent(self):
        results = run_ping_matrix(plan(), "lab1", runner=fake_runner())
        self.assertEqual(len(results), 12)
        self.assertEqual(pass_rate(results), 100.0)

    def test_failures_lower_the_pass_rate_and_name_the_failing_pair(self):
        results = run_ping_matrix(plan(), "lab1", runner=fake_runner(lambda c: "-6" in c))
        self.assertEqual(pass_rate(results), 50.0)               # every IPv6 test fails
        self.assertTrue(all(not r["passed"] for r in results if r["family"] == "ipv6"))
        self.assertTrue(all(r["passed"] for r in results if r["family"] == "ipv4"))

    def test_failed_ping_keeps_the_reason(self):
        def runner(cmd, **kwargs):
            return SimpleNamespace(returncode=2, stdout="", stderr="ping: connect: Network is unreachable\n")
        results = run_ping_matrix(plan(), "lab1", runner=runner)
        self.assertTrue(all(r["detail"] == "ping: connect: Network is unreachable" for r in results))

    def test_passed_ping_has_no_detail(self):
        results = run_ping_matrix(plan(), "lab1", runner=fake_runner())
        self.assertTrue(all(r["detail"] == "" for r in results))

    def test_progress_is_reported_once_per_ping(self):
        seen = []
        run_ping_matrix(plan(), "lab1", runner=fake_runner(), progress=lambda d, t, r: seen.append((d, t)))
        self.assertEqual([d for d, _ in seen], list(range(1, 13)))
        self.assertTrue(all(t == 12 for _, t in seen))

    def test_results_keep_the_matrix_order_when_run_in_parallel(self):
        results = run_ping_matrix(plan(), "lab1", runner=fake_runner(), workers=8)
        expected = [(e["src"], e["dst"], e["family"]) for e in build_ping_matrix(plan())]
        self.assertEqual([(r["src"], r["dst"], r["family"]) for r in results], expected)

    def test_a_single_worker_gives_the_same_answer(self):
        one = run_ping_matrix(plan(), "lab1", runner=fake_runner(), workers=1)
        many = run_ping_matrix(plan(), "lab1", runner=fake_runner(), workers=6)
        self.assertEqual(one, many)

    def test_pings_really_run_at_the_same_time(self):
        def slow(cmd, **kwargs):
            time.sleep(0.1)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        started = time.perf_counter()
        run_ping_matrix(plan(), "lab1", runner=slow, workers=6)      # 12 pings x 0.1 s = 1.2 s one at a time
        self.assertLess(time.perf_counter() - started, 0.8)

    def test_pass_rate_of_nothing_is_zero(self):
        self.assertEqual(pass_rate([]), 0.0)

    def test_csv_round_trip(self):
        results = run_ping_matrix(plan(), "lab1", runner=fake_runner())
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/results.csv"
            write_csv(results, path)
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["passed"], "True")
        self.assertIn("detail", rows[0])


if __name__ == "__main__":
    unittest.main()
