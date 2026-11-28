import ipaddress
import math
import time

from planner.ipv6_alloc import allocate_64s, carve_site_blocks, interface_address
from planner.vlsm import required_hosts, required_prefix


def _next_power_of_two(n):
    """Return smallest power of two >= max(1, n)."""
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def _prefixlen_for_block_size(size):
    """Convert a power-of-two IPv4 block size into a /prefixlen."""
    if size < 1 or (size & (size - 1)) != 0:
        raise ValueError(f"Block size must be a power of two, got {size}")
    return 32 - (size.bit_length() - 1)


def _extract_link_endpoints(link):
    """Extract (site_a, site_b, link_name) directly from a schema-valid link object."""
    return str(link["a"]), str(link["b"]), str(link["name"])


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
    site_router_map = {str(s["name"]): str(s["router"]) for s in sites}
    site_blocks, link_block = carve_site_blocks(data["ipv6_prefix"], site_names)

    site_64_pools = {}
    for s_name, s_block in site_blocks.items():
        site_obj = next(s for s in sites if str(s["name"]) == s_name)
        lan_count = len(site_obj.get("subnets", []))
        site_64_pools[s_name] = iter(allocate_64s(s_block, lan_count))

    links = data.get("links", [])
    link_64_pool = iter(allocate_64s(link_block, len(links)))

    lan_specs_by_site = {s_name: [] for s_name in site_names}
    subnet_ipv6_map = {}

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
            lan_specs_by_site[s_name].append({
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

    # Compute per-site IPv4 block sizes (sum of LAN block sizes rounded up to power of two)
    site_v4_sizes = {}
    for s_name in site_names:
        lan_sum = sum(1 << (32 - spec["ipv4_prefixlen"]) for spec in lan_specs_by_site[s_name])
        site_v4_sizes[s_name] = _next_power_of_two(lan_sum)

    # Point-to-point links block size: len(links) * 4 rounded up to power of two
    link_v4_size = _next_power_of_two(len(links) * 4) if links else 0

    # Top-level container blocks carved from ipv4_block, largest first
    container_items = [
        (f"site:{s_name}", _prefixlen_for_block_size(site_v4_sizes[s_name]))
        for s_name in site_names
    ]
    if link_v4_size > 0:
        container_items.append(("links", _prefixlen_for_block_size(link_v4_size)))

    carved_containers = _carve_ipv4_subnets(ipv4_block, container_items)
    ipv4_site_nets = {}
    for s_name, net in zip(site_names, carved_containers[: len(site_names)]):
        ipv4_site_nets[s_name] = net

    ipv4_link_net = carved_containers[len(site_names)] if link_v4_size > 0 else None

    # Carve each site's LANs inside its own site block (largest first inside _carve_ipv4_subnets)
    subnet_v4_map = {}
    for s_name in site_names:
        specs = lan_specs_by_site[s_name]
        if specs:
            carved_lans = _carve_ipv4_subnets(
                ipv4_site_nets[s_name],
                [(spec["id"], spec["ipv4_prefixlen"]) for spec in specs],
            )
            for spec, v4_net in zip(specs, carved_lans):
                subnet_v4_map[spec["id"]] = v4_net

    # Carve point-to-point links inside ipv4_link_block
    link_specs = []
    link_subnet_ids = []
    for idx, link in enumerate(links, start=1):
        a_site, b_site, link_name = _extract_link_endpoints(link)
        sub_id = f"link:{idx}:{link_name}"
        ipv6_net = next(link_64_pool)
        subnet_ipv6_map[sub_id] = ipv6_net
        link_subnet_ids.append((sub_id, a_site, b_site))
        link_specs.append({
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

    if link_specs and ipv4_link_net is not None:
        carved_links = _carve_ipv4_subnets(
            ipv4_link_net,
            [(spec["id"], spec["ipv4_prefixlen"]) for spec in link_specs],
        )
        for spec, v4_net in zip(link_specs, carved_links):
            subnet_v4_map[spec["id"]] = v4_net

    all_specs = [spec for s_name in site_names for spec in lan_specs_by_site[s_name]] + link_specs
    subnets_out = []
    subnet_next_host_idx = {}

    for spec in all_specs:
        v4_net = subnet_v4_map[spec["id"]]
        usable = v4_net.num_addresses - 2
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

    # 3. Build routers using router names from input
    routers_out = []
    for s_name in site_names:
        site_lans = [s["id"] for s in subnets_out if s["type"] == "lan" and s["site"] == s_name]
        related_links = [
            sid for sid, a_s, b_s in link_subnet_ids if a_s == s_name or b_s == s_name
        ]
        iface_targets = site_lans + related_links
        if not iface_targets:
            raise ValueError(f"Site {s_name!r} has no LANs or links to assign router interfaces")

        ifaces_out = []
        for iface_num, sub_id in enumerate(iface_targets, start=1):
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
            "name": site_router_map[s_name],
            "site": s_name,
            "interfaces": ifaces_out,
        })

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    result = {
        "organization": data["organization"],
        "ipv4_block": str(ipv4_block),
        "ipv6_prefix": str(ipaddress.IPv6Network(data["ipv6_prefix"], strict=True)),
        "ipv6_sites": {name: str(net) for name, net in site_blocks.items()},
        "ipv6_link_block": str(link_block),
        "ipv4_sites": {name: str(net) for name, net in ipv4_site_nets.items()},
        "subnets": subnets_out,
        "routers": routers_out,
        "metrics": {"allocation_time_ms": round(elapsed_ms, 3)},
    }
    if ipv4_link_net is not None:
        result["ipv4_link_block"] = str(ipv4_link_net)
    return result