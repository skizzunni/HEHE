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

    def test_safe_notes(self):
        self.assertEqual(w.safe_note(dict(label="Dalton Kincaid: 20+ Receiving Yards", line="20+", so_far=23.0)),
                         "line reached")
        self.assertEqual(w.safe_note(dict(label="X: 2+ Assists", line="2+", so_far=1.0)), "")
        self.assertEqual(w.safe_note(dict(label="Over 214.5 points", live_score="Miami Heat 110 - Utah Jazz 106")),
                         "already over (216, line 214.5)")
        self.assertEqual(w.safe_note(dict(label="Over 214.5 points", live_score="A 100 - B 100")), "")
        self.assertEqual(w.safe_note(dict(label="Over 214.5 points", status="won", live_score="A 110 - B 106")), "")
        self.assertEqual(w.safe_note(dict(label="Akron Zips under 23.5 points",
                                          live_score="Akron Zips 24 - Western Michigan Broncos 21")),
                         "gone over (24, line 23.5) -- lost")
        self.assertEqual(w.safe_note(dict(label="Akron Zips under 23.5 points",
                                          live_score="Akron Zips 7 - Western Michigan Broncos 31")), "")
        self.assertEqual(w.safe_note(dict(label="Under 41.5 points", live_score="A 21 - B 24")),
                         "gone over (45, line 41.5) -- lost")
        self.assertEqual(w.safe_note(dict(label="Utah Mammoth over 2.5 goals", live_score="Utah Mammoth 3 - Montreal Canadiens 1")),
                         "already over (3, line 2.5)")
        self.assertEqual(w.safe_note(dict(label="Utah Mammoth over 2.5 goals", live_score="Utah Mammoth 2 - Montreal Canadiens 4")), "")
        s = w.snapshot(dict(today=dict(legs=[dict(label="K: 20+ Yds", line="20+", so_far=21)])))
        self.assertEqual(s, {"K: 20+ Yds": "open | line reached"})

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


    def test_first_look_lists_legs(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        from unittest import mock
        import ladder
        rep = dict(today=dict(legs=[dict(label="A", status="open")]))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ladder, "report", lambda: rep):
            st = os.path.join(d, "s.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = w.main(st)
            self.assertEqual((rc, buf.getvalue()), (0, "WATCHING: A = open\n"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                w.main(st)                               # second look, nothing changed: silent
            self.assertEqual(buf.getvalue(), "")
            self.assertEqual(json.load(open(st)), {"A": "open"})


    def test_feed_gap_keeps_note(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        from unittest import mock
        import ladder
        reps = iter([dict(today=dict(legs=[dict(label="Over 214.5 points", live_score="A 110 - B 109")])),
                     dict(today=dict(legs=[dict(label="Over 214.5 points")])),                    # feed gap
                     dict(today=dict(legs=[dict(label="Over 214.5 points", status="won", score="A 112 - B 109")]))])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ladder, "report", lambda: next(reps)):
            st = os.path.join(d, "s.json")
            outs = []
            for _ in range(3):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    w.main(st)
                outs.append(buf.getvalue())
        self.assertEqual(outs[0], "WATCHING: Over 214.5 points = open | already over (219, line 214.5)\n")
        self.assertEqual(outs[1], "")                                   # no false "open" change
        self.assertEqual(outs[2], "CHANGE: Over 214.5 points = won | A 112 - B 109\n")


if __name__ == "__main__":
    unittest.main()
