import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import blind_model as bm  # noqa: E402
import slate_sheet as S  # noqa: E402


def ev(home, away):
    return {"id": "1", "date": "2026-11-24T00:00Z", "competitions": [{"neutralSite": False, "competitors": [
        {"homeAway": "home", "team": {"abbreviation": home}}, {"homeAway": "away", "team": {"abbreviation": away}}]}]}


class SheetTest(unittest.TestCase):
    def setUp(self):
        games = [dict(id=str(i), date=f"2026-11-{1 + i:02d}", home="AAA", away="BBB", hs=110, as_=100, neutral=False)
                 for i in range(10)]
        self.m = bm.fit(games, "2026-11-20", 1, 999)

    def test_blind_first_then_market(self):
        pc = {"pickcenter": [{"details": "AAA -6.5", "overUnder": 220.5,
                              "homeTeamOdds": {"moneyLine": -250}, "awayTeamOdds": {"moneyLine": 205}}]}
        r = S.row("nba", self.m, ev("AAA", "BBB"), pc)
        self.assertGreater(r["blind_home"], 0.5)
        self.assertAlmostEqual(r["market_home"], round(bm._ip(-250) / (bm._ip(-250) + bm._ip(205)), 3))
        t = S.text(r)
        self.assertLess(t.index("blind:"), t.index("then the line"))
        self.assertIn("gap", t)

    def test_missing_team_and_line(self):
        r = S.row("nba", self.m, ev("AAA", "ZZZ"), {})
        t = S.text(r)
        self.assertIn("no number", t)
        self.assertIn("not posted", t)
        self.assertNotIn("gap", t)


    def test_utah_alias_only_for_nhl(self):
        games = [dict(id=str(i), date=f"2026-11-{1 + i:02d}", home="UTA", away="BBB", hs=4, as_=2, neutral=False) for i in range(10)]
        m = bm.fit(games, "2026-11-20", 1, 999)
        self.assertIsNotNone(S.row("nhl", m, ev("UTAH", "BBB"), {})["blind_home"])
        self.assertIsNone(S.row("nba", m, ev("UTAH", "BBB"), {})["blind_home"])


if __name__ == "__main__":
    unittest.main()
