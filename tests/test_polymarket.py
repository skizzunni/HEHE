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
        # FanDuel is judged against the two other venues: DraftKings and Polymarket
        import sources
        snap = sources.snapshot("nhl", row(0.6, "-160", "+135"), FD=FD, PM=PM)
        self.assertTrue(all(abs(v["fair"] - round((snap["dk"] + snap["pm"]) / 2, 4)) < 1e-4 for v in home))
        self.assertTrue(abs(snap["dk"] - dk) < 1e-3)
        self.assertTrue(all(v["fair_source"] == "consensus of 2 other venues" for v in home))


class Soccer(unittest.TestCase):
    """Three yes/no markets per game, normalised; club tags (FC, SS) dropped."""
    BOOK = {"ita": [dict(title="SS Lazio vs. FC Internazionale Milano", start="2026-10-28T19:45:00Z", markets=[
        dict(type="moneyline", question="Will SS Lazio win on 2026-10-28?", outcomes='["Yes", "No"]',
             prices='["0.30", "0.70"]', liquidity=20000),
        dict(type="moneyline", question="Will SS Lazio vs. FC Internazionale Milano end in a draw?",
             outcomes='["Yes", "No"]', prices='["0.26", "0.74"]', liquidity=20000),
        dict(type="moneyline", question="Will FC Internazionale Milano win on 2026-10-28?",
             outcomes='["Yes", "No"]', prices='["0.46", "0.54"]', liquidity=20000)]),
        dict(title="SS Lazio vs. FC Internazionale Milano - Total Corners", start="2026-10-28T19:45:00Z", markets=[])]}
    MKT = dict(home="Lazio", away="Internazionale", start="2026-10-28T19:45Z")

    def test_three_way_normalised(self):
        f = lambda spec: P.fair(self.BOOK, "ita", self.MKT, spec)
        self.assertAlmostEqual(f(dict(t="win", team="Lazio")), 0.30 / 1.02, places=4)
        self.assertAlmostEqual(f(dict(t="draw")), 0.26 / 1.02, places=4)
        self.assertAlmostEqual(f(dict(t="win", team="Internazionale")), 0.46 / 1.02, places=4)
        self.assertIsNone(f(dict(t="over", line=2.5)))

    def test_thin_market_gives_nothing(self):
        thin = {"ita": [dict(self.BOOK["ita"][0], markets=[dict(m, liquidity=50) for m in self.BOOK["ita"][0]["markets"]])]}
        self.assertIsNone(P.fair(thin, "ita", self.MKT, dict(t="win", team="Lazio")))


if __name__ == "__main__":
    unittest.main()
