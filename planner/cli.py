"""Command-line entry point.

    python -m planner.cli validate   --input data/org_small.json
    python -m planner.cli allocate   --input data/org_small.json --out plan.json   (needs the allocator)
    python -m planner.cli render     --plan  data/plan_example_mini.json --out build
    python -m planner.cli configure  --plan  data/plan_example_mini.json        (after containerlab deploy)
    python -m planner.cli pingmatrix --plan  data/plan_example_mini.json [--dry-run] [--csv results.csv]
"""
import argparse
import json
import sys

from planner import configgen, labsetup, pingmatrix
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
    try:
        from planner.allocator import allocate          # Tania's module; does not exist yet
    except ImportError:
        sys.exit("error: the allocator (planner/allocator.py) is not implemented yet")
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


def cmd_pingmatrix(args):
    plan = _load_valid_plan(args.plan)
    lab = args.lab_name or configgen.default_lab_name(plan)
    if args.dry_run:
        for entry in pingmatrix.build_ping_matrix(plan):
            print(" ".join(pingmatrix.ping_command(entry, lab)))
        return
    results = pingmatrix.run_ping_matrix(plan, lab)
    for r in results:
        line = f"{'PASS' if r['passed'] else 'FAIL'}  {r['src']} -> {r['dst']} ({r['family']}, {r['target']})"
        print(line if r["passed"] or not r["detail"] else f"{line}\n      {r['detail']}")
    print(f"Pass rate: {pingmatrix.pass_rate(results):.1f}% ({sum(r['passed'] for r in results)}/{len(results)})")
    if args.csv:
        pingmatrix.write_csv(results, args.csv)
        print(f"Wrote {args.csv}")


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

    p = sub.add_parser("pingmatrix", help="run the all-pairs ping test on the deployed lab")
    p.add_argument("--plan", required=True)
    p.add_argument("--lab-name")
    p.add_argument("--csv")
    p.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    p.set_defaults(func=cmd_pingmatrix)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, OSError) as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
