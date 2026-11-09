import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import daily_review  # noqa: E402


def row(day, side, won, conf=70):
    return dict(dc=True, date=day, myside=side, conf=conf, status="won" if won else "lost")


class DcSide(unittest.TestCase):
    def test_split_and_halves(self):
        L = {}
        for i in range(20):
            L[f"h{i}"] = row("2026-10-01" if i < 10 else "2026-10-20", "home", i % 4 != 0)
        for i in range(10):
            L[f"a{i}"] = row("2026-10-01" if i < 5 else "2026-10-20", "away", i < 3)
        L["x"] = dict(row("2026-10-02", "home", False), record_excluded="unpriced")
        L["s"] = dict(row("2026-10-02", "home", False), dc=False)
        out = daily_review.dc_side_line(L, min_n=30)
        self.assertIn("home 75% vs 70% stated on 20", out)
        self.assertIn("away 30% vs 70% stated on 10 (halves 60%, 0%) SHORT", out)
        self.assertNotIn("home 75% vs 70% stated on 20 (halves 70%, 80%) SHORT", out)

    def test_straight_wins_and_draws(self):
        L = {f"h{i}": row("2026-10-01", "home", True) for i in range(30)}
        for k in L.values():
            k["league"] = "epl"
        L["s1"] = dict(row("2026-10-02", "home", False), dc=False, league="epl", scores={"A": 1, "B": 1})
        L["s2"] = dict(row("2026-10-02", "home", False), dc=False, league="epl", scores={"A": 0, "B": 2})
        L["s3"] = dict(row("2026-10-02", "home", True), dc=False, league="epl")
        L["n"] = dict(row("2026-10-02", "home", False), dc=False, league="nba", scores={"A": 9, "B": 9})
        out = daily_review.dc_side_line(L, min_n=30)
        self.assertIn("Straight wins: 33% vs 70% stated on 3; 1 of 2 losses were draws.", out)

    def test_too_few(self):
        self.assertIsNone(daily_review.dc_side_line({"a": row("2026-10-01", "home", True)}))


if __name__ == "__main__":
    unittest.main()
