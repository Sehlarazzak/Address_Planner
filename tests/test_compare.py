import csv
import tempfile
import unittest
from pathlib import Path

from planner.allocator import allocate
from planner.compare import compare_organization, summarize_plan, write_report_csv
from planner.validate import load_json

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class TestCompare(unittest.TestCase):
    def _handcrafted_small_org(self):
        # Site A: LAN1 needs 50 hosts (/26 -> 64), LAN2 needs 20 hosts (/27 -> 32) => LAN sum 96 => site block /25 (128)
        # Site B: LAN1 needs 10 hosts (/28 -> 16) => LAN sum 16 => site block /28 (16)
        # 1 link needs 2 hosts (/30 -> 4) => link block /30 (4)
        # Total needed = 50 + 20 + 10 + 2 = 82
        # Fixed (/26 for max=50): 4 * 64 = 256 allocated, 174 wasted, 82/256 = 32.03%
        # Flat VLSM (/26 + /27 + /28 + /30): 64 + 32 + 16 + 4 = 116 allocated, 34 wasted, 82/116 = 70.69%
        # Site-aligned reserved blocks: 128 + 16 + 4 = 148 allocated, 66 wasted, 82/148 = 55.41%
        return {
            "organization": "Handcrafted Small",
            "ipv4_block": "10.50.0.0/24",
            "ipv6_prefix": "2001:db8:5000::/48",
            "sites": [
                {
                    "name": "SiteA",
                    "router": "R1",
                    "subnets": [
                        {"name": "lan1", "hosts": 50, "growth_pct": 0},
                        {"name": "lan2", "hosts": 20, "growth_pct": 0},
                    ],
                },
                {
                    "name": "SiteB",
                    "router": "R2",
                    "subnets": [
                        {"name": "lan1", "hosts": 10, "growth_pct": 0},
                    ],
                },
            ],
            "links": [
                {"name": "A-B", "a": "SiteA", "b": "SiteB"},
            ],
        }

    def test_compare_organization_matches_hand_calculated_metrics(self):
        comp = compare_organization(self._handcrafted_small_org())

        self.assertEqual(comp["fixed"]["needed"], 82)
        self.assertEqual(comp["fixed"]["allocated"], 256)
        self.assertEqual(comp["fixed"]["wasted"], 174)
        self.assertEqual(comp["fixed"]["utilization_pct"], 32.03)

        self.assertEqual(comp["flat_vlsm"]["needed"], 82)
        self.assertEqual(comp["flat_vlsm"]["allocated"], 116)
        self.assertEqual(comp["flat_vlsm"]["wasted"], 34)
        self.assertEqual(comp["flat_vlsm"]["utilization_pct"], 70.69)

        self.assertEqual(comp["site_aligned_vlsm"]["needed"], 82)
        self.assertEqual(comp["site_aligned_vlsm"]["allocated"], 148)
        self.assertEqual(comp["site_aligned_vlsm"]["wasted"], 66)
        self.assertEqual(comp["site_aligned_vlsm"]["utilization_pct"], 55.41)

    def test_summarize_plan_routes_before_and_after(self):
        plan = allocate(self._handcrafted_small_org())
        summary = summarize_plan(plan)

        self.assertEqual(summary["routes_before"], 4)
        self.assertEqual(summary["routes_after"], 3)
        self.assertEqual(set(summary["site_summaries"].keys()), {"SiteA", "SiteB"})

    def test_summarize_plan_conflicting_summary_raises(self):
        plan = allocate(self._handcrafted_small_org())
        # Force a link subnet inside SiteA's /25 summary range (10.50.0.0/25)
        for sub in plan["subnets"]:
            if sub["type"] == "link":
                sub["ipv4_cidr"] = "10.50.0.124/30"
                break

        with self.assertRaisesRegex(ValueError, "(?i)conflict"):
            summarize_plan(plan)

    def test_write_report_csv_writes_header_three_rows_and_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "report.csv"
            written = write_report_csv(out_file, data_dir=DATA_DIR, runs=2)
            self.assertTrue(written.exists())

            with open(written, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 3)
            self.assertIn("aligned_allocated", rows[0])
            self.assertIn("aligned_utilization_pct", rows[0])
            self.assertIn("routes_before", rows[0])
            self.assertIn("routes_after", rows[0])

            by_org = {r["organization"]: r for r in rows}
            small = by_org["Small (3 LANs, 2 routers)"]
            self.assertEqual(small["aligned_allocated"], "292")
            self.assertEqual(small["aligned_utilization_pct"], "72.6")


if __name__ == "__main__":
    unittest.main()