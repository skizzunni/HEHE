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


class PostponedTest(unittest.TestCase):
    def test_postponed_game_settles_as_push(self):
        page = {"header": {"competitions": [{"status": {"type": {"completed": False, "name": "STATUS_POSTPONED"}},
                                             "competitors": []}]}}
        scores, done = G.final("nba", "1", get=lambda u: page)
        self.assertTrue(done)
        for pk in (dict(kind="ml", team="BOS"), dict(kind="prop", player="X", stat="PTS", line=5),
                   dict(kind="prop", lg="nba", market="Points", player="X", line=5.0, line_text="5+")):
            self.assertEqual(G.grade(pk, scores, done, page), "push")


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

BOX_DONE = dict(BOX, header={"competitions": [{"status": {"type": {"completed": True}},
                                               "competitors": BOX["header"]["competitions"][0]["competitors"]}]})


class PropTest(unittest.TestCase):
    def test_player_stat(self):
        self.assertEqual(G.player_stat(BOX, "Keegan Murray", "PTS"), 5.0)
        self.assertEqual(G.player_stat(BOX, "Keegan Murray", "PTS+REB+AST"), 9.0)
        self.assertEqual(G.player_stat(BOX, "Keegan Murray", "3PM"), 1.0)
        self.assertEqual(G.player_stat(BOX, "Bench Guy", "PTS"), 0.0)
        self.assertIsNone(G.player_stat(BOX, "Nobody", "PTS"))

    def test_dressed_but_did_not_play_is_a_push(self):
        box = {"boxscore": {"players": [{"team": {"abbreviation": "GS"}, "statistics": [
            {"name": "", "keys": ["points"], "labels": ["PTS"], "athletes": [
                {"athlete": {"id": "7", "displayName": "Kevon Looney"}, "didNotPlay": True, "reason": "COACH'S DECISION", "stats": []}]}]}]}}
        pk = dict(kind="prop", lg="nba", market="Points", player="Kevon Looney", line=5.0, line_text="5+", stat="PTS")
        self.assertEqual(G.grade(pk, {"A": 1.0, "B": 2.0}, True, box), "push")
        self.assertEqual(G.grade(pk, {}, False, box), "open")
        self.assertEqual(G.grade(dict(kind="prop", player="Kevon Looney", stat="PTS", line=5), {}, True, box), "push")

    def test_prop_settles_when_reached(self):
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="PTS", line=5), {}, False, BOX), "won")
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="REB", line=6), {}, False, BOX), "open")
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="REB", line=6), {}, True, BOX), "lost")

    def test_watch_fetches_each_game_once_per_round(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label=f"leg{i}", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)
                   for i in range(3)], open(path, "w"))
        calls = []
        G.watch(path, get=lambda u: calls.append(u) or BOX_DONE, sleep=lambda s: None, emit=lambda m: None)
        self.assertEqual(len(calls), 1)

    def test_watch_survives_a_bad_read(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500),
                   dict(label="Murray 9 reb", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="REB", line=9, price=-500)],
                  open(path, "w"))
        rounds = []

        def sleep(s):
            rounds.append(s)
            if len(rounds) == 1:
                open(path, "w").write("[{")            # half-written file on the next read
            else:
                done = dict(BOX, header={"competitions": [{"status": {"type": {"completed": True}},
                                                           "competitors": BOX["header"]["competitions"][0]["competitors"]}]})
                box.update(done)
        box = dict(BOX)
        out = []
        G.watch(path, get=lambda u: box, sleep=sleep, emit=out.append)
        self.assertEqual(out, ["REACHED Murray 5+ -- had 5 (settles when the game ends)",
                               "WON Murray 5+ -- had 5", "LOST Murray 9 reb -- had 3", "all picks settled: 1-1; all won: no"])

    def test_restarted_watch_does_not_repeat(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        first, second = [], []
        G.watch(path, get=lambda u: BOX_DONE, sleep=lambda s: None, emit=first.append)
        G.watch(path, get=lambda u: BOX_DONE, sleep=lambda s: None, emit=second.append)      # the Monitor re-armed
        self.assertEqual(first, ["WON Murray 5+ -- had 5", "all picks settled: 1-0; all won: YES"])
        self.assertEqual(second, ["all picks settled: 1-0; all won: YES"])

    def test_brief_view(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+ long label -- caution: reached it in 6 of his last 10", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS",
                        line=5, price=-500),
                   dict(label="Murray 9 reb", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="REB", line=9,
                        price=-500),
                   dict(label="Nobody 5+", id="1", lg="nba", kind="prop", player="Nobody Here", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        out = G.brief(path, get=lambda u: BOX)
        self.assertEqual(out[0], "1 won, 0 lost, 2 still open")
        self.assertEqual(out[1], "WON   Keegan Murray 5+ PTS")
        self.assertTrue(out[2].startswith("OPEN  Keegan Murray 9+ REB -- "))
        self.assertEqual(out[-1], "(1 not started yet)")
        self.assertEqual(G.short(dict(kind="ml", team="IOWA")), "IOWA ML")
        self.assertEqual(G.short(dict(kind="spread", team="BOS", line=-2.5)), "BOS -2.5")

    def test_watch_emits_each_settle_once(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        out = []
        G.watch(path, get=lambda u: BOX_DONE, sleep=lambda s: None, emit=out.append)
        self.assertEqual(out, ["WON Murray 5+ -- had 5", "all picks settled: 1-0; all won: YES"])

    def test_stat_correction_mid_game(self):
        # Nov 24: Suggs reached 5 reb+ast, then ESPN corrected him to 4 before the end
        import copy
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        lower = copy.deepcopy(BOX)
        lower["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][1] = "4"
        frames = [BOX, lower, BOX_DONE]
        state = {"i": 0}

        def sleep(s):
            state["i"] = min(state["i"] + 1, len(frames) - 1)
        out = []
        G.watch(path, get=lambda u: frames[state["i"]], sleep=sleep, emit=out.append)
        self.assertEqual(out, ["REACHED Murray 5+ -- had 5 (settles when the game ends)",
                               "BACK BELOW Murray 5+ -- had 4 -- the box score was corrected; not won yet",
                               "WON Murray 5+ -- had 5", "all picks settled: 1-0; all won: YES"])


NHL_BOX = {"boxscore": {"players": [{"team": {"abbreviation": "MIN"}, "statistics": [
    {"name": "forwards", "keys": ["goals", "assists", "shotsTotal"],
     "labels": ["G", "A", "S"],
     "athletes": [{"athlete": {"id": "1", "displayName": "Matt Boldy"}, "stats": ["1", "0", "5"]}]}]}]}}


class BoardPropTest(unittest.TestCase):
    def test_nhl_shots_graded_like_the_board(self):
        pk = dict(kind="prop", lg="nhl", market="Shots on Goal", player="Matt Boldy", line=2.0, line_text="2+",
                  stat="Shots on Goal")
        self.assertEqual(G.board_prop(pk, NHL_BOX), "won")
        self.assertEqual(G.grade(pk, {}, True, NHL_BOX), "won")
        self.assertEqual(G.grade(dict(pk, line=6.0, line_text="6+"), {}, True, NHL_BOX), "lost")
        self.assertEqual(G.grade(dict(pk, line=6.0, line_text="6+"), {}, False, NHL_BOX), "open")
        self.assertEqual(G.grade(dict(pk, player="Nobody Else"), {}, True, NHL_BOX), "push")   # did not play: void

    def test_nickname_in_box_score(self):
        # FanDuel's "Mitchell Marner" is ESPN's "Mitch Marner" (Nov 24 ticket leg)
        box = {"boxscore": {"players": [{"team": {"abbreviation": "VGK"}, "statistics": [
            {"name": "forwards", "keys": ["shotsTotal"], "labels": ["S"],
             "athletes": [{"athlete": {"id": "1", "displayName": "Mitch Marner"}, "stats": ["3"]}]}]}]}}
        pk = dict(kind="prop", lg="nhl", market="Shots on Goal", player="Mitchell Marner", line=1.0, line_text="1+",
                  stat="Shots on Goal")
        self.assertEqual(G.grade(pk, {}, False, box), "won")

    def test_live_shows_nhl_shots_count(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Boldy 6+ SOG", id="1", lg="nhl", kind="prop", market="Shots on Goal",
                        player="Matt Boldy", stat="Shots on Goal", line=6.0, line_text="6+", price=-150)], open(path, "w"))
        box = dict(NHL_BOX, header={"competitions": [{"status": {"type": {"completed": False, "shortDetail": "10:00 - 2nd"}},
                                                     "competitors": []}]})
        out = G.live(path, get=lambda u: box)
        self.assertEqual(out, ["OPEN  Boldy 6+ SOG -- 10:00 - 2nd: 5 of 6"])


if __name__ == "__main__":
    unittest.main()
