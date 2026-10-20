"""Item 3: one de-vig for every market (devig.py), old vs new on a known
two-way market."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard                                          # noqa: E402
import devig                                              # noqa: E402


class KnownMarket(unittest.TestCase):
    """-200 / +170: implied 66.67% + 37.04% = 103.70% (3.70% hold)."""

    def test_old_vs_new(self):
        old = devig.fair(-200, 170, method="proportional")
        pw = devig.fair(-200, 170, method="power")
        sh = devig.fair(-200, 170, method="shin")
        self.assertAlmostEqual(old[0], (2 / 3) / (2 / 3 + 100 / 270), places=9)     # 64.29%
        self.assertAlmostEqual(old[0], 0.642857, places=5)
        self.assertAlmostEqual(pw[0], 0.650822, places=5)
        self.assertAlmostEqual(sh[0], 0.648148, places=5)
        # power: both are the implied chances raised to one k
        k = math.log(pw[0]) / math.log(2 / 3)
        self.assertAlmostEqual((100 / 270) ** k, pw[1], places=9)
        # both new methods give the favourite more than proportional does
        self.assertGreater(pw[0], old[0])
        self.assertGreater(sh[0], old[0])
        for p in (old, pw, sh):
            self.assertAlmostEqual(sum(p), 1.0, places=9)

    def test_three_way_sums_to_one(self):
        for m in devig.METHODS:
            self.assertAlmostEqual(sum(devig.fair(-210, 360, 500, method=m)), 1.0, places=9)

    def test_board_uses_the_one_method(self):
        """dashboard.devig is devig.METHOD for every league, no local copy."""
        self.assertEqual(dashboard.devig("-200", "+170"), devig.fair(-200, 170))

    def test_bad_input(self):
        self.assertIsNone(devig.fair(None, 120))
        self.assertIsNone(devig.fair_implied(0.6))


class Reverted(unittest.TestCase):
    """Power everywhere did not beat the old method on the untouched window
    (README item 3), so the board is back to proportional with power for
    college football and basketball."""

    def test_board_method(self):
        self.assertEqual(devig.METHOD, "proportional")
        self.assertEqual(devig.method_for("nhl"), "proportional")
        self.assertEqual(devig.method_for("ncaaf"), "power")
        p = dashboard.devig("-200", "+170", method=devig.method_for("nba"))
        self.assertAlmostEqual(p[0], (2 / 3) / (2 / 3 + 100 / 270), places=9)


if __name__ == "__main__":
    unittest.main()
