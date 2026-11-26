"""Collect the evidence the brief asks for from a RUNNING lab: routing tables, OSPF neighbours, traceroutes.

One folder per organization, so the report can point at saved files instead of screenshots.
"""
import json
import subprocess
from pathlib import Path

from planner.configgen import build_model, default_lab_name
from planner.pingmatrix import output_detail

ROUTER_COMMANDS = [
    ("ip_route", "show ip route"),
    ("ipv6_route", "show ipv6 route"),
    ("ospf_neighbors", "show ip ospf neighbor"),
    ("ospf6_neighbors", "show ipv6 ospf6 neighbor"),
]


def _site_of_host(plan, model):
    """Map each test host name to the site its LAN belongs to."""
    site_of_subnet = {s["id"]: s["site"] for s in plan["subnets"]}
    return {h["name"]: site_of_subnet[h["subnet_id"]] for h in model["hosts"]}


def evidence_commands(plan, lab_name=None):
    """List of (file name, docker command) to run on the deployed lab.

    - 4 vtysh commands on every router (routes and OSPF neighbours, IPv4 and IPv6)
    - traceroutes (IPv4 and IPv6) from the first site's first host to the first host of every other site,
      plus one branch-to-branch trace when there are 3 or more sites, so every trace crosses a router."""
    lab_name = lab_name or default_lab_name(plan)
    model = build_model(plan)
    commands = []

    for router in model["routers"]:
        container = f"clab-{lab_name}-{router['name']}"
        for suffix, vtysh in ROUTER_COMMANDS:
            commands.append((f"{router['name']}_{suffix}.txt",
                             ["docker", "exec", container, "vtysh", "-c", vtysh]))

    site_of = _site_of_host(plan, model)
    # one representative host per site (the first LAN host of each site, in input order)
    reps = {}
    for host in model["hosts"]:
        reps.setdefault(site_of[host["name"]], host)
    reps = list(reps.values())
    pairs = [(reps[0], other) for other in reps[1:]]
    if len(reps) >= 3:
        pairs.append((reps[1], reps[-1]))          # branch to branch: has to cross the hub as well

    for source, target in pairs:
        container = f"clab-{lab_name}-{source['name']}"
        base = f"traceroute_{source['name']}_to_{target['name']}"
        commands.append((f"{base}_ipv4.txt",
                         ["docker", "exec", container, "traceroute", "-n", target["ipv4"]]))
        commands.append((f"{base}_ipv6.txt",
                         ["docker", "exec", container, "traceroute", "-6", "-n", target["ipv6"]]))
    return commands


def collect_evidence(plan, out_dir, lab_name=None, runner=subprocess.run):
    """Run every evidence command and save its output. Returns [{"file", "ok", "detail"}].

    Also saves plan.json next to the results so each folder is self-contained.
    `runner` is injectable so tests can fake docker."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    results = []
    for filename, cmd in evidence_commands(plan, lab_name):
        done = runner(cmd, capture_output=True, text=True)
        ok = done.returncode == 0
        text = getattr(done, "stdout", "") or ""
        if not ok:
            text += "\n[command failed]\n" + (getattr(done, "stderr", "") or "")
        (out / filename).write_text(text, encoding="utf-8")
        results.append({"file": filename, "ok": ok, "detail": "" if ok else output_detail(done)})
    return results
