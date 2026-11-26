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


if __name__ == "__main__":
    unittest.main()
