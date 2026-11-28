import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "tools"), os.path.join(os.path.dirname(__file__), "..")]
import both_sides as B  # noqa: E402
import props_ledger as PL  # noqa: E402

GAMES = [{"id": "nfl:1", "match": "A @ B", "props": [
    {"name": "X Y", "market": "Receiving Yards", "line": "13.5", "price": "-113", "imp": 0.53, "p": 0.5,
     "label": "X Y: Over 13.5 Receiving Yards", "two_sided": True},
    {"name": "X Y", "market": "Receiving Yards", "line": "u13.5", "price": "-113", "imp": 0.53, "p": 0.5,
     "label": "X Y: Under 13.5 Receiving Yards", "two_sided": True},
    {"name": "X Y", "market": "Receiving Yards", "line": "50+", "price": "+300", "label": "one-sided"}]}]


class BothSides(unittest.TestCase):
    def test_logs_both_sides_only_two_sided(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "b.json")
            self.assertEqual(B.record("2026-11-26", GAMES, p), 2)
            self.assertEqual(sorted(e["side"] for e in B.load(p).values()), ["over", "under"])
            self.assertEqual(B.record("2026-11-26", GAMES, p), 0)       # first price kept

    def test_started_games_skipped(self):
        now = dt.datetime(2026, 11, 26, 19, tzinfo=dt.timezone.utc)
        rows = [{"start": "2026-11-26T18:00Z"}, {"start": "2026-11-26T21:30Z"}, {"start": None}]
        self.assertEqual(B.not_started(rows, now), [rows[1]])

    def test_grade_uses_own_file_and_restores(self):
        seen = []
        keep = PL.LEDGER
        with patch.object(PL, "grade", lambda: seen.append(PL.LEDGER)):
            B.grade("/x/both.json")
        self.assertEqual(seen, ["/x/both.json"])
        self.assertEqual(PL.LEDGER, keep)

    def test_report_by_side_and_half(self):
        book = {"a": dict(side="under", price="-110", status="won", date="2026-11-01"),
                "b": dict(side="under", price="-110", status="lost", date="2026-11-10"),
                "c": dict(side="over", price="+150", status="won", date="2026-11-10")}
        r = B.report(book)
        self.assertIn("under -150..100: first 1/1 = 100%, return +90.9%; second 0/1 = 0%, return -100.0%", r)
        self.assertIn("over 100..200: second 1/1 = 100%, return +150.0%", r)

    def test_under_grades_as_under(self):
        self.assertTrue(PL.won("nfl", "Receiving Yards", "u13.5", 13))
        self.assertFalse(PL.won("nfl", "Receiving Yards", "u13.5", 14))


class ReviewLine(unittest.TestCase):
    def test_daily_review_line(self):
        import daily_review as DR
        book = {"a": dict(side="over", price="-110", status="won", date="2026-11-26"),
                "b": dict(side="under", price="-110", status="lost", date="2026-11-26"),
                "c": dict(side="under", price="+120", status="won", date="2026-11-26"),
                "d": dict(side="over", price="-110", status="open", date="2026-11-26")}
        self.assertEqual(DR.both_sides_line(book),
                         "Both sides of FanDuel's main prop lines: over 1/1 (100%, return +90.9%), "
                         "under 1/2 (50%, return +10.0%) -- information only until a side holds in both "
                         "date halves (tools/both_sides.py report).")
        self.assertIsNone(DR.both_sides_line({}))

    def test_widest_gap(self):
        import daily_review as DR
        import both_sides as BS
        mk = lambda side, st, lg="nfl", m="Receptions": dict(side=side, price="-110", status=st, league=lg, market=m)
        done = ([mk("under", "won")] * 7 + [mk("under", "lost")] * 3 + [mk("over", "won")] * 3 + [mk("over", "lost")] * 7
                + [mk("under", "won", "nba", "Points")] * 5 + [mk("under", "lost", "nba", "Points")] * 5
                + [mk("over", "won", "nba", "Points")] * 5 + [mk("over", "lost", "nba", "Points")] * 5)
        out = DR.widest_side_gap(done, BS._ret)
        self.assertTrue(out.startswith("; widest gap: nfl Receptions, under 7/10"))
        self.assertIn("vs over 3/10", out)
        self.assertEqual(DR.widest_side_gap(done[:5], BS._ret), "")      # under 10 a side: none


class ByMarket(unittest.TestCase):
    def test_needs_ten_a_side(self):
        mk = lambda side, st: dict(league="nfl", market="Receiving Yards", side=side, price="-110", status=st, date="d")
        book = {f"o{i}": mk("over", "won" if i < 4 else "lost") for i in range(10)}
        book.update({f"u{i}": mk("under", "won" if i < 7 else "lost") for i in range(10)})
        self.assertIn("nfl Receiving Yards: over 4/10 (-23.6%), under 7/10 (+33.6%)", B.by_market(book))
        self.assertIn("no market has 10", B.by_market({}))


class OneDay(unittest.TestCase):
    def test_one_day_has_no_halves(self):
        book = {"a": dict(side="over", price="-110", status="won", date="2026-11-26"),
                "b": dict(side="over", price="-110", status="lost", date="2026-11-26")}
        r = B.report(book)
        self.assertIn("one day so far", r)
        self.assertIn("over -150..100: all 1/2 = 50%", r)
        self.assertNotIn("second", r)


class ByGameTest(unittest.TestCase):
    def test_by_game_counts_games_short(self):
        mk = lambda k, gid, side, st: (k, dict(league="nba", date="2026-11-27", gid=gid, side=side,
                                                status=st, imp=0.5, price="-110"))
        book = dict([mk("a", "nba:1", "over", "lost"), mk("b", "nba:1", "under", "won"),
                     mk("c", "nba:2", "over", "won"), mk("d", "nba:2", "under", "lost"),
                     mk("e", "nba:2", "over", "won")])
        out = B.by_game(book)
        self.assertIn("nba 2026-11-27: over 2/3 vs 1.5 priced", out)
        self.assertIn("under 1/2 vs 1.0 priced (z +0.00", out)
        self.assertIn("overs short in 1 of 2 games", out)
        self.assertEqual(B.by_game({}), "both sides by day: nothing graded yet")

    def test_totals_line(self):
        def get(u):
            eid = u.rsplit("=", 1)[1]
            pts = {"1": ("100", "98"), "2": ("120", "115")}[eid]
            return {"header": {"competitions": [{"competitors": [{"score": pts[0]}, {"score": pts[1]}]}]},
                    "pickcenter": [{"overUnder": 220.5}]}
        mk = lambda k, gid: (k, dict(league="nba", date="2026-11-27", gid=gid, side="over",
                                     status="lost", imp=0.5, price="-110"))
        book = dict([mk("a", "nba:1"), mk("b", "nba:2")])
        self.assertEqual(B.totals_line(book, "nba", "2026-11-27", get),
                         "; games under their total: 1 of 2, final minus total -4.0 a game")
        self.assertIn("games under their total: 1 of 2", B.by_game(book, totals=True, get=get))

if __name__ == "__main__":
    unittest.main()
