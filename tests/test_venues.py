"""Where a pick pays most: the same straight-win bet at DraftKings, FanDuel
and Kalshi (with its fee), best first."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import venues as V                                        # noqa: E402

START = "2026-10-22T23:00Z"
ROW = dict(mkt=dict(home="Toronto Maple Leafs", away="Boston Bruins", home_abbr="TOR", away_abbr="BOS", start=START))
FD = {"nhl": [dict(home="Toronto Maple Leafs", away="Boston Bruins", id="9", start=START,
                   ml={"Toronto Maple Leafs": "m:1", "Boston Bruins": "m:2"},
                   px={"m:1": "-140", "m:2": "+120"}, spread={}, total={})]}
KB = {"nhl": {"26OCT22BOSTOR": {"GAME": [
    dict(ticker="KXNHLGAME-26OCT22BOSTOR-TOR", yes="Toronto", yes_ask=0.60, no_ask=0.41,
         event="KXNHLGAME-26OCT22BOSTOR", series="KXNHLGAME"),
    dict(ticker="KXNHLGAME-26OCT22BOSTOR-BOS", yes="Boston", yes_ask=0.41, no_ask=0.60,
         event="KXNHLGAME-26OCT22BOSTOR", series="KXNHLGAME")]}}}


class Venues(unittest.TestCase):
    def test_kalshi_fee(self):
        # 100 contracts at 60c: 0.07 x 100 x 0.6 x 0.4 = $1.68 -> 1.68c each
        self.assertAlmostEqual(V.kalshi_dec(0.60), 1 / (0.60 + 0.0168))
        self.assertIsNone(V.kalshi_dec(1.0))

    def test_best_first_across_three_venues(self):
        out = V.compare("nhl", ROW, "Toronto Maple Leafs", "-160", "DraftKings", FD, KB)
        # FanDuel -140 (1.714) > DraftKings -160 (1.625) > Kalshi 60c + 1.68c fee (1.621)
        self.assertEqual([x["venue"] for x in out], ["FanDuel", "DraftKings", "Kalshi"])
        self.assertAlmostEqual(out[0]["dec"], round(1 + 100 / 140, 4))
        self.assertAlmostEqual(out[2]["dec"], round(1 / 0.6168, 4))

    def test_missing_venues_leave_the_listed_price(self):
        out = V.compare("nhl", ROW, "Toronto Maple Leafs", "-160", "DraftKings", {}, {})
        self.assertEqual([x["venue"] for x in out], ["DraftKings"])

    def test_expected_return(self):
        self.assertEqual(V.expected_per_100(0.6, 1 / 0.6), 0.0)
        self.assertLess(V.expected_per_100(0.6, 1.625), 0)


if __name__ == "__main__":
    unittest.main()
