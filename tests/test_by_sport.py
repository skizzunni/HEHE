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


class WatchPool(unittest.TestCase):
    def test_short_in_both_halves_across_the_pools(self):
        import locks
        legs = []
        days = [f"2026-10-{10 + i:02d}" for i in range(10)]
        for i, d in enumerate(days):
            for j in range(12):                    # 120 NHL unders at 80%, ~70% won (home 2 away 1)
                legs.append((d, dict(gid=f"nhl:{i}-{j}", label="Under 2.5 goals", p=0.80, home="H", away="A",
                                     spec=dict(t="under", line=2.5 if j % 10 < 7 else 3.5 - 2), league="nhl")))
        pools = {}
        for d, L in legs:
            pools.setdefault(d, {"legs": []})["legs"].append(L)
        led = {L["gid"]: dict(status="won", scores={"H": 2, "A": 1} if L["spec"]["line"] == 2.5 else {"H": 2, "A": 2})
               for _, L in legs}
        orig = locks.load
        locks.load = lambda path=None: {"pools": pools}
        try:
            got = locks.watch_pool(paths=(None,), led=led)
        finally:
            locks.load = orig
        self.assertEqual([(w["league"], w["t"], w["n"]) for w in got], [("nhl", "under", 120)])


class KindRecord(unittest.TestCase):
    def test_game_lines_by_type_props_by_market(self):
        import locks
        book = {"legs": {"a": dict(league="nhl", spec=dict(t="teamunder"), status="won"),
                         "b": dict(league="nhl", spec=dict(t="teamunder"), status="lost"),
                         "c": dict(league="nba", kind="prop", market="Assists", status="won"),
                         "d": dict(league="nba", kind="prop", market="Assists", status="open")}}
        self.assertEqual(locks.kind_record(book), {("nhl", "teamunder"): [1, 2], ("nba", "prop:Assists"): [1, 1]})
        self.assertEqual(locks.kind_key(dict(league="nhl", t="teamunder")), ("nhl", "teamunder"))


if __name__ == "__main__":
    unittest.main()
