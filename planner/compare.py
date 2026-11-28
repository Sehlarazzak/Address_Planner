import csv
import ipaddress
import statistics
import time
from pathlib import Path

from planner.allocator import _carve_ipv4_subnets, allocate
from planner.validate import load_json
from planner.vlsm import required_hosts, required_prefix

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _collect_subnet_requirements(data):
    """Return list of (sub_id, site_name, kind, hosts_needed, vlsm_prefixlen)."""
    items = []
    for site in data.get("sites", []):
        s_name = str(site["name"])
        for lan in site.get("subnets", []):
            hosts_needed = required_hosts(int(lan["hosts"]), int(lan["growth_pct"]))
            items.append((
                f"{s_name}:{lan['name']}",
                s_name,
                "lan",
                hosts_needed,
                required_prefix(hosts_needed),
            ))
    for idx, link in enumerate(data.get("links", []), start=1):
        items.append((
            f"link:{idx}:{link['name']}",
            str(link["a"]),
            "link",
            2,
            30,
        ))
    return items


def _evaluate_prefixes(ipv4_block, items_with_needed, prefixes):
    """Check whether `prefixes` fit inside `ipv4_block` and compute capacity metrics."""
    needed_total = sum(h for _, _, _, h, _ in items_with_needed)
    allocated_total = sum(1 << (32 - p) for p in prefixes)
    wasted_total = allocated_total - needed_total
    utilization_pct = (needed_total / allocated_total * 100.0) if allocated_total else 0.0

    fits = True
    try:
        nets = _carve_ipv4_subnets(
            ipv4_block,
            [(sub_id, p) for (sub_id, _, _, _, _), p in zip(items_with_needed, prefixes)],
        )
        for (_, _, _, hosts_needed, _), net in zip(items_with_needed, nets):
            if (net.num_addresses - 2) < hosts_needed:
                fits = False
                break
    except ValueError:
        fits = False

    return {
        "allocated": allocated_total,
        "needed": needed_total,
        "wasted": wasted_total,
        "utilization_pct": round(utilization_pct, 2),
        "fits": fits,
    }


def compare_organization(data):
    """Compare fixed-length, flat VLSM, and site-aligned VLSM for one organization input."""
    ipv4_block = ipaddress.IPv4Network(data["ipv4_block"], strict=True)
    items = _collect_subnet_requirements(data)

    # Fixed-length: every subnet uses the prefix for the largest requirement
    max_needed = max(h for _, _, _, h, _ in items)
    fixed_prefix = required_prefix(max_needed)
    fixed_metrics = _evaluate_prefixes(ipv4_block, items, [fixed_prefix] * len(items))
    fixed_metrics["prefixlen"] = fixed_prefix

    # Flat VLSM: all subnets carved together from ipv4_block
    flat_prefixes = [p for _, _, _, _, p in items]
    flat_metrics = _evaluate_prefixes(ipv4_block, items, flat_prefixes)

    # Site-aligned VLSM: actual output of allocate(data)
    aligned_needed = sum(h for _, _, _, h, _ in items)
    aligned_allocated = 0
    aligned_fits = True
    try:
        plan = allocate(data)
        aligned_allocated = sum(1 << (32 - s["ipv4_prefixlen"]) for s in plan["subnets"])
    except ValueError:
        aligned_fits = False

    aligned_wasted = aligned_allocated - aligned_needed
    aligned_util = (aligned_needed / aligned_allocated * 100.0) if aligned_allocated else 0.0
    aligned_metrics = {
        "allocated": aligned_allocated,
        "needed": aligned_needed,
        "wasted": aligned_wasted,
        "utilization_pct": round(aligned_util, 2),
        "fits": aligned_fits,
    }

    return {
        "organization": data["organization"],
        "ipv4_block": str(ipv4_block),
        "block_size": ipv4_block.num_addresses,
        "subnet_count": len(items),
        "fixed": fixed_metrics,
        "flat_vlsm": flat_metrics,
        "site_aligned_vlsm": aligned_metrics,
    }


def compare_sample_orgs(data_dir=DATA_DIR):
    """Run comparison for small, medium, and large sample organizations."""
    results = []
    for name in ("org_small.json", "org_medium.json", "org_large.json"):
        path = Path(data_dir) / name
        if path.exists():
            results.append(compare_organization(load_json(path)))
    return results


def _smallest_covering_network(networks):
    """Return the smallest single IPv4Network covering all given IPv4Network objects."""
    if not networks:
        raise ValueError("Cannot compute covering prefix for an empty subnet list")
    collapsed = list(ipaddress.collapse_addresses(networks))
    current = collapsed[0]
    for nxt in collapsed[1:]:
        while not (current.subnet_of(nxt) and nxt.supernet_of(current) or nxt.subnet_of(current)):
            if current.supernet_of(nxt):
                break
            if current.prefixlen == 0:
                raise ValueError("Reached /0 while computing covering summary prefix")
            current = current.supernet(new_prefix=current.prefixlen - 1)
        if nxt.subnet_of(current):
            continue
        while not nxt.subnet_of(current):
            if current.prefixlen == 0:
                raise ValueError("Reached /0 while computing covering summary prefix")
            current = current.supernet(new_prefix=current.prefixlen - 1)
    return current


def summarize_plan(plan):
    """Compute per-site summary prefixes, verify isolation, and return route counts."""
    subnets = plan["subnets"]
    lan_subnets = [s for s in subnets if s["type"] == "lan"]
    link_subnets = [s for s in subnets if s["type"] == "link"]

    site_names = sorted({s["site"] for s in lan_subnets})
    site_nets = {
        s["id"]: ipaddress.IPv4Network(s["ipv4_cidr"], strict=True)
        for s in subnets
    }

    summaries = {}
    for s_name in site_names:
        own_nets = [
            site_nets[s["id"]]
            for s in lan_subnets
            if s["site"] == s_name
        ]
        other_nets = [
            site_nets[s["id"]]
            for s in subnets
            if s["type"] != "lan" or s["site"] != s_name
        ]
        summary_net = _smallest_covering_network(own_nets)

        for other_net in other_nets:
            if other_net.subnet_of(summary_net) or summary_net.subnet_of(other_net):
                raise ValueError(
                    f"Summary {summary_net} for site {s_name!r} conflicts with non-site subnet {other_net}"
                )
        summaries[s_name] = str(summary_net)

    routes_before = len(subnets)
    routes_after = len(summaries) + (1 if link_subnets else 0)

    return {
        "organization": plan["organization"],
        "site_summaries": summaries,
        "routes_before": routes_before,
        "routes_after": routes_after,
    }


def summarize_sample_orgs(data_dir=DATA_DIR):
    """Run summarization analysis for small, medium, and large sample organizations."""
    results = []
    for name in ("org_small.json", "org_medium.json", "org_large.json"):
        path = Path(data_dir) / name
        if path.exists():
            plan = allocate(load_json(path))
            results.append(summarize_plan(plan))
    return results


def benchmark_allocation(data, runs=20):
    """Return the median allocation time in milliseconds over `runs` iterations."""
    times_ms = []
    for _ in range(runs):
        t0 = time.perf_counter()
        allocate(data)
        times_ms.append((time.perf_counter() - t0) * 1000.0)
    return round(statistics.median(times_ms), 4)


def build_report_rows(data_dir=DATA_DIR, runs=20):
    """Build combined comparison, summarization, and median timing rows for sample orgs."""
    rows = []
    for name in ("org_small.json", "org_medium.json", "org_large.json"):
        path = Path(data_dir) / name
        if not path.exists():
            continue
        data = load_json(path)
        comp = compare_organization(data)
        plan = allocate(data)
        summ = summarize_plan(plan)
        med_ms = benchmark_allocation(data, runs=runs)

        rows.append({
            "organization": comp["organization"],
            "subnets": comp["subnet_count"],
            "block_size": comp["block_size"],
            "fixed_allocated": comp["fixed"]["allocated"],
            "fixed_needed": comp["fixed"]["needed"],
            "fixed_wasted": comp["fixed"]["wasted"],
            "fixed_utilization_pct": comp["fixed"]["utilization_pct"],
            "flat_allocated": comp["flat_vlsm"]["allocated"],
            "flat_needed": comp["flat_vlsm"]["needed"],
            "flat_wasted": comp["flat_vlsm"]["wasted"],
            "flat_utilization_pct": comp["flat_vlsm"]["utilization_pct"],
            "aligned_allocated": comp["site_aligned_vlsm"]["allocated"],
            "aligned_needed": comp["site_aligned_vlsm"]["needed"],
            "aligned_wasted": comp["site_aligned_vlsm"]["wasted"],
            "aligned_utilization_pct": comp["site_aligned_vlsm"]["utilization_pct"],
            "routes_before": summ["routes_before"],
            "routes_after": summ["routes_after"],
            "allocation_time_ms_median": med_ms,
        })
    return rows


def write_report_csv(out_path, data_dir=DATA_DIR, runs=20):
    """Write comparison, summarization, and timing metrics to `out_path`."""
    rows = build_report_rows(data_dir=data_dir, runs=runs)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "organization",
        "subnets",
        "block_size",
        "fixed_allocated",
        "fixed_needed",
        "fixed_wasted",
        "fixed_utilization_pct",
        "flat_allocated",
        "flat_needed",
        "flat_wasted",
        "flat_utilization_pct",
        "aligned_allocated",
        "aligned_needed",
        "aligned_wasted",
        "aligned_utilization_pct",
        "routes_before",
        "routes_after",
        "allocation_time_ms_median",
    ]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out