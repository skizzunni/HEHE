import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import grade_picks as G  # noqa: E402


class GradeTest(unittest.TestCase):
    S = {"MEM": 110.0, "CHA": 106.0}

    def test_spread_ml_totals(self):
        self.assertEqual(G.grade(dict(kind="spread", team="MEM", line=-2.5), self.S, True), "won")
        self.assertEqual(G.grade(dict(kind="spread", team="MEM", line=-4.0), self.S, True), "push")
        self.assertEqual(G.grade(dict(kind="spread", team="CHA", line=3.5), self.S, True), "lost")
        self.assertEqual(G.grade(dict(kind="ml", team="CHA"), self.S, True), "lost")
        self.assertEqual(G.grade(dict(kind="under", line=222.5), self.S, True), "won")
        self.assertEqual(G.grade(dict(kind="over", line=216.0), self.S, True), "push")
        self.assertEqual(G.grade(dict(kind="ml", team="MEM"), self.S, False), "open")

    def test_summary_units(self):
        picks = [dict(price=-116), dict(price=124), dict(price=-105), dict(price=-110)]
        s = G.summary(picks, ["won", "won", "lost", "open"])
        self.assertEqual((s["won"], s["lost"], s["open"]), (2, 1, 1))
        self.assertAlmostEqual(s["units"], round(100 / 116 + 1.24 - 1, 2))

    def test_final_from_espn_shape(self):
        page = {"header": {"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
            {"team": {"abbreviation": "NJ"}, "score": "4"}, {"team": {"abbreviation": "CBJ"}, "score": "2"}]}]}}
        scores, done = G.final("nhl", "1", get=lambda u: page)
        self.assertEqual((scores, done), ({"NJ": 4.0, "CBJ": 2.0}, True))


class StandingTest(unittest.TestCase):
    def test_words(self):
        S = {"MEM": 89.0, "CHA": 81.0}
        self.assertEqual(G.standing(dict(kind="spread", team="MEM", line=-2.5), S), "89-81, ahead by 5.5")
        self.assertEqual(G.standing(dict(kind="under", line=222.5), {"MIN": 74.0, "BKN": 61.0}), "135 so far, 87.5 to spare before the line")
        self.assertEqual(G.standing(dict(kind="over", line=6.5), {"A": 3.0, "B": 2.0}), "5 so far, needs 1.5 more")
        self.assertEqual(G.standing(dict(kind="ml", team="X"), {}), "not started")


BOX = {"header": {"competitions": [{"status": {"type": {"completed": False}}, "competitors": [
    {"team": {"abbreviation": "SA"}, "score": "35"}, {"team": {"abbreviation": "SAC"}, "score": "36"}]}]},
       "boxscore": {"players": [{"statistics": [{"labels": ["MIN", "PTS", "REB", "AST", "3PT"], "athletes": [
           {"athlete": {"displayName": "Keegan Murray"}, "stats": ["20", "5", "3", "1", "1-4"]},
           {"athlete": {"displayName": "Bench Guy"}, "stats": []}]}]}]}}


class PropTest(unittest.TestCase):
    def test_player_stat(self):
        self.assertEqual(G.player_stat(BOX, "Keegan Murray", "PTS"), 5.0)
        self.assertEqual(G.player_stat(BOX, "Keegan Murray", "PTS+REB+AST"), 9.0)
        self.assertEqual(G.player_stat(BOX, "Keegan Murray", "3PM"), 1.0)
        self.assertEqual(G.player_stat(BOX, "Bench Guy", "PTS"), 0.0)
        self.assertIsNone(G.player_stat(BOX, "Nobody", "PTS"))

    def test_prop_settles_when_reached(self):
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="PTS", line=5), {}, False, BOX), "won")
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="REB", line=6), {}, False, BOX), "open")
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="REB", line=6), {}, True, BOX), "lost")

    def test_watch_emits_each_settle_once(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        out = []
        G.watch(path, get=lambda u: BOX, sleep=lambda s: None, emit=out.append)
        self.assertEqual(out, ["WON Murray 5+", "all picks settled"])


if __name__ == "__main__":
    unittest.main()
