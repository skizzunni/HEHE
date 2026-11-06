"""Every game: its single likeliest game line, graded off the picks ledger."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import locks                                              # noqa: E402


def leg(gid, label, p, spec, kind=None):
    return dict(gid=gid, label=label, p=p, price="-900", spec=spec, kind=kind, home="H", away="A", match="A at H")


class EveryGame(unittest.TestCase):
    POOL = [leg("nhl:1", "Under 9.5 goals", 0.90, dict(t="under", line=9.5)),
            leg("nhl:1", "H +3.5", 0.93, dict(t="spread", team="H", line=3.5)),
            leg("nhl:1", "Player 1+ shots", 0.99, None, kind="prop"),
            leg("nhl:2", "Over 0.5 goals", 0.91, dict(t="over", line=0.5))]

    def test_one_line_per_game_props_left_out(self):
        self.assertEqual([L["label"] for L in locks.best_per_game(self.POOL)], ["H +3.5", "Over 0.5 goals"])

    def test_graded_off_final_scores(self):
        led = {"nhl:1": dict(status="won", scores={"H": 1, "A": 6}), "nhl:2": dict(status="open")}
        got = {g["gid"]: (g["status"], g["score"]) for g in locks.every_game(self.POOL, led)}
        self.assertEqual(got, {"nhl:1": ("lost", "A 6 - H 1"), "nhl:2": ("open", None)})


class Record(unittest.TestCase):
    def test_by_league(self):
        legs = [dict(EveryGame.POOL[1], league="nhl"), dict(EveryGame.POOL[3], league="nhl")]
        book = {"pools": {"2026-11-03": {"legs": legs}}}
        led = {"nhl:1": dict(status="won", scores={"H": 3, "A": 1}), "nhl:2": dict(status="won", scores={"H": 0, "A": 0})}
        orig = locks.load
        locks.load = lambda path=None: book
        try:
            r = locks.every_game_record(None, led)
        finally:
            locks.load = orig
        self.assertEqual((r["n"], r["won"], r["by_league"], r["swept"]), (2, 1, [dict(league="NHL", won=1, n=2)], 0))


if __name__ == "__main__":
    unittest.main()


class PoolForm(unittest.TestCase):
    def test_last_days_only(self):
        import locks
        rows = [("2026-11-0%d" % d, "nba", "over", 0.8, d % 2 == 0) for d in range(1, 10) for _ in range(5)]
        orig = locks._pool_rows
        locks._pool_rows = lambda paths=None, led=None: rows
        try:
            f = locks.pool_form(days=2, min_n=5)
        finally:
            locks._pool_rows = orig
        self.assertEqual(f, [dict(league="nba", t="over", won=5, n=10, said=80.0, since="2026-11-08")])


class PropForm(unittest.TestCase):
    def test_last_days_and_band(self):
        import props_ledger
        book = {}
        for d in range(1, 10):
            for i in range(4):
                book[f"{d}-{i}"] = dict(date=f"2026-11-0{d}", league="nba", market="Assists", p=0.8,
                                        status="won" if i < 3 else "lost")
        book["x"] = dict(date="2026-11-09", league="nba", market="Assists", p=0.99, status="lost")   # out of band
        f = props_ledger.form(days=2, min_n=5, book=book)
        self.assertEqual(f, [dict(league="nba", market="Assists", won=6, n=8, said=80.0, since="2026-11-08")])


class SpreadSides(unittest.TestCase):
    def test_split_by_side_and_halves(self):
        import locks
        legs = []
        led = {}
        for d in range(1, 5):
            for i in range(30):
                gid = f"nhl:{d}{i}"
                led[gid] = dict(status="won", scores={"H": 3, "A": 2 if i % 3 else 5})
                legs.append(dict(gid=gid, label=f"A +1.5 {i}", league="nhl", home="H", away="A", p=0.8,
                                 spec=dict(t="spread", team="A", line=1.5)))
        pools = {"pools": {f"2026-11-0{d}": {"legs": [L for L in legs if L["gid"].startswith(f"nhl:{d}")]} for d in range(1, 5)}}
        orig = locks.load
        locks.load = lambda path=None: pools if path == "x" else {}
        try:
            out = locks.spread_sides(paths=["x"], led=led)
        finally:
            locks.load = orig
        self.assertEqual(out, [dict(league="nhl", side="getting", all=[120, 120, 80.0],
                                    halves=[[60, 60, 80.0], [60, 60, 80.0]])])
