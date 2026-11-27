"""Impairment experiments (delay and loss on a router link), from the project proposal.

    C1 baseline 0 ms / 0 %     C2 moderate 50 ms / 2 %     C3 higher 100 ms / 5 %     (per direction)

Each condition is run 3 times. In every run, netem is applied to the egress interface of BOTH routers
on the chosen link, so a ping crosses the impaired link in both directions, then 100 ICMP echo requests
are sent from a host behind one router to a host behind the other, over IPv4 and IPv6.
"""
import csv
import json
import re
import statistics
import subprocess
import time
from pathlib import Path

from planner import configgen, labsetup
from planner.allocator import allocate
from planner.configgen import build_model
from planner.validate import (load_json, validate_input_semantics, validate_plan_semantics,
                              validate_structure)

CONDITIONS = [("C1", 0, 0.0), ("C2", 50, 2.0), ("C3", 100, 5.0)]    # name, delay ms, loss % (per direction)
CONTAINERLAB = ["sudo", "containerlab"]

_PACKETS = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received(?:, \+\d+ errors)?, ([\d.]+)% packet loss")
_RTT = re.compile(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")


def parse_ping_output(text):
    """Pull sent, received, loss % and the RTT figures (ms) out of iputils ping output."""
    m = _PACKETS.search(text)
    if not m:
        raise ValueError("could not find the packet statistics in the ping output")
    result = {"sent": int(m.group(1)), "received": int(m.group(2)), "loss_pct": float(m.group(3)),
              "rtt_min": None, "rtt_avg": None, "rtt_max": None, "rtt_mdev": None}
    r = _RTT.search(text)
    if r:
        result.update(rtt_min=float(r.group(1)), rtt_avg=float(r.group(2)),
                      rtt_max=float(r.group(3)), rtt_mdev=float(r.group(4)))
    return result


def expected_rtt_ms(delay_ms):
    """A ping crosses the impaired link twice, so the extra round-trip time is twice the per-direction delay."""
    return 2.0 * delay_ms


def expected_loss_pct(loss_pct):
    """A ping is lost if either the request or the reply is lost: 1 - (1 - p)^2."""
    p = loss_pct / 100.0
    return 100.0 * (1.0 - (1.0 - p) ** 2)


def pick_link(plan):
    """First router-to-router link: returns (link subnet id, [(router, iface), (router, iface)])."""
    link = next(s for s in plan["subnets"] if s["type"] == "link")
    ends = [(r["name"], i["name"], r["site"]) for r in plan["routers"]
            for i in r["interfaces"] if i["subnet_id"] == link["id"]]
    return link["id"], ends


def pick_test_pair(plan):
    """(source host, destination host): one host behind each router of the chosen link."""
    _, ends = pick_link(plan)
    model = build_model(plan)
    site_of_subnet = {s["id"]: s["site"] for s in plan["subnets"]}
    first_on = {}
    for host in model["hosts"]:
        first_on.setdefault(site_of_subnet[host["subnet_id"]], host)
    return first_on[ends[0][2]], first_on[ends[1][2]]


def netem_apply_command(method, container, iface, delay_ms, loss_pct):
    if method == "tc":
        return ["docker", "exec", container, "tc", "qdisc", "replace", "dev", iface, "root",
                "netem", "delay", f"{delay_ms}ms", "loss", f"{loss_pct}%"]
    return CONTAINERLAB + ["tools", "netem", "set", "-n", container, "-i", iface,
                           "--delay", f"{delay_ms}ms", "--loss", str(loss_pct)]


def netem_clear_command(method, container, iface):
    if method == "tc":
        return ["docker", "exec", container, "tc", "qdisc", "del", "dev", iface, "root"]
    return CONTAINERLAB + ["tools", "netem", "reset", "-n", container, "-i", iface]


def check_netem(lab, ends, methods=("tc", "clab"), runner=subprocess.run):
    """Return the first method that can apply and remove netem on the link, or raise RuntimeError."""
    router, iface, _ = ends[0]
    container = f"clab-{lab}-{router}"
    problems = []
    for method in methods:
        done = runner(netem_apply_command(method, container, iface, 1, 0.0), capture_output=True, text=True)
        runner(netem_clear_command(method, container, iface), capture_output=True, text=True)
        if done.returncode == 0:
            return method
        problems.append(f"{method}: {(getattr(done, 'stderr', '') or getattr(done, 'stdout', '') or '').strip()[:150]}")
    raise RuntimeError("netem does not work here (" + "; ".join(problems) + "). On WSL2 the default kernel "
                       "may not include the netem scheduler; tell your instructor or try a native Linux/VM.")


def summarize(rows):
    """Mean and sample standard deviation of loss % and average RTT across runs, per condition and family."""
    out = []
    for condition, delay, loss in CONDITIONS:
        for family in ("ipv4", "ipv6"):
            group = [r for r in rows if r["condition"] == condition and r["family"] == family]
            if not group:
                continue
            losses = [r["loss_pct_measured"] for r in group]
            rtts = [r["rtt_avg"] for r in group if r["rtt_avg"] is not None]
            sd = lambda xs: statistics.stdev(xs) if len(xs) > 1 else 0.0
            out.append({
                "condition": condition, "family": family, "runs": len(group),
                "delay_ms_per_direction": delay, "loss_pct_per_direction": loss,
                "expected_rtt_ms": expected_rtt_ms(delay), "expected_loss_pct": round(expected_loss_pct(loss), 2),
                "loss_mean": round(statistics.mean(losses), 2), "loss_stdev": round(sd(losses), 2),
                "rtt_mean": round(statistics.mean(rtts), 2) if rtts else None,
                "rtt_stdev": round(sd(rtts), 2) if rtts else None,
            })
    return out


def markdown_table(summary):
    lines = ["| Condition | Family | Runs | Expected RTT (ms) | Mean RTT (ms) | RTT stdev | Expected loss (%) | Mean loss (%) | Loss stdev |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        lines.append(f"| {s['condition']} | {s['family']} | {s['runs']} | {s['expected_rtt_ms']:.0f} | {s['rtt_mean']} | "
                     f"{s['rtt_stdev']} | {s['expected_loss_pct']} | {s['loss_mean']} | {s['loss_stdev']} |")
    return "\n".join(lines) + "\n"


def _write_csv(rows, path, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_impairments(input_path, name, runs=3, count=100, interval=0.2, wait=60, method="auto",
                    check_only=False, keep=False, capture=True, capture_packets=40,
                    evidence_root="evidence", build_root=".",
                    runner=subprocess.run, sleeper=time.sleep, log=print):
    """Deploy the lab, run C1/C2/C3 x `runs` ping tests, save the results, destroy the lab.

    With capture=True, run 1 of every condition also records the first `capture_packets` ICMP packets on the
    source host (a .pcap for Wireshark plus a readable _packets.txt with timestamps)."""
    data = load_json(input_path)
    validate_structure(data, "input")
    validate_input_semantics(data)
    plan = allocate(data)
    validate_structure(plan, "plan")
    validate_plan_semantics(plan)
    lab = configgen.default_lab_name(plan)
    build_dir = Path(build_root) / f"build_{name}_impair"
    out_dir = Path(evidence_root) / f"{name}_impairment"
    topology = build_dir / "topology.clab.yml"
    configgen.render_all(plan, build_dir, lab)
    out_dir.mkdir(parents=True, exist_ok=True)
    link_id, ends = pick_link(plan)
    src, dst = pick_test_pair(plan)
    log(f"[{name}] impairing link {link_id} ({ends[0][0]}:{ends[0][1]} <-> {ends[1][0]}:{ends[1][1]}); "
        f"pinging {src['name']} -> {dst['name']}")

    cleared = False
    try:
        if runner(CONTAINERLAB + ["deploy", "-t", str(topology)]).returncode != 0:
            raise RuntimeError("containerlab deploy failed")
        failures = labsetup.run_host_setup(plan, lab, runner=runner)
        if failures:
            raise RuntimeError(f"host setup failed: {failures[0]['command']} ({failures[0]['detail']})")
        log(f"[{name}] waiting {wait} s for OSPF")
        sleeper(wait)

        methods = ("tc", "clab") if method == "auto" else (method,)
        method = check_netem(lab, ends, methods, runner)
        log(f"[{name}] netem works using method '{method}'")
        if check_only:
            return {"method": method}

        src_container = f"clab-{lab}-{src['name']}"
        can_capture = capture and runner(["docker", "exec", src_container, "tcpdump", "--version"],
                                         capture_output=True, text=True).returncode == 0
        if capture and not can_capture:
            log(f"[{name}] tcpdump not found in {src['name']}; skipping packet captures")

        def set_condition(delay, loss):
            for router, iface, _ in ends:
                container = f"clab-{lab}-{router}"
                if delay == 0 and loss == 0:
                    runner(netem_clear_command(method, container, iface), capture_output=True, text=True)
                else:
                    done = runner(netem_apply_command(method, container, iface, delay, loss),
                                  capture_output=True, text=True)
                    if done.returncode != 0:
                        raise RuntimeError(f"could not apply netem on {container}:{iface}")

        rows = []
        for condition, delay, loss in CONDITIONS:
            for run in range(1, runs + 1):
                set_condition(delay, loss)
                log(f"[{name}] {condition} (delay {delay} ms, loss {loss}% each way) run {run}/{runs}")
                for family, flag, target in (("ipv4", "-4", dst["ipv4"]), ("ipv6", "-6", dst["ipv6"])):
                    cmd = ["docker", "exec", src_container, "ping", flag, "-c", str(count),
                           "-i", str(interval), "-W", "2", "-n", target]
                    capturing = can_capture and run == 1
                    pcap = f"/tmp/{condition}_{family}.pcap"
                    if capturing:
                        flt = "icmp" if family == "ipv4" else "icmp6"
                        runner(["docker", "exec", "-d", src_container, "sh", "-c",
                                f"tcpdump -nn -i eth1 -c {capture_packets} -w {pcap} {flt}"],
                               capture_output=True, text=True)
                        sleeper(1)                                  # let tcpdump start listening
                    done = runner(cmd, capture_output=True, text=True)
                    if capturing:
                        sleeper(1)
                        runner(["docker", "cp", f"{src_container}:{pcap}", str(out_dir / f"{condition}_{family}.pcap")],
                               capture_output=True, text=True)
                        text = runner(["docker", "exec", src_container, "tcpdump", "-nn", "-tt", "-r", pcap],
                                      capture_output=True, text=True)
                        (out_dir / f"{condition}_{family}_packets.txt").write_text(
                            getattr(text, "stdout", "") or "", encoding="utf-8")
                    stats = parse_ping_output(getattr(done, "stdout", "") or "")
                    rows.append({"condition": condition, "delay_ms": delay, "loss_pct": loss, "run": run,
                                 "family": family, "src": src["name"], "dst": dst["name"],
                                 "sent": stats["sent"], "received": stats["received"],
                                 "loss_pct_measured": stats["loss_pct"], "rtt_min": stats["rtt_min"],
                                 "rtt_avg": stats["rtt_avg"], "rtt_max": stats["rtt_max"], "rtt_mdev": stats["rtt_mdev"]})
        set_condition(0, 0)
        cleared = True

        _write_csv(rows, out_dir / "impairment_runs.csv",
                   ["condition", "delay_ms", "loss_pct", "run", "family", "src", "dst", "sent", "received",
                    "loss_pct_measured", "rtt_min", "rtt_avg", "rtt_max", "rtt_mdev"])
        summary = summarize(rows)
        _write_csv(summary, out_dir / "impairment_summary.csv", list(summary[0].keys()))
        (out_dir / "impairment_summary.md").write_text(markdown_table(summary), encoding="utf-8")
        (out_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        log(f"[{name}] saved {len(rows)} runs and a summary in {out_dir}")
        return {"method": method, "rows": rows, "summary": summary}
    finally:
        if not keep:
            runner(CONTAINERLAB + ["destroy", "-t", str(topology), "--cleanup"])
        else:
            log(f"[{name}] lab left running; remove it with: sudo containerlab destroy -t {topology} --cleanup")
