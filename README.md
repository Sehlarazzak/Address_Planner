# IPv4/IPv6 Address Planner (CS3001 Project 16)

Team: Tania (24K-0713) and Sehla Razzak (24K-0575)

## Run the tests (no installs needed)

    python3 -m unittest discover -s tests -v

Failing tests are the to-do list. Turn them green by implementing the functions marked `TODO`,
then write the tests marked `skipTest("TODO ...")`. Target: 0 failures, 0 skipped.

## Layout

    data/      org_small / org_medium / org_large (3 / 6 / 10 LANs), org_sample_15 (4 sites, 15 subnets),
               plan_example_mini.json (hand-written example of the OUTPUT format)
    schemas/   input.schema.json (what the planner reads), plan.schema.json (what it writes)
    planner/   validate.py, ipv6_alloc.py, vlsm.py
    tests/     one test file per module; read them before coding

## Status and ownership

| Item | Owner | Status |
|---|---|---|
| planner/ipv6_alloc.py | Sehla | done |
| validate_input_semantics | Sehla | done |
| _check_plan_ipv6, _check_plan_links (in validate.py) | Sehla | done |
| planner/vlsm.py (required_hosts, required_prefix) | Tania | TODO |
| _check_plan_ipv4 (in validate.py) | Tania | TODO |
| Skipped tests in test_schemas.py (3), test_plan_semantics.py (2), test_vlsm.py (1) | Tania | TODO |
| IPv4 VLSM allocator, fixed-vs-VLSM comparison, summarization, metrics | Tania | TODO |
| CLI entry point, Jinja2 templates, containerlab topology, ping matrix, impairment runs | Sehla | TODO |

Everyone must be able to explain every file. Examiners ask each person about the other's half.

## Git workflow (so we never overwrite each other)

    git pull                              # always first
    git checkout -b tania/vlsm            # your own branch (Sehla: sehla/<topic>)
    ...edit, run tests...
    git add -A
    git commit -m "Implement required_hosts and required_prefix"
    git push -u origin tania/vlsm         # then open a Pull Request into main on GitHub

The other person reviews the Pull Request and merges it. validate.py has separate functions per
person (_check_plan_ipv6 vs _check_plan_ipv4), so Git can merge both edits automatically.

## Decisions to defend in the viva

1. One /52 per site numbered from 1; links share the /52 at nibble f; nibble 0 reserved; max 14 sites.
2. Integer arithmetic for growth (float rounding gives wrong host counts, e.g. 100 hosts at 10%).
3. Every network-specific value comes from the input file; only the allocation policy is fixed in code.
4. Sample blocks are sized so fixed-length subnetting also fits. Showing the case where it does not fit is a bonus result.
5. UNDECIDED: flat vs site-aligned IPv4 allocation (site-aligned is needed for route summarization).

## AI assistance disclosure

Edit this to match your course policy. Draft: "Claude (Anthropic) was used to explain concepts, generate
the starter tests and schemas, and write planner/ipv6_alloc.py and the validators in planner/validate.py.
We reviewed, ran and can explain all code."

## Checklist against the brief

- [ ] VLSM largest-first, growth applied, overlap check
- [x] IPv6 /52 per site, /64 per LAN and link
- [ ] Router configs generated from Jinja2 templates (FRR)
- [ ] Containerlab topology deployed from the generated files
- [ ] Full ping matrix, IPv4 and IPv6, with pass rate
- [ ] Routing tables and at least one traceroute captured
- [ ] Impairments: C1/C2/C3 x 3 runs x 100 pings, mean and standard deviation
- [ ] Utilization and wasted addresses, VLSM vs fixed, for small, medium and large
- [ ] Route count before and after summarization
- [ ] Allocation time measured
- [ ] README, report, presentation; every claim backed by a saved output file