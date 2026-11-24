"""Validation for planner input files and plan files.

Two layers:
  1. STRUCTURE  - does the JSON have the right shape?  (done for you: validate_structure)
  2. SEMANTICS  - do the values make networking sense? (YOU write these two functions)

Both raise ValueError with a readable message on the first problem class they find.
"""
import json
import re
from pathlib import Path

# You will need these in the semantic checks:
import ipaddress  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"

_PY_TYPES = {"object": dict, "array": list, "string": str,
             "integer": int, "number": (int, float), "boolean": bool}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Layer 1: structure (a small JSON-Schema subset checker, standard library only)
# Supports: type, required, properties, additionalProperties:false, items,
#           minItems, maxItems, minLength, minimum, maximum, pattern, enum, $ref.
# The schema files themselves are standard JSON Schema, so you can swap in the
# `jsonschema` package later without touching them.
# --------------------------------------------------------------------------
def _check(schema, data, path, defs, errors):
    if "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    t = schema.get("type")
    if t:
        ok = isinstance(data, _PY_TYPES[t])
        if t in ("integer", "number") and isinstance(data, bool):
            ok = False
        if not ok:
            errors.append(f"{path or '<root>'}: expected {t}")
            return
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(data, str):
        if len(data) < schema.get("minLength", 0):
            errors.append(f"{path}: string too short")
        if "pattern" in schema and not re.search(schema["pattern"], data):
            errors.append(f"{path}: '{data}' does not match pattern {schema['pattern']}")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: {data} is below minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: {data} is above maximum {schema['maximum']}")
    if isinstance(data, list):
        if len(data) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(data):
                _check(schema["items"], item, f"{path}[{i}]", defs, errors)
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path or '<root>'}: missing required field '{key}'")
        props = schema.get("properties", {})
        for key, value in data.items():
            if key in props:
                _check(props[key], value, f"{path}/{key}", defs, errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path or '<root>'}: unexpected field '{key}'")


def validate_structure(data, kind):
    """kind is 'input' or 'plan'. Raises ValueError listing every structural problem."""
    schema = load_json(SCHEMA_DIR / f"{kind}.schema.json")
    errors = []
    _check(schema, data, "", schema.get("$defs", {}), errors)
    if errors:
        raise ValueError("; ".join(errors))


# --------------------------------------------------------------------------
# Layer 2: semantics  --  TODO (you write these)
# --------------------------------------------------------------------------
def validate_input_semantics(data):
    """Raise ValueError if the (structurally valid) input makes no networking sense.

    Rules to enforce:
      1. ipv4_block is a valid IPv4 network written in strict form (10.0.0.5/24 is NOT valid).
      2. ipv6_prefix is a valid IPv6 network, strict, with prefix length exactly 48.
      3. Site names are unique; router names are unique; subnet names are unique within a site.
      4. Every link's a and b name an existing site, and a != b.
      5. No duplicate links (A-B and B-A count as the same link).
      6. The sites form ONE connected graph through the links (no isolated site).
      7. Baseline from the proposal: at least 2 routers and at least 3 subnets in total
         (LANs + links).
    """
    # Rule 1: strict=True rejects host bits (10.10.0.5/23); impossible octets (300) also fail.
    try:
        ipaddress.IPv4Network(data["ipv4_block"], strict=True)
    except ValueError as exc:
        raise ValueError(f"Invalid ipv4_block {data['ipv4_block']!r}: {exc}") from exc

    # Rule 2: valid IPv6 network, and exactly a /48.
    try:
        v6 = ipaddress.IPv6Network(data["ipv6_prefix"], strict=True)
    except ValueError as exc:
        raise ValueError(f"Invalid ipv6_prefix {data['ipv6_prefix']!r}: {exc}") from exc
    if v6.prefixlen != 48:
        raise ValueError(f"ipv6_prefix must be a /48, got /{v6.prefixlen}")

    # Rule 3: uniqueness. A set drops duplicates, so a shorter set means a duplicate existed.
    sites = data["sites"]
    site_names = [site["name"] for site in sites]
    if len(set(site_names)) != len(site_names):
        raise ValueError("Duplicate site names")
    router_names = [site["router"] for site in sites]
    if len(set(router_names)) != len(router_names):
        raise ValueError("Duplicate router names")
    for site in sites:  # subnet names only need to be unique INSIDE one site
        subnet_names = [lan["name"] for lan in site["subnets"]]
        if len(set(subnet_names)) != len(subnet_names):
            raise ValueError(f"Duplicate subnet name inside site {site['name']!r}")

    # Rules 4 and 5: check each link, and build the neighbour map for rule 6 as we go.
    known_sites = set(site_names)
    neighbours = {name: set() for name in site_names}
    seen_links = set()
    for link in data["links"]:
        a, b = link["a"], link["b"]
        if a not in known_sites or b not in known_sites:
            raise ValueError(f"Link {link['name']!r} refers to an unknown site")
        if a == b:
            raise ValueError(f"Link {link['name']!r} connects site {a!r} to itself")
        pair = frozenset({a, b})  # A-B and B-A give the same frozenset
        if pair in seen_links:
            raise ValueError(f"Duplicate link between {a!r} and {b!r}")
        seen_links.add(pair)
        neighbours[a].add(b)
        neighbours[b].add(a)

    # Rule 6: walk the graph from the first site, visiting every neighbour not seen yet.
    visited = {site_names[0]}
    todo = [site_names[0]]
    while todo:
        current = todo.pop()
        for other in neighbours[current]:
            if other not in visited:
                visited.add(other)
                todo.append(other)
    if visited != known_sites:
        unreachable = sorted(known_sites - visited)
        raise ValueError(f"Sites are not all connected; cannot reach: {unreachable}")

    # Rule 7: baseline from the proposal.
    total_subnets = sum(len(site["subnets"]) for site in sites) + len(data["links"])
    if len(sites) < 2 or total_subnets < 3:
        raise ValueError("Need at least 2 routers and 3 subnets in total")


def validate_plan_semantics(data):
    """Raise ValueError if a plan is internally inconsistent. This is your overlap detector.

    The work is split so Sehla and Tania edit DIFFERENT functions (no Git conflicts):
      _check_plan_links  - shared, already written
      _check_plan_ipv6   - Sehla, written
      _check_plan_ipv4   - Tania, TODO
    The IPv6 check runs before the IPv4 one on purpose.
    """
    subnets = {}
    for sub in data["subnets"]:
        if sub["id"] in subnets:
            raise ValueError(f"Duplicate subnet id {sub['id']!r}")
        subnets[sub["id"]] = sub
    _check_plan_links(data, subnets)
    _check_plan_ipv6(data, subnets)
    _check_plan_ipv4(data, subnets)


def _check_plan_links(data, subnets):
    """Shared rule: every interface points at a real subnet; a LAN has exactly 1 router
    interface (its gateway) and a link has exactly 2 (one per end)."""
    ends = {sid: 0 for sid in subnets}
    for router in data["routers"]:
        for iface in router["interfaces"]:
            if iface["subnet_id"] not in subnets:
                raise ValueError(
                    f"Interface {router['name']}:{iface['name']} points at unknown subnet "
                    f"{iface['subnet_id']!r}")
            ends[iface["subnet_id"]] += 1
    for sid, sub in subnets.items():
        wanted = 1 if sub["type"] == "lan" else 2
        if ends[sid] != wanted:
            raise ValueError(
                f"Subnet {sid!r} ({sub['type']}) has {ends[sid]} router interface(s), "
                f"needs exactly {wanted}")


def _check_plan_ipv6(data, subnets):
    """Sehla's half. Rules: every ipv6_cidr is a strict /64 inside ipv6_prefix; no two overlap;
    a LAN lies inside its site's /52, a link inside ipv6_link_block; every interface IPv6
    address lies inside its subnet; no IPv6 address is used twice."""
    try:
        prefix = ipaddress.IPv6Network(data["ipv6_prefix"], strict=True)
        link_block = ipaddress.IPv6Network(data["ipv6_link_block"], strict=True)
        site_blocks = {name: ipaddress.IPv6Network(cidr, strict=True)
                       for name, cidr in data["ipv6_sites"].items()}
    except ValueError as exc:
        raise ValueError(f"Invalid IPv6 block in plan: {exc}") from exc

    nets = {}  # subnet id -> IPv6Network, kept for the interface checks below
    for sub in data["subnets"]:
        try:
            net = ipaddress.IPv6Network(sub["ipv6_cidr"], strict=True)
        except ValueError as exc:
            raise ValueError(f"Subnet {sub['id']!r} has invalid ipv6_cidr: {exc}") from exc
        if net.prefixlen != 64:
            raise ValueError(f"Subnet {sub['id']!r}: IPv6 subnet must be a /64, got /{net.prefixlen}")
        if not net.subnet_of(prefix):
            raise ValueError(f"Subnet {sub['id']!r}: {net} is outside {prefix}")

        if sub["type"] == "lan":
            block = site_blocks.get(sub["site"])
            if block is None:
                raise ValueError(f"Subnet {sub['id']!r}: site {sub['site']!r} has no /52 in ipv6_sites")
            if not net.subnet_of(block):
                raise ValueError(f"Subnet {sub['id']!r}: {net} is outside its site's /52 {block}")
        elif not net.subnet_of(link_block):
            raise ValueError(f"Subnet {sub['id']!r}: link {net} is outside the link block {link_block}")

        for other_id, other in nets.items():
            if net.overlaps(other):
                raise ValueError(f"IPv6 overlap between {sub['id']!r} and {other_id!r}")
        nets[sub["id"]] = net

    used = set()
    for router in data["routers"]:
        for iface in router["interfaces"]:
            try:
                addr = ipaddress.IPv6Address(iface["ipv6"])
            except ValueError as exc:
                raise ValueError(f"Bad IPv6 address {iface['ipv6']!r}: {exc}") from exc
            if addr not in nets[iface["subnet_id"]]:
                raise ValueError(
                    f"{router['name']}:{iface['name']} address {addr} is outside "
                    f"{nets[iface['subnet_id']]}")
            if addr in used:
                raise ValueError(f"Duplicate IPv6 address {addr} (already used elsewhere)")
            used.add(addr)


def _check_plan_ipv4(data, subnets):
    """Validate IPv4 subnets, overlaps, host capacity, and interfaces."""
    try:
        block = ipaddress.IPv4Network(data["ipv4_block"], strict=True)
    except ValueError as exc:
        raise ValueError(f"Invalid ipv4_block in plan: {exc}") from exc

    nets = {}
    for sid, sub in subnets.items():
        try:
            net = ipaddress.IPv4Network(sub["ipv4_cidr"], strict=True)
        except ValueError as exc:
            raise ValueError(f"Subnet {sid!r} has invalid ipv4_cidr {sub['ipv4_cidr']!r}: {exc}") from exc
        if not net.subnet_of(block):
            raise ValueError(f"Subnet {sid!r}: {net} is outside the block {block}")
        if net.prefixlen != sub["ipv4_prefixlen"]:
            raise ValueError(
                f"Subnet {sid!r}: ipv4_prefixlen {sub['ipv4_prefixlen']} does not match {net}"
            )
        real_usable = net.num_addresses - 2
        if sub["ipv4_usable"] != real_usable:
            raise ValueError(
                f"Subnet {sid!r}: ipv4_usable is {sub['ipv4_usable']} but {net} has {real_usable}"
            )
        if sub["ipv4_usable"] < sub["hosts_required"]:
            raise ValueError(
                f"Subnet {sid!r}: {net} has {sub['ipv4_usable']} usable addresses, "
                f"but {sub['hosts_required']} are required"
            )
        nets[sid] = net

    ordered = sorted(nets.items(), key=lambda kv: (int(kv[1].network_address), kv[1].prefixlen))
    for (id_a, a), (id_b, b) in zip(ordered, ordered[1:]):
        if a.overlaps(b):
            raise ValueError(f"IPv4 overlap between {id_a!r} ({a}) and {id_b!r} ({b})")

    used = set()
    for router in data["routers"]:
        for iface in router["interfaces"]:
            where = f"{router['name']}:{iface['name']}"
            try:
                addr = ipaddress.IPv4Address(iface["ipv4"])
            except ValueError as exc:
                raise ValueError(f"{where} has bad IPv4 address {iface['ipv4']!r}: {exc}") from exc
            net = nets[iface["subnet_id"]]
            if addr not in net:
                raise ValueError(f"{where} address {addr} is outside its subnet {net}")
            if addr == net.network_address:
                raise ValueError(f"{where} address {addr} is the network address of {net}")
            if addr == net.broadcast_address:
                raise ValueError(f"{where} address {addr} is the broadcast address of {net}")
            if addr in used:
                raise ValueError(f"Duplicate IPv4 address {addr} (already used elsewhere)")
            used.add(addr)