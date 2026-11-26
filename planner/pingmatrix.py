"""The reachability test: every LAN host pings every other LAN host over IPv4 and IPv6."""
import csv
import subprocess

from planner.configgen import build_model, default_lab_name


def build_ping_matrix(plan):
    """List of {"src", "dst", "family", "target"}: every ordered pair of hosts, once per family."""
    hosts = build_model(plan)["hosts"]
    entries = []
    for src in hosts:
        for dst in hosts:
            if src is dst:
                continue
            for family in ("ipv4", "ipv6"):
                entries.append({"src": src["name"], "dst": dst["name"], "family": family,
                                "target": dst["ipv4"] if family == "ipv4" else dst["ipv6"]})
    return entries


def ping_command(entry, lab_name, count=2):
    """The docker command that runs one ping inside the source host's container."""
    flag = "-4" if entry["family"] == "ipv4" else "-6"
    return ["docker", "exec", f"clab-{lab_name}-{entry['src']}",
            "ping", flag, "-c", str(count), "-W", "2", "-n", entry["target"]]


def output_detail(done):
    """One short line explaining a failed command: the last line of its error output, else of its output."""
    err = [l.strip() for l in (getattr(done, "stderr", "") or "").splitlines() if l.strip()]
    out = [l.strip() for l in (getattr(done, "stdout", "") or "").splitlines() if l.strip()]
    lines = err or out
    return lines[-1][:200] if lines else ""


def run_ping_matrix(plan, lab_name=None, runner=subprocess.run, count=2):
    """Run every test; return a list of entries with a "passed" True/False added.

    `runner` is injectable so tests can fake docker."""
    lab_name = lab_name or default_lab_name(plan)
    results = []
    for entry in build_ping_matrix(plan):
        done = runner(ping_command(entry, lab_name, count), capture_output=True, text=True)
        passed = done.returncode == 0
        results.append({**entry, "passed": passed, "detail": "" if passed else output_detail(done)})
    return results


def pass_rate(results):
    """Percentage of tests that passed (0.0 for an empty list)."""
    if not results:
        return 0.0
    return 100.0 * sum(1 for r in results if r["passed"]) / len(results)


def write_csv(results, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["src", "dst", "family", "target", "passed", "detail"])
        writer.writeheader()
        writer.writerows(results)
