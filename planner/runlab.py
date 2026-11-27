"""One command per organization:

    allocate -> render -> deploy -> configure hosts -> wait for OSPF -> ping matrix -> evidence -> destroy

Everything is saved under evidence/<name>/ : plan.json, results.csv, summary.json and the router/traceroute files.
"""
import json
import subprocess
import time
from pathlib import Path

from planner import configgen, evidence, labsetup, pingmatrix
from planner.allocator import allocate
from planner.validate import (load_json, validate_input_semantics, validate_plan_semantics,
                              validate_structure)

CONTAINERLAB = ["sudo", "containerlab"]


def run_lab(input_path, name, wait=60, keep=False, workers=8, retry_wait=30,
            evidence_root="evidence", build_root=".",
            runner=subprocess.run, sleeper=time.sleep, log=print):
    """Run the whole chain for one organization and return a summary dictionary.

    The lab is destroyed at the end (also when something fails) unless keep=True.
    `runner`, `sleeper` and `log` are injectable so tests can run without Docker or waiting."""
    data = load_json(input_path)
    validate_structure(data, "input")
    validate_input_semantics(data)
    plan = allocate(data)
    validate_structure(plan, "plan")
    validate_plan_semantics(plan)

    lab = configgen.default_lab_name(plan)
    build_dir = Path(build_root) / f"build_{name}"
    out_dir = Path(evidence_root) / name
    topology = build_dir / "topology.clab.yml"
    configgen.render_all(plan, build_dir, lab)
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"[{name}] allocated {len(plan['subnets'])} subnets, rendered configs into {build_dir}")

    try:
        log(f"[{name}] deploying lab {lab} (this needs sudo)")
        if runner(CONTAINERLAB + ["deploy", "-t", str(topology)]).returncode != 0:
            raise RuntimeError("containerlab deploy failed")

        failures = labsetup.run_host_setup(plan, lab, runner=runner)
        if failures:
            raise RuntimeError(f"host setup failed: {failures[0]['command']} ({failures[0]['detail']})")
        log(f"[{name}] hosts configured; waiting {wait} s for OSPF to converge")
        sleeper(wait)

        def show(done, total, r):
            if not r["passed"]:
                log(f"[{name}] FAIL {r['src']} -> {r['dst']} ({r['family']}) {r['detail']}")

        started = time.perf_counter()
        results = pingmatrix.run_ping_matrix(plan, lab, runner=runner, workers=workers, progress=show)
        attempts = 1
        if retry_wait and any(not r["passed"] for r in results):
            log(f"[{name}] some pings failed; waiting {retry_wait} s and trying once more")
            sleeper(retry_wait)
            results = pingmatrix.run_ping_matrix(plan, lab, runner=runner, workers=workers, progress=show)
            attempts = 2
        ping_seconds = time.perf_counter() - started
        pingmatrix.write_csv(results, out_dir / "results.csv")

        saved = evidence.collect_evidence(plan, out_dir, lab, runner=runner)
        passed = sum(1 for r in results if r["passed"])
        summary = {
            "name": name,
            "organization": plan["organization"],
            "lab": lab,
            "routers": len(plan["routers"]),
            "hosts": len({r["src"] for r in results}),
            "pings": len(results),
            "passed": passed,
            "pass_rate": round(pingmatrix.pass_rate(results), 1),
            "attempts": attempts,
            "wait_seconds": wait,
            "ping_seconds": round(ping_seconds, 1),
            "allocation_time_ms": plan.get("metrics", {}).get("allocation_time_ms"),
            "evidence_files": sum(1 for r in saved if r["ok"]),
            "evidence_failures": [r["file"] for r in saved if not r["ok"]],
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        log(f"[{name}] pass rate {summary['pass_rate']}% ({passed}/{len(results)}), "
            f"{summary['evidence_files']} evidence files, saved in {out_dir}")
        return summary
    finally:
        if keep:
            log(f"[{name}] lab left running; remove it with: sudo containerlab destroy -t {topology} --cleanup")
        else:
            log(f"[{name}] destroying lab")
            runner(CONTAINERLAB + ["destroy", "-t", str(topology), "--cleanup"])
