"""IPv4 sizing tests (Tania). They FAIL until planner/vlsm.py is implemented."""
import unittest

from tests.helpers import ROOT  # noqa: F401
from planner.vlsm import required_hosts, required_prefix


class TestRequiredHosts(unittest.TestCase):
    def test_known_values_from_the_proposal(self):
        self.assertEqual(required_hosts(100, 20), 120)
        self.assertEqual(required_hosts(50, 20), 60)
        self.assertEqual(required_hosts(25, 20), 30)

    def test_fractions_round_up(self):
        self.assertEqual(required_hosts(12, 20), 15)     # 14.4 -> 15
        self.assertEqual(required_hosts(28, 20), 34)     # 33.6 -> 34

    def test_float_trap(self):
        # math.ceil(100 * (1 + 10/100)) gives 111 because of floating point; exactly 110 is right.
        self.assertEqual(required_hosts(100, 10), 110)
        self.assertEqual(required_hosts(50, 10), 55)

    def test_zero_growth(self):
        self.assertEqual(required_hosts(2, 0), 2)

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            required_hosts(0, 20)
        with self.assertRaises(ValueError):
            required_hosts(10, -1)


class TestRequiredPrefix(unittest.TestCase):
    def test_exact_fits(self):
        self.assertEqual(required_prefix(126), 25)
        self.assertEqual(required_prefix(62), 26)
        self.assertEqual(required_prefix(30), 27)
        self.assertEqual(required_prefix(14), 28)
        self.assertEqual(required_prefix(2), 30)

    def test_one_over_needs_the_next_size_up(self):
        self.assertEqual(required_prefix(127), 24)
        self.assertEqual(required_prefix(63), 25)
        self.assertEqual(required_prefix(31), 26)
        self.assertEqual(required_prefix(15), 27)
        self.assertEqual(required_prefix(3), 29)

    def test_never_longer_than_30(self):
        self.assertEqual(required_prefix(1), 30)

    def test_large_networks(self):
        self.assertEqual(required_prefix(300), 23)
        self.assertEqual(required_prefix(2 ** 24 - 2), 8)

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            required_prefix(0)
        with self.assertRaises(ValueError):
            required_prefix(2 ** 24 - 1)

    # ---- TODO (you write this) ------------------------------------------------------
    def test_todo_every_sample_lan_gets_a_prefix_that_fits(self):
        self.skipTest("TODO: for every LAN in every data/org_*.json, compute required_prefix("
                      "required_hosts(...)) and assert usable hosts >= hosts_required")


if __name__ == "__main__":
    unittest.main()
