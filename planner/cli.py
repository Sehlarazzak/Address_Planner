"""Command-line entry point.

    python -m planner.cli validate   --input data/org_small.json
    python -m planner.cli allocate   --input data/org_small.json --out plan.json
    python -m planner.cli render     --plan  data/plan_example_mini.json --out build
    python -m planner.cli configure  --plan  data/plan_example_mini.json        (after containerlab deploy)
    python -m planner.cli pingmatrix --plan  data/plan_example_mini.json [--dry-run] [--csv results.csv]
    python -m planner.cli evidence   --plan  data/plan_example_mini.json --out evidence/mini
    python -m planner.cli runlab     --input data/org_large.json            (the whole chain, one organization)
    python -m planner.cli impair     --input data/org_small.json            (delay/loss experiments C1-C3)
    python -m planner.cli report     [--out comparison_report.csv] [--runs 20]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from planner import compare, configgen, evidence, impair, labsetup, pingmatrix, runlab
from planner.allocator import allocate
from planner.validate import (load_json, validate_input_semantics, validate_plan_semantics,
                              validate_structure)


def _load_valid_plan(path):
    plan = load_json(path)
    validate_structure(plan, "plan")
    validate_plan_semantics(plan)
    return plan


def cmd_validate(args):
    data = load_json(args.input)
    validate_structure(data, "input")
    validate_input_semantics(data)
    print(f"OK: {args.input} is a valid planner input")


def cmd_allocate(args):
    data = load_json(args.input)
    validate_structure(data, "input")
    validate_input_semantics(data)
    plan = allocate(data)
    validate_structure(plan, "plan")
    validate_plan_semantics(plan)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
        f.write("\n")
    print(f"Wrote {args.out}")


def cmd_render(args):
    plan = _load_valid_plan(args.plan)
    written = configgen.render_all(plan, args.out, args.lab_name, args.frr_image, args.host_image)
    for path in written:
        print(path)
    print(f"Deploy with: sudo containerlab deploy -t {args.out}/topology.clab.yml")
    print(f"Then run:    python3 -m planner.cli configure --plan {args.plan}")


def cmd_configure(args):
    plan = _load_valid_plan(args.plan)
    lab = args.lab_name or configgen.default_lab_name(plan)
    total = len(labsetup.host_setup_commands(plan, lab))
    failures = labsetup.run_host_setup(plan, lab)
    for f in failures:
        print(f"FAIL  {f['command']}\n      {f['detail']}")
    if failures:
        sys.exit(f"error: {len(failures)} of {total} host setup commands failed")
    print(f"OK: ran {total} setup commands on the test hosts")


def cmd_evidence(args):
    plan = _load_valid_plan(args.plan)
    lab = args.lab_name or configgen.default_lab_name(plan)
    results = evidence.collect_evidence(plan, args.out, lab)
    for r in results:
        print(f"{'saved' if r['ok'] else 'FAIL '}  {args.out}/{r['file']}" + ("" if r["ok"] else f"  ({r['detail']})"))
    failed = [r for r in results if not r["ok"]]
    if failed:
        sys.exit(f"error: {len(failed)} of {len(results)} evidence commands failed (is the lab running?)")
    print(f"OK: saved {len(results)} files and plan.json in {args.out}")


def cmd_runlab(args):
    name = args.name or Path(args.input).stem.replace("org_", "")
    summary = runlab.run_lab(args.input, name, wait=args.wait, keep=args.keep, workers=args.workers)
    if summary["pass_rate"] < 100:
        sys.exit(f"error: only {summary['pass_rate']}% of the pings passed")


def cmd_impair(args):
    name = args.name or Path(args.input).stem.replace("org_", "")
    result = impair.run_impairments(args.input, name, runs=args.runs, count=args.count, interval=args.interval,
                                    wait=args.wait, method=args.method, check_only=args.check, keep=args.keep,
                                    capture=not args.no_capture)
    if args.check:
        print(f"OK: netem works using method '{result['method']}'")
    else:
        print(impair.markdown_table(result["summary"]))


def cmd_pingmatrix(args):
    plan = _load_valid_plan(args.plan)
    lab = args.lab_name or configgen.default_lab_name(plan)
    if args.dry_run:
        for entry in pingmatrix.build_ping_matrix(plan):
            print(" ".join(pingmatrix.ping_command(entry, lab)))
        return

    def show(done, total, r):
        line = f"[{done}/{total}] {'PASS' if r['passed'] else 'FAIL'}  {r['src']} -> {r['dst']} ({r['family']}, {r['target']})"
        print(line if r["passed"] or not r["detail"] else f"{line}\n      {r['detail']}", flush=True)

    started = time.perf_counter()
    results = pingmatrix.run_ping_matrix(plan, lab, workers=args.workers, progress=show)
    seconds = time.perf_counter() - started
    print(f"Pass rate: {pingmatrix.pass_rate(results):.1f}% ({sum(r['passed'] for r in results)}/{len(results)}) in {seconds:.1f} s")
    if args.csv:
        pingmatrix.write_csv(results, args.csv)
        print(f"Wrote {args.csv}")


def cmd_report(args):
    out = compare.write_report_csv(args.out, runs=args.runs)
    print(f"Wrote {out}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="planner", description="IPv4/IPv6 address planner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a planner input file")
    p.add_argument("--input", required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("allocate", help="input file -> addressing plan")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_allocate)

    p = sub.add_parser("render", help="plan -> FRR configs + containerlab topology")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lab-name")
    p.add_argument("--frr-image", default=configgen.DEFAULT_FRR_IMAGE)
    p.add_argument("--host-image", default=configgen.DEFAULT_HOST_IMAGE)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("configure", help="give the test hosts their addresses (run after containerlab deploy)")
    p.add_argument("--plan", required=True)
    p.add_argument("--lab-name")
    p.set_defaults(func=cmd_configure)

    p = sub.add_parser("evidence", help="save routing tables, OSPF neighbours and traceroutes from the running lab")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lab-name")
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("runlab", help="the whole chain for one organization: allocate, deploy, test, save evidence, destroy")
    p.add_argument("--input", required=True)
    p.add_argument("--name", help="folder name under evidence/ (default: the input file name without org_)")
    p.add_argument("--wait", type=int, default=60, help="seconds to wait for OSPF before pinging (default 60)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--keep", action="store_true", help="do not destroy the lab at the end")
    p.set_defaults(func=cmd_runlab)

    p = sub.add_parser("impair", help="delay and loss experiments on a router link (conditions C1, C2, C3)")
    p.add_argument("--input", required=True)
    p.add_argument("--name")
    p.add_argument("--runs", type=int, default=3, help="runs per condition (default 3)")
    p.add_argument("--count", type=int, default=100, help="pings per run (default 100)")
    p.add_argument("--interval", type=float, default=0.2, help="seconds between pings (default 0.2)")
    p.add_argument("--wait", type=int, default=60)
    p.add_argument("--method", choices=["auto", "tc", "clab"], default="auto")
    p.add_argument("--check", action="store_true", help="only deploy, test that netem works here, and destroy")
    p.add_argument("--keep", action="store_true")
    p.add_argument("--no-capture", action="store_true", help="skip the tcpdump packet captures")
    p.set_defaults(func=cmd_impair)

    p = sub.add_parser("pingmatrix", help="run the all-pairs ping test on the deployed lab")
    p.add_argument("--plan", required=True)
    p.add_argument("--lab-name")
    p.add_argument("--csv")
    p.add_argument("--workers", type=int, default=8, help="how many pings to run at the same time (default 8)")
    p.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    p.set_defaults(func=cmd_pingmatrix)

    p = sub.add_parser("report", help="export comparison, summarization, and timing metrics to CSV")
    p.add_argument("--out", default="comparison_report.csv")
    p.add_argument("--runs", type=int, default=20)
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, OSError, RuntimeError) as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()