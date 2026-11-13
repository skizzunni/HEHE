import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import daily_review as dr                                         # noqa: E402


def leg(day, mk, won, p=0.8, lg="nfl", kind="prop"):
    return dict(date=day, market=mk, league=lg, kind=kind, p=p, status="won" if won else "lost")


class PropMarkets(unittest.TestCase):
    def test_line(self):
        L = []
        for i in range(10):                     # early half
            L.append(leg("2026-10-01", "Receiving Yards", i < 6))          # 6/10 vs 80%: short
            L.append(leg("2026-10-01", "Assists", True, lg="nba"))
        for i in range(10):                     # late half
            L.append(leg("2026-10-20", "Receiving Yards", i < 7))          # 7/10: short
            L.append(leg("2026-10-20", "Assists", i < 9, lg="nba"))
        L.append(leg("2026-10-20", "Winner", True, kind="game"))          # not a prop: ignored
        out = dr.locks_prop_market_line(L)
        self.assertIn("NFL Receiving Yards 6/10 then 7/10 (vs 80%, 80%)", out)
        self.assertIn("NBA Assists 10/10 then 9/10", out)
        self.assertTrue(out.endswith("Short in both halves: NFL Receiving Yards."))

    def test_too_few(self):
        self.assertIsNone(dr.locks_prop_market_line([leg("2026-10-01", "Assists", True)] * 5))
        self.assertIsNone(dr.locks_prop_market_line([]))


if __name__ == "__main__":
    unittest.main()
