"""Tests for planner/impair.py. Docker, sudo, tc and waiting are all faked."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.helpers import DATA
from planner.allocator import allocate
from planner.impair import (CONDITIONS, check_netem, expected_loss_pct, expected_rtt_ms, markdown_table,
                            netem_apply_command, netem_clear_command, parse_ping_output, pick_link,
                            pick_test_pair, run_impairments, summarize)
from planner.validate import load_json

GOOD = """PING 10.10.0.194 (10.10.0.194) 56(84) bytes of data.

--- 10.10.0.194 ping statistics ---
100 packets transmitted, 98 received, 2% packet loss, time 20300ms
rtt min/avg/max/mdev = 100.123/101.456/110.789/2.345 ms, pipe 2
"""
ALL_LOST = """--- 10.10.0.194 ping statistics ---
100 packets transmitted, 0 received, +100 errors, 100% packet loss, time 20000ms
"""


class TestParse(unittest.TestCase):
    def test_normal_output(self):
        r = parse_ping_output(GOOD)
        self.assertEqual((r["sent"], r["received"], r["loss_pct"]), (100, 98, 2.0))
        self.assertEqual((r["rtt_min"], r["rtt_avg"], r["rtt_max"], r["rtt_mdev"]), (100.123, 101.456, 110.789, 2.345))

    def test_everything_lost_has_no_rtt(self):
        r = parse_ping_output(ALL_LOST)
        self.assertEqual((r["received"], r["loss_pct"], r["rtt_avg"]), (0, 100.0, None))

    def test_garbage_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_ping_output("ping: unknown host")


class TestExpectations(unittest.TestCase):
    def test_rtt_is_twice_the_per_direction_delay(self):
        self.assertEqual(expected_rtt_ms(50), 100.0)
        self.assertEqual(expected_rtt_ms(100), 200.0)

    def test_round_trip_loss_is_one_minus_both_directions_surviving(self):
        self.assertAlmostEqual(expected_loss_pct(2.0), 3.96)
        self.assertAlmostEqual(expected_loss_pct(5.0), 9.75)
        self.assertEqual(expected_loss_pct(0.0), 0.0)

    def test_conditions_match_the_proposal(self):
        self.assertEqual(CONDITIONS, [("C1", 0, 0.0), ("C2", 50, 2.0), ("C3", 100, 5.0)])


class TestCommands(unittest.TestCase):
    def test_tc_commands(self):
        self.assertEqual(netem_apply_command("tc", "c1", "eth3", 50, 2.0),
                         ["docker", "exec", "c1", "tc", "qdisc", "replace", "dev", "eth3", "root", "netem",
                          "delay", "50ms", "loss", "2.0%"])
        self.assertEqual(netem_clear_command("tc", "c1", "eth3"),
                         ["docker", "exec", "c1", "tc", "qdisc", "del", "dev", "eth3", "root"])

    def test_containerlab_commands(self):
        apply = netem_apply_command("clab", "c1", "eth3", 100, 5.0)
        self.assertEqual(apply[:4], ["sudo", "containerlab", "tools", "netem"])
        self.assertIn("--delay", apply)
        self.assertIn("100ms", apply)


class TestPicking(unittest.TestCase):
    def test_link_and_pair_for_the_small_org(self):
        plan = allocate(load_json(DATA / "org_small.json"))
        link_id, ends = pick_link(plan)
        self.assertEqual(len(ends), 2)
        src, dst = pick_test_pair(plan)
        self.assertNotEqual(src["name"], dst["name"])
        sites = {s["id"]: s["site"] for s in plan["subnets"]}
        self.assertEqual({sites[src["subnet_id"]], sites[dst["subnet_id"]]}, {ends[0][2], ends[1][2]})


class TestSummary(unittest.TestCase):
    def test_mean_and_sample_stdev_across_runs(self):
        rows = [{"condition": "C2", "family": "ipv4", "loss_pct_measured": x, "rtt_avg": y}
                for x, y in ((2.0, 100.0), (4.0, 102.0), (6.0, 104.0))]
        s = summarize(rows)[0]
        self.assertEqual((s["loss_mean"], s["loss_stdev"]), (4.0, 2.0))
        self.assertEqual((s["rtt_mean"], s["rtt_stdev"]), (102.0, 2.0))
        self.assertEqual(s["expected_rtt_ms"], 100.0)
        self.assertIn("C2", markdown_table([s]))


class Fake:
    def __init__(self, fail=lambda cmd: False, ping_out=GOOD):
        self.calls, self.fail, self.ping_out = [], fail, ping_out

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.ping_out if "ping" in cmd else ""
        return SimpleNamespace(returncode=1 if self.fail(cmd) else 0, stdout=out, stderr="nope" if self.fail(cmd) else "")


class TestCheck(unittest.TestCase):
    ENDS = [("r-A", "eth3", "A"), ("r-B", "eth2", "B")]

    def test_first_working_method_wins(self):
        self.assertEqual(check_netem("lab", self.ENDS, runner=Fake()), "tc")

    def test_falls_back_to_containerlab_when_tc_fails(self):
        rec = Fake(fail=lambda c: c[:2] == ["docker", "exec"])
        self.assertEqual(check_netem("lab", self.ENDS, runner=rec), "clab")

    def test_error_when_nothing_works(self):
        with self.assertRaises(RuntimeError):
            check_netem("lab", self.ENDS, runner=Fake(fail=lambda c: "netem" in c or "qdisc" in c))


class TestRun(unittest.TestCase):
    def go(self, rec, **kw):
        with tempfile.TemporaryDirectory() as d:
            result = run_impairments(DATA / "org_small.json", "small", evidence_root=f"{d}/e", build_root=d,
                                     runner=rec, sleeper=lambda s: None, log=lambda m: None, **kw)
            files = sorted(p.name for p in (Path(d) / "e" / "small_impairment").iterdir()) if not kw.get("check_only") else []
        return result, files

    def test_nine_runs_two_families_and_both_routers_are_impaired(self):
        rec = Fake()
        result, files = self.go(rec)
        self.assertEqual(len(result["rows"]), 3 * 3 * 2)
        applies = [c for c in rec.calls if "netem" in c and "delay" in c and "50ms" in c]
        self.assertEqual(len(applies), 3 * 2)                      # C2: 3 runs x 2 routers
        self.assertTrue({c[2] for c in applies} == {"clab-small-3-lans-2-routers-r-A", "clab-small-3-lans-2-routers-r-B"})
        for name in ("impairment_runs.csv", "impairment_summary.csv", "impairment_summary.md", "plan.json"):
            self.assertIn(name, files)

    def test_first_run_of_every_condition_is_captured(self):
        rec = Fake()
        _, files = self.go(rec)
        copies = [c for c in rec.calls if c[:2] == ["docker", "cp"]]
        self.assertEqual(len(copies), 3 * 2)                       # 3 conditions x 2 families, run 1 only
        for condition in ("C1", "C2", "C3"):
            for family in ("ipv4", "ipv6"):
                self.assertIn(f"{condition}_{family}_packets.txt", files)

    def test_capture_starts_before_the_ping_and_uses_the_right_filter(self):
        rec = Fake()
        self.go(rec)
        starts = [i for i, c in enumerate(rec.calls) if "-d" in c and "tcpdump" in " ".join(c)]
        pings = [i for i, c in enumerate(rec.calls) if "ping" in c]
        self.assertTrue(starts[0] < pings[0])
        text = [" ".join(rec.calls[i]) for i in starts]
        self.assertTrue(any(t.endswith("icmp") for t in text))
        self.assertTrue(any(t.endswith("icmp6") for t in text))

    def test_no_capture_option(self):
        rec = Fake()
        _, files = self.go(rec, capture=False)
        self.assertEqual([c for c in rec.calls if c[:2] == ["docker", "cp"]], [])
        self.assertNotIn("C2_ipv4_packets.txt", files)

    def test_missing_tcpdump_skips_captures_but_the_experiment_still_runs(self):
        rec = Fake(fail=lambda c: "--version" in c)
        result, files = self.go(rec)
        self.assertEqual(len(result["rows"]), 18)
        self.assertEqual([c for c in rec.calls if c[:2] == ["docker", "cp"]], [])

    def test_ping_uses_the_requested_count_and_interval(self):
        rec = Fake()
        self.go(rec, count=50, interval=0.5)
        pings = [c for c in rec.calls if "ping" in c]
        self.assertTrue(pings and all(c[c.index("-c") + 1] == "50" and c[c.index("-i") + 1] == "0.5" for c in pings))

    def test_lab_is_destroyed_at_the_end_and_conditions_are_cleared(self):
        rec = Fake()
        self.go(rec)
        self.assertEqual(rec.calls[-1][:4], ["sudo", "containerlab", "destroy", "-t"])
        self.assertIn("del", [c for c in rec.calls if "qdisc" in c][-1])

    def test_check_only_stops_before_the_experiments(self):
        rec = Fake()
        result, _ = self.go(rec, check_only=True)
        self.assertEqual(result["method"], "tc")
        self.assertEqual([c for c in rec.calls if "ping" in c], [])
        self.assertEqual(rec.calls[-1][2], "destroy")

    def test_destroys_the_lab_when_netem_is_unavailable(self):
        rec = Fake(fail=lambda c: "netem" in c or "qdisc" in c)
        with self.assertRaises(RuntimeError):
            self.go(rec)
        self.assertEqual(rec.calls[-1][2], "destroy")


if __name__ == "__main__":
    unittest.main()
