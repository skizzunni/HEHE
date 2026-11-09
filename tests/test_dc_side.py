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


class DcBands(unittest.TestCase):
    def test_band_short_in_both_halves(self):
        L = {}
        for i in range(40):
            L[f"a{i}"] = row("2026-10-01" if i < 20 else "2026-10-20", "home", i % 2 == 0, conf=82)
        for i in range(40):
            L[f"b{i}"] = row("2026-10-01" if i < 20 else "2026-10-20", "home", True, conf=72)
        out = daily_review.dc_side_line(L)
        self.assertIn("Short in both halves: 80-100% (50%, then 50%).", out)
        self.assertNotIn("70-75%", out)


class TrailingPool(unittest.TestCase):
    def test_locks_prop_gets_pool(self):
        P = {f"p{i}": dict(league="nfl", status="won" if i % 4 else "lost", p=0.76) for i in range(200)}
        a = dict(name="locks nfl prop", hit=50.0, said=79.7, n=10)
        out = daily_review.trailing_line(a, P)
        self.assertIn("all 200 saved NFL prop lines 150/200 (75% vs 76% stated) -- the pool is on par", out)
        P2 = {f"p{i}": dict(league="nfl", status="won" if i % 2 else "lost", p=0.76) for i in range(200)}
        self.assertIn("the pool is short too", daily_review.trailing_line(a, P2))
        self.assertNotIn("saved", daily_review.trailing_line(dict(name="calls nba", hit=50, said=70, n=40), P))


class PoolCtx(unittest.TestCase):
    def test_card_caution_gets_pool(self):
        F = {("nba", "over"): dict(league="nba", t="over", won=515, n=625, said=81.7, since="2026-11-02")}
        self.assertEqual(daily_review.pool_ctx(dict(league="nba", t="over", where="Locks"), F),
                         " (all saved lines since 2026-11-02: 515/625, 82% vs 82% -- pool on par)")
        F2 = {("nba", "over"): dict(league="nba", t="over", won=450, n=625, said=81.7, since="2026-11-02")}
        self.assertIn("pool short too", daily_review.pool_ctx(dict(league="nba", t="over", where="Safe Locks"), F2))
        self.assertEqual(daily_review.pool_ctx(dict(league="nba", t="over", where="all saved lines"), F), "")
        self.assertEqual(daily_review.pool_ctx(dict(league="nhl", t="over", where="Locks"), F), "")


if __name__ == "__main__":
    unittest.main()
