"""IPv6 allocation (Sehla). Nibble-aligned: one /52 per site, /64 for every LAN and link.

Layout inside the /48  (the 4th hextet is the 'subnet' field; its first hex digit picks the block):

    2001:db8:1000:1000::/52   site 1   (4096 /64s: 1000..1fff)
    2001:db8:1000:2000::/52   site 2
    ...
    2001:db8:1000:e000::/52   site 14
    2001:db8:1000:f000::/52   all router-to-router links
    2001:db8:1000:0000::/52   left unused on purpose (reserved)

Hint: look up IPv6Network.subnets(new_prefix=...) and ipaddress arithmetic in the Python docs.
"""
import ipaddress
import itertools
from ipaddress import IPv6Network


def carve_site_blocks(ipv6_prefix, site_names):
    """Return (site_blocks, link_block). See the module docstring for the layout."""
    # 1. Parse the prefix. strict=True rejects host bits (2001:db8:1000:1::/48) and
    #    IPv4 text (10.0.0.0/8); both raise a ValueError subclass, which the tests expect.
    try:
        net = ipaddress.IPv6Network(ipv6_prefix, strict=True)
    except ValueError as exc:
        raise ValueError(f"Invalid IPv6 prefix {ipv6_prefix!r}: {exc}") from exc

    # 2. The whole design assumes a /48: splitting it into /52s gives exactly 16 blocks.
    if net.prefixlen != 48:
        raise ValueError(f"IPv6 prefix must be a /48, got /{net.prefixlen}")

    # 3. Site names are dictionary keys, so duplicates would silently overwrite each other.
    if len(set(site_names)) != len(site_names):
        raise ValueError("Duplicate site names")

    # 4. 16 blocks: #0 reserved, #1..#14 for sites, #15 for links -> at most 14 sites.
    if len(site_names) > 14:
        raise ValueError(f"At most 14 sites fit in a /48, got {len(site_names)}")

    # 5. Split the /48 into its sixteen /52 blocks, in address order (0000, 1000, ... f000).
    blocks = list(net.subnets(new_prefix=52))

    # 6. Site number i (starting at 1) takes block i. Block 0 stays unused on purpose.
    site_blocks = {name: blocks[i] for i, name in enumerate(site_names, start=1)}

    # 7. The last block (f000::/52) is for every router-to-router link.
    link_block = blocks[15]
    return site_blocks, link_block


def allocate_64s(block, count):
    """Return `count` consecutive /64 networks from the start of `block`."""
    if count < 0:
        raise ValueError("count cannot be negative")
    if block.prefixlen > 64:
        raise ValueError(f"Block /{block.prefixlen} is smaller than a /64")

    # A /52 holds 2**(64-52) = 4096 /64s; refuse to hand out more than exist.
    capacity = 2 ** (64 - block.prefixlen)
    if count > capacity:
        raise ValueError(f"Block holds only {capacity} /64s, {count} requested")

    # subnets() is a lazy generator, so islice takes just the first `count` items
    # without building all 4096 (or 65536 for a /48) networks.
    return list(itertools.islice(block.subnets(new_prefix=64), count))


def interface_address(subnet, host_index):
    """Return the address `host_index` above the subnet start, as text without a prefix."""
    # Index 0 is the subnet-router anycast address; anything >= num_addresses is outside.
    if host_index < 1 or host_index >= subnet.num_addresses:
        raise ValueError(f"host_index {host_index} is not usable in {subnet}")
    # IPv6Address + int gives another IPv6Address, so there is no manual bit shifting.
    return str(subnet.network_address + host_index)