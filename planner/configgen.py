"""Turn an addressing plan into FRR router configs and a containerlab topology.

Pipeline:  plan.json  ->  build_model()  ->  Jinja2 templates  ->  files on disk

build_model() does all the thinking (which interface connects to what, which address a test host
gets). The templates only print what the model contains, so they stay simple.
"""
import ipaddress
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
# Verify these tags exist when you first deploy; change them here (or with --frr-image).
DEFAULT_FRR_IMAGE = "quay.io/frrouting/frr:10.2.1"
DEFAULT_HOST_IMAGE = "ghcr.io/hellt/network-multitool"


def slug(text):
    """Make text safe for a containerlab node or lab name: letters, digits and hyphens only."""
    return re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-")


def _first_free_host(net, taken):
    """First usable address in `net` that is not in `taken` (used to pick a test host's address)."""
    for offset in range(1, 20):
        candidate = net.network_address + offset
        if candidate not in net or candidate in taken:
            continue
        if net.version == 4 and candidate == net.broadcast_address:
            continue
        return candidate
    raise ValueError(f"No free host address left in {net}")


def build_model(plan):
    """Return {"routers": [...], "hosts": [...], "links": [(endpoint, endpoint), ...]}.

    - Every LAN gets one test host, connected to its gateway router interface.
    - Every link subnet joins the two router interfaces that share it.
    """
    subnets = {s["id"]: s for s in plan["subnets"]}
    routers, hosts, links = [], [], []
    link_ends = {}  # link subnet id -> its two "Router:ethN" endpoints

    for number, router in enumerate(plan["routers"], start=1):
        interfaces = []
        for iface in router["interfaces"]:
            sub = subnets[iface["subnet_id"]]
            net4 = ipaddress.IPv4Network(sub["ipv4_cidr"])
            net6 = ipaddress.IPv6Network(sub["ipv6_cidr"])
            interfaces.append({
                "name": iface["name"],
                "subnet_id": sub["id"],
                "kind": sub["type"],
                "ipv4_cidr": f"{iface['ipv4']}/{net4.prefixlen}",
                "ipv6_cidr": f"{iface['ipv6']}/{net6.prefixlen}",
            })
            endpoint = f"{router['name']}:{iface['name']}"
            if sub["type"] == "lan":
                host4 = _first_free_host(net4, {ipaddress.IPv4Address(iface["ipv4"])})
                host6 = _first_free_host(net6, {ipaddress.IPv6Address(iface["ipv6"])})
                host = {
                    "name": f"H-{slug(sub['id'])}",
                    "subnet_id": sub["id"],
                    "ipv4": str(host4), "ipv6": str(host6),
                    "ipv4_cidr": f"{host4}/{net4.prefixlen}",
                    "ipv6_cidr": f"{host6}/{net6.prefixlen}",
                    "gw4": iface["ipv4"], "gw6": iface["ipv6"],
                }
                hosts.append(host)
                links.append((endpoint, f"{host['name']}:eth1"))
            else:
                link_ends.setdefault(sub["id"], []).append(endpoint)
        routers.append({
            "name": router["name"], "site": router["site"],
            "router_id": f"192.0.2.{number}",   # any unique dotted quad works as an OSPF router id
            "interfaces": interfaces,
        })

    for subnet_id, ends in link_ends.items():
        if len(ends) != 2:
            raise ValueError(f"Link {subnet_id!r} needs exactly 2 router interfaces, found {len(ends)}")
        links.append((ends[0], ends[1]))
    return {"routers": routers, "hosts": hosts, "links": links}


def _environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
        undefined=StrictUndefined,          # a typo in a template raises an error instead of printing nothing
    )


def default_lab_name(plan):
    return slug(plan["organization"]).lower()[:30] or "lab"


def render_all(plan, out_dir, lab_name=None, frr_image=DEFAULT_FRR_IMAGE, host_image=DEFAULT_HOST_IMAGE):
    """Write configs/<router>/frr.conf, configs/<router>/daemons and topology.clab.yml.

    Returns the list of written paths."""
    out = Path(out_dir)
    env = _environment()
    model = build_model(plan)
    lab_name = lab_name or default_lab_name(plan)
    written = []

    for router in model["routers"]:
        folder = out / "configs" / router["name"]
        folder.mkdir(parents=True, exist_ok=True)
        for template, filename in (("frr.conf.j2", "frr.conf"), ("daemons.j2", "daemons")):
            path = folder / filename
            path.write_text(env.get_template(template).render(router=router), encoding="utf-8")
            written.append(path)

    topology = out / "topology.clab.yml"
    topology.write_text(env.get_template("topology.clab.yml.j2").render(
        lab_name=lab_name, routers=model["routers"], hosts=model["hosts"], links=model["links"],
        frr_image=frr_image, host_image=host_image), encoding="utf-8")
    written.append(topology)
    return written
