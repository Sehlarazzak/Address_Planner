# IPv4/IPv6 Address Planner (CS3001 Project 16)

Team: Tania (24K-0713) and Sehla Razzak (24K-0575)

## Setup and tests

    pip install -r requirements.txt          # jinja2 and pyyaml
    python3 -m unittest discover -s tests -v

Failing tests are the to-do list. Turn them green by implementing the functions marked `TODO`,
then write the tests marked `skipTest("TODO ...")`. Target: 0 failures, 0 skipped.

## Layout

    data/        org_small / org_medium / org_large (3 / 6 / 10 LANs), org_sample_15 (4 sites, 15 subnets),
                 plan_example_mini.json (hand-written example of the plan format)
    schemas/     input.schema.json (what the planner reads), plan.schema.json (what it writes)
    planner/     validate.py, ipv6_alloc.py, vlsm.py, configgen.py, pingmatrix.py, cli.py
    planner/templates/   frr.conf.j2, daemons.j2, topology.clab.yml.j2  (Jinja2)
    tests/       one test file per module; read them before coding

## Commands

    python3 -m planner.cli validate   --input data/org_small.json
    python3 -m planner.cli allocate   --input data/org_small.json --out plan.json     # needs Tania's allocator
    python3 -m planner.cli render     --plan data/plan_example_mini.json --out build
    python3 -m planner.cli pingmatrix --plan data/plan_example_mini.json --csv build/results.csv
    python3 -m planner.cli pingmatrix --plan data/plan_example_mini.json --dry-run    # print commands only

## Running the lab (Linux, or WSL2 on Windows)

Containerlab needs Linux and Docker. On Windows use WSL2 and clone this repo INSIDE the WSL home
folder (not /mnt/d), because bind-mounting files from the Windows drive can fail.

    python3 -m planner.cli render --plan data/plan_example_mini.json --out build
    sudo containerlab deploy -t build/topology.clab.yml
    # wait ~30 s for OSPF to converge, then:
    python3 -m planner.cli pingmatrix --plan data/plan_example_mini.json --csv build/results.csv
    docker exec clab-<lab-name>-R1 vtysh -c "show ip route"        # evidence for the report
    docker exec clab-<lab-name>-R1 vtysh -c "show ipv6 route"
    sudo containerlab destroy -t build/topology.clab.yml --cleanup

The lab name is printed by `render` and appears as `name:` in the topology file. The FRR and host image
tags in configgen.py are defaults; check they exist and change them with --frr-image / --host-image.

## Status and ownership

| Item | Owner | Status |
|---|---|---|
| ipv6_alloc.py, validate_input_semantics, _check_plan_ipv6, _check_plan_links | Sehla | done |
| configgen.py + templates, pingmatrix.py, cli.py (render, validate, pingmatrix) | Sehla | written; first real deployment not yet done |
| vlsm.py (required_hosts, required_prefix) | Tania | TODO |
| _check_plan_ipv4 (in validate.py) | Tania | TODO |
| Skipped tests: test_schemas.py (3), test_plan_semantics.py (2), test_vlsm.py (1) | Tania | TODO |
| IPv4 VLSM allocator (planner/allocator.py with allocate(data) -> plan), fixed-vs-VLSM comparison, summarization, metrics, CSV | Tania | TODO |
| Impairment experiments (netem), captures, report | Both | TODO |

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
5. OSPFv2 + OSPFv3, single area 0, LAN-facing interfaces passive, links point-to-point.
6. One test host per LAN; the ping matrix is host-to-host, both IPv4 and IPv6.
7. UNDECIDED: flat vs site-aligned IPv4 allocation (site-aligned is needed for route summarization).

## AI assistance disclosure

Edit this to match your course policy. Draft: "Claude (Anthropic) was used to explain concepts and to
write starter tests, schemas, planner/ipv6_alloc.py, the validators in planner/validate.py, and the
config generator, ping matrix and CLI. We reviewed, ran and can explain all code."

## Checklist against the brief

- [ ] VLSM largest-first, growth applied, overlap check
- [x] IPv6 /52 per site, /64 per LAN and link
- [x] Router configs generated from Jinja2 templates (FRR)  (verify on a real deployment)
- [x] Containerlab topology generated from the plan  (verify on a real deployment)
- [ ] Containerlab topology deployed and OSPF converged
- [ ] Full ping matrix, IPv4 and IPv6, with pass rate (script written; run it on the lab)
- [ ] Routing tables and at least one traceroute captured
- [ ] Impairments: C1/C2/C3 x 3 runs x 100 pings, mean and standard deviation
- [ ] Utilization and wasted addresses, VLSM vs fixed, for small, medium and large
- [ ] Route count before and after summarization
- [ ] Allocation time measured
- [ ] README, report, presentation; every claim backed by a saved output file
