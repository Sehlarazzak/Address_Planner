"""Give the test hosts their addresses AFTER the lab is deployed.

Containerlab's own `exec:` option ran before the cables were attached in the first real deployment,
so the hosts came up with no IP address. Doing it ourselves, after `containerlab deploy`, is
reliable, repeatable (`replace` never fails with "File exists") and prints any error.
"""
import subprocess

from planner.configgen import build_model, default_lab_name
from planner.pingmatrix import output_detail


def host_setup_commands(plan, lab_name=None):
    """The docker commands that configure every test host: address, address, default route, default route."""
    lab_name = lab_name or default_lab_name(plan)
    commands = []
    for host in build_model(plan)["hosts"]:
        base = ["docker", "exec", f"clab-{lab_name}-{host['name']}"]
        commands.append(base + ["ip", "addr", "replace", host["ipv4_cidr"], "dev", "eth1"])
        commands.append(base + ["ip", "-6", "addr", "replace", host["ipv6_cidr"], "dev", "eth1"])
        commands.append(base + ["ip", "route", "replace", "default", "via", host["gw4"]])
        commands.append(base + ["ip", "-6", "route", "replace", "default", "via", host["gw6"]])
    return commands


def run_host_setup(plan, lab_name=None, runner=subprocess.run):
    """Run every setup command; return a list of {"command", "detail"} for the ones that failed.

    `runner` is injectable so tests can fake docker."""
    failures = []
    for cmd in host_setup_commands(plan, lab_name):
        done = runner(cmd, capture_output=True, text=True)
        if done.returncode != 0:
            failures.append({"command": " ".join(cmd), "detail": output_detail(done)})
    return failures
