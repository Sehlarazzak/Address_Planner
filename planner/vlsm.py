"""IPv4 VLSM sizing helpers (Tania).  Start here; the allocator builds on these two functions.

IMPORTANT: use INTEGER arithmetic for growth. In Python, math.ceil(100 * (1 + 10/100)) is 111,
not 110, because 1.1 cannot be stored exactly. One host too many can push a subnet into the
next prefix size and waste half a block. Find out why for yourself before the viva.
"""


def required_hosts(hosts, growth_pct):
    """Hosts needed after growth, rounded UP to a whole number: ceil(hosts * (100+growth)/100).

    Raise ValueError if hosts < 1 or growth_pct < 0.
    """
    raise NotImplementedError("TODO: implement required_hosts")


def required_prefix(hosts_needed):
    """Return the longest IPv4 prefix length whose usable host count (2^(32-p) - 2) is at least
    hosts_needed. Never return a prefix longer than /30.

    Raise ValueError if hosts_needed < 1 or more than 2**24 - 2.
    """
    raise NotImplementedError("TODO: implement required_prefix")
