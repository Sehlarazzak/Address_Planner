import ipaddress
import time

from planner.ipv6_alloc import allocate_64s, carve_site_blocks, interface_address
from planner.vlsm import required_hosts, required_prefix


def _extract_link_endpoints(link, site_names):
    """Extract (site_a, site_b, link_name) as non-empty strings from a link object."""
    fallback_a = site_names[0]
    fallback_b = site_names[1] if len(site_names) > 1 else site_names[0]

    if isinstance(link, dict):
        endpoints = link.get("endpoints") or link.get("sites") or link.get("nodes")
        a_site = link.get("site_a") or link.get("from") or link.get("source") or link.get("a")
        b_site = link.get("site_b") or link.get("to") or link.get("target") or link.get("b")

        if (not a_site or not b_site) and isinstance(endpoints, (list, tuple)) and len(endpoints) >= 2:
            a_site = a_site or endpoints[0]
            b_site = b_site or endpoints[1]

        if not a_site or not b_site:
            for val in link.values():
                if isinstance(val, str) and val in site_names:
                    if not a_site:
                        a_site = val
                    elif not b_site and val != a_site:
                        b_site = val

        a_site = str(a_site) if a_site else fallback_a
        b_site = str(b_site) if b_site else fallback_b
        link_name = str(link.get("name") or link.get("id") or f"{a_site}-{b_site}")
        return a_site, b_site, link_name

    return fallback_a, fallback_b, f"{fallback_a}-{fallback_b}"


def _carve_ipv4_subnets(block, items_with_prefix):
    """Allocate non-overlapping IPv4 subnets inside `block`, largest first."""
    indexed = sorted(enumerate(items_with_prefix), key=lambda pair: pair[1][1])
    available_cursor = int(block.network_address)
    block_end = int(block.broadcast_address) + 1
    allocated_nets = {}

    for orig_idx, (sub_id, prefixlen) in indexed:
        size = 1 << (32 - prefixlen)
        remainder = available_cursor % size
        if remainder != 0:
            available_cursor += size - remainder
        if available_cursor + size > block_end:
            raise ValueError(
                f"IPv4 block {block} exhausted while allocating /{prefixlen} for {sub_id!r}"
            )
        net = ipaddress.IPv4Network((available_cursor, prefixlen), strict=True)
        allocated_nets[orig_idx] = net
        available_cursor += size

    return [allocated_nets[i] for i in range(len(items_with_prefix))]


def allocate(data):
    """Build a validated addressing plan dictionary from an organization input."""
    t0 = time.perf_counter()

    ipv4_block = ipaddress.IPv4Network(data["ipv4_block"], strict=True)
    sites = data.get("sites", [])
    site_names = [str(s["name"]) for s in sites]
    site_blocks, link_block = carve_site_blocks(data["ipv6_prefix"], site_names)

    site_64_pools = {}
    for s_name, s_block in site_blocks.items():
        site_obj = next(s for s in sites if str(s["name"]) == s_name)
        lan_count = len(site_obj.get("subnets", []))
        site_64_pools[s_name] = iter(allocate_64s(s_block, lan_count))

    links = data.get("links", [])
    link_64_pool = iter(allocate_64s(link_block, len(links)))

    subnet_specs = []
    subnet_ipv6_map = {}
    link_subnet_ids = []

    # 1. LAN subnets per site
    for site_obj in sites:
        s_name = str(site_obj["name"])
        for lan in site_obj.get("subnets", []):
            hosts_req = int(lan["hosts"])
            growth = int(lan["growth_pct"])
            hosts_needed = required_hosts(hosts_req, growth)
            prefixlen = required_prefix(hosts_needed)
            sub_id = f"{s_name}:{lan['name']}"
            ipv6_net = next(site_64_pools[s_name])
            subnet_ipv6_map[sub_id] = ipv6_net
            subnet_specs.append({
                "id": sub_id,
                "site": s_name,
                "name": str(lan["name"]),
                "type": "lan",
                "hosts_requested": hosts_req,
                "growth_pct": growth,
                "hosts_required": hosts_needed,
                "ipv4_prefixlen": prefixlen,
                "ipv6_cidr": str(ipv6_net),
            })

    # 2. Point-to-point links (/30 IPv4, 2 hosts required)
    for idx, link in enumerate(links, start=1):
        a_site, b_site, link_name = _extract_link_endpoints(link, site_names)
        sub_id = f"link:{idx}:{link_name}"
        ipv6_net = next(link_64_pool)
        subnet_ipv6_map[sub_id] = ipv6_net
        link_subnet_ids.append((sub_id, a_site, b_site))
        subnet_specs.append({
            "id": sub_id,
            "site": a_site,
            "name": link_name,
            "type": "link",
            "hosts_requested": 2,
            "growth_pct": 0,
            "hosts_required": 2,
            "ipv4_prefixlen": 30,
            "ipv6_cidr": str(ipv6_net),
        })

    carved_v4 = _carve_ipv4_subnets(
        ipv4_block, [(spec["id"], spec["ipv4_prefixlen"]) for spec in subnet_specs]
    )

    subnets_out = []
    subnet_v4_map = {}
    subnet_next_host_idx = {}

    for spec, v4_net in zip(subnet_specs, carved_v4):
        usable = v4_net.num_addresses - 2
        subnet_v4_map[spec["id"]] = v4_net
        subnet_next_host_idx[spec["id"]] = 1
        subnets_out.append({
            "id": spec["id"],
            "site": spec["site"],
            "name": spec["name"],
            "type": spec["type"],
            "hosts_requested": spec["hosts_requested"],
            "growth_pct": spec["growth_pct"],
            "hosts_required": spec["hosts_required"],
            "ipv4_cidr": str(v4_net),
            "ipv4_prefixlen": spec["ipv4_prefixlen"],
            "ipv4_usable": usable,
            "ipv6_cidr": spec["ipv6_cidr"],
        })

    # 3. Build routers (at least 2 routers, each with at least 1 interface)
    raw_routers = data.get("routers")
    if not raw_routers:
        router_specs = []
        for idx, s_name in enumerate(site_names, start=1):
            site_lans = [s["id"] for s in subnets_out if s["type"] == "lan" and s["site"] == s_name]
            related_links = [
                sid for sid, a_s, b_s in link_subnet_ids if a_s == s_name or b_s == s_name
            ]
            iface_targets = site_lans + related_links
            if not iface_targets and subnets_out:
                iface_targets = [subnets_out[0]["id"]]
            router_specs.append({
                "name": f"r-{s_name}",
                "site": s_name,
                "subnet_ids": iface_targets,
            })

        # Ensure at least 2 routers exist to satisfy schema minItems: 2
        while len(router_specs) < 2:
            target_sub = subnets_out[len(router_specs) % len(subnets_out)]["id"]
            target_site = site_names[len(router_specs) % len(site_names)]
            router_specs.append({
                "name": f"r-{target_site}-{len(router_specs) + 1}",
                "site": target_site,
                "subnet_ids": [target_sub],
            })
    else:
        router_specs = []
        for idx, r in enumerate(raw_routers, start=1):
            r_site = str(r.get("site") or site_names[0])
            r_name = str(r.get("name") or f"r{idx}")
            ifaces = r.get("interfaces") or []
            sub_ids = []
            for iface in ifaces:
                if isinstance(iface, dict) and iface.get("subnet_id") in subnet_v4_map:
                    sub_ids.append(iface["subnet_id"])
            if not sub_ids:
                site_lans = [s["id"] for s in subnets_out if s["type"] == "lan" and s["site"] == r_site]
                sub_ids = site_lans[:1] or [subnets_out[0]["id"]]
            router_specs.append({"name": r_name, "site": r_site, "subnet_ids": sub_ids})

        while len(router_specs) < 2:
            extra_idx = len(router_specs) + 1
            extra_site = site_names[(extra_idx - 1) % len(site_names)]
            extra_sub = subnets_out[(extra_idx - 1) % len(subnets_out)]["id"]
            router_specs.append({
                "name": f"r{extra_idx}",
                "site": extra_site,
                "subnet_ids": [extra_sub],
            })

    routers_out = []
    for r_spec in router_specs:
        ifaces_out = []
        for iface_num, sub_id in enumerate(r_spec["subnet_ids"], start=1):
            host_idx = subnet_next_host_idx[sub_id]
            subnet_next_host_idx[sub_id] = host_idx + 1

            v4_net = subnet_v4_map[sub_id]
            v6_net = subnet_ipv6_map[sub_id]
            v4_addr = str(v4_net.network_address + host_idx)
            v6_addr = interface_address(v6_net, host_idx)

            ifaces_out.append({
                "name": f"eth{iface_num}",
                "subnet_id": sub_id,
                "ipv4": v4_addr,
                "ipv6": v6_addr,
            })

        routers_out.append({
            "name": r_spec["name"],
            "site": r_spec["site"],
            "interfaces": ifaces_out,
        })

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "organization": data["organization"],
        "ipv4_block": str(ipv4_block),
        "ipv6_prefix": str(ipaddress.IPv6Network(data["ipv6_prefix"], strict=True)),
        "ipv6_sites": {name: str(net) for name, net in site_blocks.items()},
        "ipv6_link_block": str(link_block),
        "subnets": subnets_out,
        "routers": routers_out,
        "metrics": {"allocation_time_ms": round(elapsed_ms, 3)},
    }