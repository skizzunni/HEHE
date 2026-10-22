"""Prop Locks: confirmed, gradable, 70%+ FanDuel props, one per game and per
player, set from noon Eastern, frozen and topped up, logged in the props
ledger and graded from it."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prop_locks as PL                                   # noqa: E402
import props_ledger                                       # noqa: E402

NOON = dt.datetime(2026, 10, 22, 12, 30, tzinfo=PL.ET).astimezone(dt.timezone.utc)
START = (NOON + dt.timedelta(hours=7)).isoformat()


def prop(name, p, market="Points", line="10+", plays=True, fd="f", price="-400"):
    return dict(name=name, p=p, market=market, line=line, label=f"{name}: {line} {market}", price=price,
                fd=fd + name, plays=plays, play="ok" if plays else "listed out", aid=None)


def game(i, props):
    return dict(id=f"nba:{i}", match=f"A{i} @ B{i}", tip="7:30 PM", props=props)


class PropLocks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.path = os.path.join(tmp, "prop_locks.json")
        self.led = os.path.join(tmp, "props.json")
        self.p = mock.patch.object(props_ledger, "LEDGER", self.led)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def run_at(self, t, games, starts=None):
        starts = starts or {g["id"]: START for g in games}
        return PL.update(games, starts, "2026-10-22", t, self.path, n=3)

    def test_chosen_strongest_one_per_game_and_player(self):
        games = [game(1, [prop("Ann", 0.92), prop("Bea", 0.90), prop("Out", 0.99, plays=False)]),
                 game(2, [prop("Ann", 0.95), prop("Cat", 0.80), prop("Low", 0.60)]),
                 game(3, [prop("Dee", 0.75, market="Fantasy Score")])]          # not gradable
        rec = self.run_at(NOON, games)
        self.assertEqual([(L["gid"], L["name"]) for L in rec["legs"]], [("nba:2", "Ann"), ("nba:1", "Bea")])
        led = props_ledger.load()
        self.assertTrue(all(led[L["key"]]["prop_lock"] and led[L["key"]]["status"] == "open" for L in rec["legs"]))

    def test_not_before_noon_and_frozen_then_topped_up(self):
        g1 = [game(1, [prop("Ann", 0.92)])]
        self.assertEqual(self.run_at(NOON - dt.timedelta(hours=2), g1)["legs"], [])
        self.run_at(NOON, g1)
        later = NOON + dt.timedelta(hours=1)
        rec = self.run_at(later, [game(1, [prop("Zed", 0.99)]), game(4, [prop("Eve", 0.85)])])
        self.assertEqual([L["name"] for L in rec["legs"]], ["Ann", "Eve"])         # never replaced; topped up

    def test_started_games_excluded(self):
        g = [game(1, [prop("Ann", 0.92)])]
        rec = self.run_at(NOON, g, {"nba:1": (NOON - dt.timedelta(minutes=1)).isoformat()})
        self.assertEqual(rec["legs"], [])

    def test_report_from_the_ledger(self):
        rec = self.run_at(NOON, [game(1, [prop("Ann", 0.80, price="-400")]), game(2, [prop("Bea", 0.75, price="-300")])])
        led = props_ledger.load()
        led[rec["legs"][0]["key"]]["status"] = "won"
        led[rec["legs"][1]["key"]]["status"] = "lost"
        props_ledger.save(led)
        r = PL.report(self.path)
        self.assertEqual((r["n"], r["won"], r["stated"]), (2, 1, 77.5))
        self.assertAlmostEqual(r["roi"], round(100 * (0.25 - 1) / 2, 1))
        pr = PL.props_record()
        self.assertEqual(pr["all"]["n"], 2)


if __name__ == "__main__":
    unittest.main()
