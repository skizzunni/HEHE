"""Price-source scoreboard: per-game no-vig home chance from every venue,
kept at the last pre-start snapshot, graded, and scored against DraftKings."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sources as S                                       # noqa: E402
from test_venues import FD, KB, START                     # noqa: E402

ROW = dict(id="nhl:1", mkt=dict(home="Toronto Maple Leafs", away="Boston Bruins", start=START),
           legs=[dict(side="home", price="-160"), dict(side="away", price="+135")])
BEFORE = dt.datetime(2026, 10, 22, 20, tzinfo=dt.timezone.utc)


class Snapshot(unittest.TestCase):
    def test_every_source_is_a_home_chance(self):
        p = S.snapshot("nhl", ROW, FD=FD, KB=KB)
        self.assertEqual(set(p), {"dk", "fd", "kalshi", "blend"})
        # Kalshi 60c home, 41c away -> 0.60 / 1.01
        self.assertAlmostEqual(p["kalshi"], round(0.60 / 1.01, 4))
        for k in ("dk", "fd"):
            self.assertTrue(0.5 < p[k] < 0.62, (k, p[k]))
        self.assertAlmostEqual(p["blend"], round((p["dk"] + p["fd"] + p["kalshi"]) / 3, 4), places=3)

    def test_three_way_market_is_skipped(self):
        row = dict(ROW, legs=ROW["legs"] + [dict(side="draw", price="+300")])
        self.assertEqual(S.snapshot("nhl", row, FD=FD, KB=KB), {})


class RecordAndScore(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_started_games_are_frozen(self):
        self.assertEqual(S.record({"nhl": [ROW]}, now=BEFORE, path=self.path, FD=FD, KB=KB), 1)
        after = dt.datetime(2026, 10, 23, 1, tzinfo=dt.timezone.utc)
        self.assertEqual(S.record({"nhl": [ROW]}, now=after, path=self.path, FD={}, KB={}), 0)
        self.assertIn("fd", S.load(self.path)["games"]["nhl:1"]["p"])

    def test_scores_the_better_source_on_the_same_games(self):
        # 40 games: source fd always nearer the truth than dk
        book = {"games": {}}
        for i in range(40):
            y = i % 2
            book["games"][f"g{i}"] = dict(home="H", away="A", status="graded", home_won=y,
                                          p=dict(dk=0.5, fd=0.7 if y else 0.3))
        S.save(book, self.path)
        r = {x["source"]: x for x in S.report(self.path)["sources"]}
        self.assertEqual(r["fd"]["n"], 40)
        self.assertAlmostEqual(r["fd"]["brier"], 0.09)
        self.assertAlmostEqual(r["fd"]["brier_dk"], 0.25)
        self.assertTrue(r["fd"]["better"])

    def test_grade_from_ledger_winner(self):
        S.record({"nhl": [ROW]}, now=BEFORE, path=self.path, FD=FD, KB=KB)
        S.grade({"nhl:1": dict(status="won", winner="Boston Bruins")}, self.path)
        g = S.load(self.path)["games"]["nhl:1"]
        self.assertEqual((g["status"], g["home_won"]), ("graded", 0))


if __name__ == "__main__":
    unittest.main()


class Best(unittest.TestCase):
    def test_only_a_proven_source_is_best(self):
        path = tempfile.mktemp(suffix=".json")
        book = {"games": {}}
        for i in range(250):
            y = i % 2
            book["games"][f"g{i}"] = dict(home="H", away="A", status="graded", home_won=y,
                                          p=dict(dk=0.5, fd=0.7 if y else 0.3, kalshi=0.5))
        S.save(book, path)
        self.assertEqual(S.best(path), "fd")
        self.assertIsNone(S.best(path, min_n=300))           # not enough games
        os.remove(path)
