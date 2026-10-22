"""Polymarket as a second fair reference: matched by team names and start,
liquid markets only, moneyline / spread / total, averaged into the fair."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polymarket as P                                    # noqa: E402
import value_bets as V                                    # noqa: E402
from test_value_bets import row                           # noqa: E402
from test_venues import FD, START                         # noqa: E402

PM = {"nhl": [dict(title="Bruins vs. Maple Leafs", start=START, markets=[
    dict(question="Bruins vs. Maple Leafs", type="moneyline", outcomes='["Bruins", "Maple Leafs"]',
         prices='["0.38", "0.62"]', liquidity=50000),
    dict(question="Spread: Maple Leafs (-1.5)", type="spreads", outcomes='["Maple Leafs", "Bruins"]',
         prices='["0.40", "0.60"]', liquidity=20000),
    dict(question="Bruins vs. Maple Leafs: O/U 5.5", type="totals", outcomes='["Over", "Under"]',
         prices='["0.55", "0.45"]', liquidity=15000),
    dict(question="Bruins vs. Maple Leafs: O/U 6.5", type="totals", outcomes='["Over", "Under"]',
         prices='["0.35", "0.65"]', liquidity=500)])]}


class Polymarket(unittest.TestCase):
    def setUp(self):
        self.mkt = row(0.6, "-160", "+135")["mkt"]

    def test_moneyline_spread_total(self):
        self.assertEqual(P.fair(PM, "nhl", self.mkt, dict(t="win", team="Toronto Maple Leafs")), 0.62)
        self.assertEqual(P.fair(PM, "nhl", self.mkt, dict(t="spread", team="Toronto Maple Leafs", line=-1.5)), 0.40)
        self.assertEqual(P.fair(PM, "nhl", self.mkt, dict(t="spread", team="Boston Bruins", line=1.5)), 0.60)
        self.assertEqual(P.fair(PM, "nhl", self.mkt, dict(t="under", line=5.5)), 0.45)
        self.assertIsNone(P.fair(PM, "nhl", self.mkt, dict(t="over", line=6.5)))    # thin market: ignored

    def test_unmatched_game(self):
        mkt = dict(self.mkt, home="Ottawa Senators")
        self.assertIsNone(P.fair(PM, "nhl", mkt, dict(t="win", team="Ottawa Senators")))

    def test_averaged_into_the_fair(self):
        import devig
        dk = devig.fair(-160, 135, method="shin")[0]
        val, _ = V.scan("nhl", row(0.6, "-160", "+135"), FD, {}, min_ev=-1, PM=PM)
        home = [v for v in val if v["side"] == "home"]
        self.assertEqual([v["venue"] for v in home], ["FanDuel"])
        self.assertTrue(all(abs(v["fair"] - round((dk + 0.62) / 2, 4)) < 1e-4 for v in home))
        self.assertTrue(all(v["fair_source"] == "DraftKings (Shin) + Polymarket" for v in home))


if __name__ == "__main__":
    unittest.main()
