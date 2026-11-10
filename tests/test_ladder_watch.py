import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ladder_watch as w                                          # noqa: E402


class LadderWatch(unittest.TestCase):
    def test_snapshot_and_changes(self):
        r = dict(today=dict(legs=[dict(label="A", status="open"), dict(label="B", status="won", score="X 2 - Y 1")]))
        s = w.snapshot(r)
        self.assertEqual(s, {"A": "open", "B": "won | X 2 - Y 1"})
        self.assertEqual(w.changes({}, s), [])                        # first look: nothing to report
        s2 = dict(s, A="lost | X 0 - Y 3")
        self.assertEqual(w.changes(s, s2), ["CHANGE: A = lost | X 0 - Y 3"])
        self.assertEqual(w.changes(s2, s2), [])

    def test_settled(self):
        done = w.snapshot(dict(today=None, last=dict(day="2026-11-07", result="lost"), bank=1.0))
        self.assertEqual(done, {"SETTLED": "2026-11-07 lost bank 1.0"})
        self.assertEqual(w.changes({"A": "open"}, done), ["SETTLED: 2026-11-07 lost bank 1.0"])
        self.assertEqual(w.changes(done, done), [])


    def test_games(self):
        book = {"a": dict(date="2026-11-09", league="nba", matchup="CLE @ CHA", pick="Cleveland Cavaliers", status="lost",
                          scores={"Charlotte Hornets": 124, "Cleveland Cavaliers": 112}),
                "b": dict(date="2026-11-09", league="nba", matchup="NO @ GS", pick="Golden State Warriors", status="open"),
                "c": dict(date="2026-11-09", league="nhl", matchup="X @ Y", pick="Y", status="open"),
                "d": dict(date="2026-11-08", league="nba", matchup="P @ Q", pick="Q", status="open")}
        g = w.games_snapshot(book, "2026-11-09", "nba")
        self.assertEqual(g, {"GAME CLE @ CHA": "board pick Cleveland Cavaliers = lost | Charlotte Hornets 124, Cleveland Cavaliers 112",
                             "GAME NO @ GS": "board pick Golden State Warriors = open"})
        settled = dict(g, SETTLED="2026-11-09 won bank 2.0")
        self.assertFalse(w.done(settled))                             # a watched game is still open
        self.assertTrue(w.done(dict(settled, **{"GAME NO @ GS": "board pick Golden State Warriors = won | A 1, B 0"})))
        self.assertTrue(w.done({"SETTLED": "x"}))
        self.assertEqual(w.changes({"SETTLED": "x", "GAME NO @ GS": "board pick G = open"},
                                   {"SETTLED": "x", "GAME NO @ GS": "board pick G = won | A 1, B 0"}),
                         ["CHANGE: GAME NO @ GS = board pick G = won | A 1, B 0"])


    def test_loop_stops_when_settled(self):
        calls = {"pull": 0, "sleep": 0}
        codes = iter([0, 0, 3])
        rc = w.loop(["state.json"], 120, "b",
                    run=lambda: next(codes),
                    pull=lambda: calls.__setitem__("pull", calls["pull"] + 1),
                    sleep=lambda s: calls.__setitem__("sleep", calls["sleep"] + 1))
        self.assertEqual((rc, calls["pull"], calls["sleep"]), (0, 3, 2))


if __name__ == "__main__":
    unittest.main()
