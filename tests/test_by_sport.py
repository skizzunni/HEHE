"""By-sport breakdowns of the records: Locks / Safe Locks legs by league."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import locks                                              # noqa: E402


class LocksBySport(unittest.TestCase):
    def test_graded_legs_by_league_most_first(self):
        legs = [dict(league="nhl", status="won"), dict(league="nhl", status="lost"), dict(league="nhl", status="won"),
                dict(league="nba", status="won")]
        self.assertEqual(locks.by_sport(legs), [dict(sport="nhl", won=2, n=3), dict(sport="nba", won=1, n=1)])

    def test_report_counts_only_graded_legs(self):
        path = tempfile.mktemp(suffix=".json")
        book = {"days": {"2026-11-03": ["a", "b", "c"]},
                "legs": {"a": dict(league="nhl", status="won", p=0.8, price="-300"),
                         "b": dict(league="nhl", status="open", p=0.8, price="-300"),
                         "c": dict(league="nfl", status="lost", p=0.8, price="-300")}}
        locks.save(book, path)
        try:
            r = locks.report(path)
        finally:
            os.remove(path)
        self.assertEqual(r["by_sport"], [dict(sport="nhl", won=1, n=1), dict(sport="nfl", won=0, n=1)])


if __name__ == "__main__":
    unittest.main()
