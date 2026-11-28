"""Tests for planner/runlab.py. Docker, sudo and waiting are all faked."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.helpers import DATA
from planner.runlab import run_lab


class Recorder:
    """A fake subprocess.run that records every command and can be told which ones fail."""
    def __init__(self, fail=lambda cmd: False):
        self.calls, self.fail = [], fail

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return SimpleNamespace(returncode=1 if self.fail(cmd) else 0, stdout="ok\n", stderr="")

    def clab(self, verb):
        return [c for c in self.calls if c[:2] == ["sudo", "containerlab"] and c[2] == verb]


def run(recorder, **kwargs):
    sleeps = []
    with tempfile.TemporaryDirectory() as d:
        try:
            summary = run_lab(DATA / "org_small.json", "small", evidence_root=f"{d}/evidence", build_root=d,
                              runner=recorder, sleeper=sleeps.append, log=lambda m: None, **kwargs)
            files = sorted(p.name for p in (Path(d) / "evidence" / "small").iterdir())
            summary_file = json.loads((Path(d) / "evidence" / "small" / "summary.json").read_text())
        except RuntimeError as exc:
            return exc, sleeps, None, None
    return summary, sleeps, files, summary_file


class TestRunLab(unittest.TestCase):
    def test_happy_path_deploys_tests_and_destroys(self):
        rec = Recorder()
        summary, sleeps, files, saved = run(rec, wait=45)
        self.assertEqual(summary["pass_rate"], 100.0)
        self.assertEqual(summary["pings"], 12)
        self.assertEqual(summary["attempts"], 1)
        self.assertEqual(sleeps, [45])
        self.assertEqual(len(rec.clab("deploy")), 1)
        self.assertEqual(len(rec.clab("destroy")), 1)
        self.assertEqual(rec.calls[0][2], "deploy")           # first thing it does
        self.assertEqual(rec.calls[-1][2], "destroy")         # last thing it does
        self.assertEqual(saved, summary)

    def test_results_and_evidence_are_saved(self):
        _, _, files, _ = run(Recorder())
        for name in ("plan.json", "results.csv", "summary.json"):
            self.assertIn(name, files)
        self.assertIn("R1_ip_route.txt", files)

    def test_failed_pings_are_retried_once_then_reported(self):
        rec = Recorder(fail=lambda c: "ping" in c and "-6" in c)
        summary, sleeps, _, _ = run(rec, wait=10, retry_wait=7)
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(sleeps, [10, 7])
        self.assertEqual(summary["pass_rate"], 50.0)
        self.assertEqual(len(rec.clab("destroy")), 1)         # still cleans up

    def test_lab_is_destroyed_even_when_deploy_fails(self):
        rec = Recorder(fail=lambda c: c[:3] == ["sudo", "containerlab", "deploy"])
        error, *_ = run(rec)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(len(rec.clab("destroy")), 1)

    def test_host_setup_failure_stops_the_run_and_cleans_up(self):
        rec = Recorder(fail=lambda c: c[:2] == ["docker", "exec"] and "addr" in c)
        error, *_ = run(rec)
        self.assertIsInstance(error, RuntimeError)
        self.assertIn("host setup failed", str(error))
        self.assertEqual(len(rec.clab("destroy")), 1)

    def test_keep_leaves_the_lab_running(self):
        rec = Recorder()
        run(rec, keep=True)
        self.assertEqual(rec.clab("destroy"), [])

    def test_bad_input_is_rejected_before_anything_is_deployed(self):
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps({"organization": "x"}))
            with self.assertRaises(ValueError):
                run_lab(bad, "bad", evidence_root=d, build_root=d, runner=rec, sleeper=lambda s: None,
                        log=lambda m: None)
        self.assertEqual(rec.calls, [])


if __name__ == "__main__":
    unittest.main()
