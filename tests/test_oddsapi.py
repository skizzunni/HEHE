"""oddsapi: off without a key, within its call budget, Pinnacle's Shin fair
as the reference, and extra books in the price comparison."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oddsapi as O                                       # noqa: E402
import value_bets as V                                    # noqa: E402
import venues                                             # noqa: E402
from test_value_bets import row                           # noqa: E402
from test_venues import START                             # noqa: E402

EV = dict(home_team="Toronto Maple Leafs", away_team="Boston Bruins", commence_time=START, bookmakers=[
    dict(key="pinnacle", title="Pinnacle", markets=[dict(key="h2h", outcomes=[
        dict(name="Toronto Maple Leafs", price=1.65), dict(name="Boston Bruins", price=2.35)])]),
    dict(key="betmgm", title="BetMGM", markets=[dict(key="h2h", outcomes=[
        dict(name="Toronto Maple Leafs", price=1.72), dict(name="Boston Bruins", price=2.20)])])])
OA = {"nhl": [EV]}


class OddsApi(unittest.TestCase):
    def test_off_without_a_key(self):
        with mock.patch.dict(os.environ, {"ODDS_API_KEY": ""}):
            self.assertEqual(O.load({"nhl": 5}), {})

    def test_daily_budget(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(O, "CACHE", tmp), \
                mock.patch.object(O, "MAX_CALLS_PER_DAY", 2), \
                mock.patch.dict(os.environ, {"ODDS_API_KEY": "k"}), \
                mock.patch.object(O, "_fetch", lambda sport, k: (calls.append(sport) or [EV], "499")):
            out = O.load({"nhl": 9, "nba": 5, "nfl": 3})
            self.assertEqual(len(calls), 2)                       # the budget, busiest sports first
            self.assertEqual(calls, ["icehockey_nhl", "basketball_nba"])
            self.assertEqual(set(out), {"nhl", "nba"})
            O.load({"nhl": 9, "nba": 5, "nfl": 3})
            self.assertEqual(len(calls), 2)                       # cached and over budget: no new call

    def test_pinnacle_is_the_reference(self):
        import devig
        fair = devig.fair_decimal(1.65, 2.35, method="shin")[0]
        mkt = row(0.6, "-160", "+135")["mkt"]
        self.assertAlmostEqual(O.sharp_fair(OA, "nhl", mkt, "Toronto Maple Leafs"), fair)
        val, _ = V.scan("nhl", row(0.6, "-160", "+135"), {}, {}, OA=OA)
        mgm = [v for v in val if v["venue"] == "BetMGM" and v["side"] == "home"]
        self.assertEqual(len(mgm), 1)                              # 1.72 x 0.596 > 1.01
        self.assertEqual(mgm[0]["fair_source"], "Pinnacle (Shin)")
        self.assertTrue(all(v["venue"] != "Pinnacle" for v in val))

    def test_extra_books_in_the_price_comparison(self):
        out = venues.compare("nhl", row(0.6, "-160", "+135"), "Toronto Maple Leafs", "-160", "DraftKings", {}, {}, OA)
        self.assertEqual([x["venue"] for x in out][:2], ["BetMGM", "Pinnacle"])


if __name__ == "__main__":
    unittest.main()
