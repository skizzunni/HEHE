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


class ByKind(unittest.TestCase):
    def test_props_and_game_lines(self):
        import locks
        legs = [dict(kind="prop", status="won", p=0.8), dict(kind="prop", status="lost", p=0.8), dict(kind=None, status="won", p=0.7)]
        self.assertEqual(locks.by_kind(legs), [dict(kind="player props", won=1, n=2, said=80.0),
                                                dict(kind="game lines", won=1, n=1, said=70.0)])


class Watch(unittest.TestCase):
    def test_kind_short_in_both_halves(self):
        import locks
        legs, days = {}, {}
        for i in range(16):
            d = f"2026-10-{10 + i:02d}"
            k = f"{d}|o"
            legs[k] = dict(league="nba", spec=dict(t="over"), p=0.75, status="won" if i % 2 else "lost")
            days[d] = [k]
        w = locks.watch_kinds(dict(days=days, legs=legs))
        self.assertEqual(w, [dict(league="nba", t="over", won=8, n=16, said=75)])
        for k in legs:
            legs[k]["status"] = "won"
        self.assertEqual(locks.watch_kinds(dict(days=days, legs=legs)), [])


if __name__ == "__main__":
    unittest.main()
