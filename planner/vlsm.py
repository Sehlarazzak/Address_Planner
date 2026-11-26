"""IPv4 VLSM sizing helpers (Tania).  Start here; the allocator builds on these two functions.

IMPORTANT: use INTEGER arithmetic for growth. In Python, math.ceil(100 * (1 + 10/100)) is 111,
not 110, because 1.1 cannot be stored exactly. One host too many can push a subnet into the
next prefix size and waste half a block. Find out why for yourself before the viva.
"""




def required_hosts(hosts, growth_pct):
    """Hosts needed after growth, rounded UP to a whole number: ceil(hosts * (100+growth)/100).

    Raise ValueError if hosts < 1 or growth_pct < 0.
    """
    if hosts < 1:
        raise ValueError(f"hosts must be at least 1, got {hosts}")
    if growth_pct < 0:
        raise ValueError(f"growth_pct cannot be negative, got {growth_pct}")
    return (hosts * (100 + growth_pct) + 99) // 100


def required_prefix(hosts_needed):
    """Return the longest IPv4 prefix length whose usable host count (2^(32-p) - 2) is at least
    hosts_needed. Never return a prefix longer than /30.

    Raise ValueError if hosts_needed < 1 or more than 2**24 - 2.
    """
    if hosts_needed < 1:
        raise ValueError(f"hosts_needed must be at least 1, got {hosts_needed}")
    if hosts_needed > 2 ** 24 - 2:
        raise ValueError(
            f"hosts_needed {hosts_needed} does not fit in any IPv4 subnet we allow (max {2 ** 24 - 2})"
        )
    host_bits = max(2, (hosts_needed + 1).bit_length())
    return 32 - host_bits