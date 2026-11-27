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
        box = {"boxscore": {"players": [{"statistics": [{"labels": ["PTS"], "athletes": [
            {"athlete": {"displayName": "Luka Dončić"}, "stats": ["31"]}]}]}]}}
        self.assertEqual(G.player_stat(box, "Luka Doncic", "PTS"), 31.0)               # accents

    def test_dressed_but_did_not_play_is_a_push(self):
        box = {"boxscore": {"players": [{"team": {"abbreviation": "GS"}, "statistics": [
            {"name": "", "keys": ["points"], "labels": ["PTS"], "athletes": [
                {"athlete": {"id": "7", "displayName": "Kevon Looney"}, "didNotPlay": True, "reason": "COACH'S DECISION", "stats": []}]}]}]}}
        pk = dict(kind="prop", lg="nba", market="Points", player="Kevon Looney", line=5.0, line_text="5+", stat="PTS")
        self.assertEqual(G.grade(pk, {"A": 1.0, "B": 2.0}, True, box), "push")
        self.assertEqual(G.grade(pk, {}, False, box), "open")
        self.assertEqual(G.grade(dict(kind="prop", player="Kevon Looney", stat="PTS", line=5), {}, True, box), "push")

    def test_absent_player_with_a_surname_twin_is_a_push(self):
        """2026-11-25: Dejounte Murray did not play; Kris Murray did, so the
        name was 'unresolved' and the prop graded LOST. FanDuel voids a DNP."""
        from unittest import mock
        pk = dict(kind="prop", lg="nba", market="Points", player="Dejounte Murray", line=5.0, line_text="5+", stat="PTS")
        with mock.patch.object(G, "board_value", lambda p, s: (None, "unresolved")):
            self.assertEqual(G.grade(pk, {"A": 1.0, "B": 2.0}, True, BOX_DONE), "push")
            self.assertEqual(G.grade(pk, {}, False, BOX_DONE), "open")
        kp = dict(pk, player="Keegan Murray", market=None)    # the one who did play still grades (label path)
        self.assertEqual(G.grade(kp, {"A": 1.0, "B": 2.0}, True, BOX_DONE), "won")

    def test_prop_settles_when_reached(self):
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="PTS", line=5), {}, False, BOX), "won")
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="REB", line=6), {}, False, BOX), "open")
        self.assertEqual(G.grade(dict(kind="prop", player="Keegan Murray", stat="REB", line=6), {}, True, BOX), "lost")

    def test_record_counts_a_prop_only_at_the_final(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="k", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        self.assertEqual(G.main(path, get=lambda u: BOX)[1], ["open"])        # reached mid-game
        self.assertEqual(G.main(path, get=lambda u: BOX_DONE)[1], ["won"])

    def test_dropped_count_without_and_with_sidecar(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "ticket.json")
        json.dump([dict(label=x, id="1", lg="nba", kind="ml", team="BOS") for x in ("a", "b")], open(path, "w"))
        self.assertEqual(G.dropped_count(path), 0)
        self.assertEqual(G.dropped_count(path + ".missing"), 0)
        json.dump(["b", "not on this ticket"], open(path + ".dropped", "w"))
        self.assertEqual(G.dropped_count(path), 1)
        head = G.brief(path, get=lambda u: {})[0]
        self.assertTrue(head.endswith("(1 dropped before tip, not counted)"), head)

    def test_slate_lists_every_saved_ticket(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        leg = dict(label="k", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)
        json.dump([leg, dict(leg, label="r", stat="REB", line=50)], open(os.path.join(d, "ticket.json"), "w"))
        json.dump([leg], open(os.path.join(d, "ticket_ladder.json"), "w"))
        out = G.slate(d, get=lambda u: BOX_DONE)
        self.assertEqual(out[0], "ticket, 2 legs: 1 won, 1 lost, 0 still open")
        self.assertEqual(out[1], "  safest bands 0/0, the rest 1/2 (50%)")     # the main ticket's band split
        self.assertEqual(out[2], "ladder stand-in, 1 legs: 1 won, 0 lost, 0 still open -- every leg won")

    def test_watch_picks_up_a_drop_made_while_it_runs(self):
        """A recheck at 6:30 PM may drop a leg after the watch started; the
        next round must leave it out of the record (2026-11-25)."""
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="keep", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500),
                   dict(label="drop", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="REB", line=50, price=-500)],
                  open(path, "w"))
        state = {"box": BOX}

        def nap(s):
            json.dump(["drop"], open(path + ".dropped", "w"))
            state["box"] = BOX_DONE
        out = []
        G.watch(path, get=lambda u: state["box"], sleep=nap, emit=out.append, remember=False)
        self.assertEqual(out[-1], "all picks settled: 1-0; all won: YES")
        self.assertFalse(any("drop" in m for m in out))

    def test_failed_read_on_a_final_game_is_not_a_correction(self):
        """2026-11-25: an empty ESPN read on finished games announced BACK BELOW
        for three legs that had won (Kent Johnson, Hamilton, Coyle)."""
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="done", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500),
                   dict(label="late", id="2", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        rnd = {"n": 0}

        def get(u):
            if "event=1" in u:
                return BOX_DONE if rnd["n"] != 1 else None     # round 2: the read fails
            return BOX if rnd["n"] < 2 else BOX_DONE

        def nap(s):
            rnd["n"] += 1
        out = []
        G.watch(path, get=get, sleep=nap, emit=out.append, remember=False)
        self.assertFalse(any(m.startswith("BACK BELOW") for m in out), out)
        self.assertEqual(sum(m.startswith("WON done") for m in out), 1, out)
        self.assertEqual(out[-1], "all picks settled: 2-0; all won: YES")

    def test_watch_fetches_each_game_once_per_round(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label=f"leg{i}", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)
                   for i in range(3)], open(path, "w"))
        calls = []
        G.watch(path, get=lambda u: calls.append(u) or BOX_DONE, sleep=lambda s: None, emit=lambda m: None)
        self.assertEqual(len(calls), 1)

    def test_watch_skips_legs_already_final(self):
        """2026-11-27: once a game's legs are settled, later rounds do not read it."""
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        legs = [dict(label="done", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500),
                dict(label="later", id="2", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)]
        json.dump(legs, open(path, "w"))
        calls, rounds = [], []
        live = {"header": {"competitions": [{"status": {"type": {"completed": False, "state": "in"}}}]}}
        def get(u):
            calls.append(u)
            return BOX_DONE if "event=1" in u or len(rounds) >= 2 else live
        G.watch(path, get=get, sleep=lambda s: rounds.append(s), emit=lambda m: None, remember=False)
        self.assertEqual(sum("event=1" in u for u in calls), 1, calls)    # read once, then skipped

    def test_standing_after_a_loss(self):
        picks = [dict(label=f"L{i}") for i in range(5)]
        seen = {"L0": "won", "L0|final": True, "L1": "lost", "L1|final": True, "L2": "reached"}
        self.assertEqual(G._standing(picks, seen), " (ticket now 1-1, 3 to go)")

    def test_final_score(self):
        sm = {"header": {"competitions": [{"status": {"type": {"detail": "Final/SO"}},
                                           "competitors": [{"team": {"abbreviation": "NSH"}, "score": "5"},
                                                           {"team": {"abbreviation": "UTA"}, "score": "6"}]}]}}
        self.assertEqual(G._final_score(sm), " (final: UTA 6, NSH 5, Final/SO)")
        sm["header"]["competitions"][0]["status"]["type"]["detail"] = "Final"
        self.assertEqual(G._final_score(sm), " (final: UTA 6, NSH 5)")
        self.assertEqual(G._final_score({}), "")

    def test_short_clause(self):
        picks = [dict(id=str(g), price=p) for g in range(6) for p in ("-1500", "-6000")]
        res = ["lost", "won"] * 6
        self.assertEqual(G._short_clause(picks, res), "; short 6: 6-0 (all won)")
        self.assertEqual(G._short_clause(picks[:4], res[:4]), "")

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
        self.assertEqual(out, ["REACHED Murray 5+ -- had 5 in 20 min (settles when the game ends)",
                               "WON Murray 5+ -- had 5 in 20 min (final: SAC 36, SA 35)", "LOST Murray 9 reb -- had 3 in 20 min (final: SAC 36, SA 35) (ticket now 1-1, 0 to go)", "all picks settled: 1-1; all won: no"])

    def test_restarted_watch_does_not_repeat(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        json.dump([dict(label="Murray 5+", id="1", lg="nba", kind="prop", player="Keegan Murray", stat="PTS", line=5, price=-500)],
                  open(path, "w"))
        first, second = [], []
        G.watch(path, get=lambda u: BOX_DONE, sleep=lambda s: None, emit=first.append)
        G.watch(path, get=lambda u: BOX_DONE, sleep=lambda s: None, emit=second.append)      # the Monitor re-armed
        self.assertEqual(first, ["WON Murray 5+ -- had 5 in 20 min (final: SAC 36, SA 35)", "all picks settled: 1-0; all won: YES"])
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
        out = G.brief(path, get=lambda u: BOX)                 # game in progress
        self.assertEqual(out[0], "0 won, 0 lost, 3 still open (1 reached, settles at the final)")
        self.assertTrue(out[1].startswith("REACHED Keegan Murray 5+ PTS -- "), out[1])   # not WON mid-game
        self.assertTrue(out[2].startswith("OPEN  Keegan Murray 9+ REB -- "))
        self.assertEqual(out[-1], "(1 not started yet)")
        done = G.brief(path, get=lambda u: BOX_DONE)            # final
        self.assertEqual(done[1], "WON   Keegan Murray 5+ PTS -- had 5 in 20 min (final: SAC 36, SA 35)")     # what settled it, not the label note
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
        self.assertEqual(out, ["WON Murray 5+ -- had 5 in 20 min (final: SAC 36, SA 35)", "all picks settled: 1-0; all won: YES"])

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
        self.assertEqual(out, ["REACHED Murray 5+ -- had 5 in 20 min (settles when the game ends)",
                               "BACK BELOW Murray 5+ -- had 4 in 20 min -- the box score was corrected; not won yet",
                               "WON Murray 5+ -- had 5 in 20 min (final: SAC 36, SA 35)", "all picks settled: 1-0; all won: YES"])


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

    def test_football_player_in_plays_only_is_lost_not_void(self):
        """2026-11-27: a receiver targeted without a catch is missing from
        ESPN's football box; named in the play-by-play he played -- 0, lost."""
        box = {"boxscore": {"players": [{"team": {"abbreviation": "LAC"}, "statistics": [
            {"name": "receiving", "keys": ["receptions", "receivingYards"], "labels": ["REC", "YDS"],
             "athletes": [{"athlete": {"id": "7", "displayName": "Keenan Allen"}, "stats": ["6", "71"]}]}]}]},
               "drives": {"previous": [{"plays": [
                   {"text": "(Shotgun) J.Herbert pass incomplete short middle to D.Njoku (T.Buchanan)."}]}]}}
        pk = dict(kind="prop", lg="nfl", market="Receptions", player="David Njoku", line=1.0, line_text="1+",
                  stat="Receptions")
        self.assertEqual(G.board_prop(pk, box), "lost")
        self.assertEqual(G.board_prop(dict(pk, player="Tyler Warren"), box), "void")    # never named: DNP
        self.assertEqual(G.board_prop(dict(pk, player="D.J. Allen"), box), "void")      # another first letter

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

class StuckLineTest(unittest.TestCase):
    def test_names_the_cause(self):
        import daily_review as D
        st = [("picks", "ncaab:401921804")]
        self.assertIn("grading is broken", D.stuck_line(st))
        self.assertIn("the grader has not run", D.stuck_line(st, "STALE GRADER: ..."))
        self.assertTrue(D.stuck_line(st).startswith("STUCK 1 record(s)"))

class ValueLongshotClauseTest(unittest.TestCase):
    def test_counts_longshots_claiming_big_edges(self):
        import daily_review as D
        mk = lambda st, fair=0.15, ev=0.04, kind="value": dict(kind=kind, status=st, fair=fair, ev=ev)
        finds = [mk("lost")] * 11 + [mk("won", ev=0.02)] * 5 + [mk("lost", kind="suspect")] * 5
        out = D.value_longshot_clause(finds)
        self.assertEqual(out, "; longshots claiming a 3%+ edge (fair under 25%): 0/11 against 1.6 expected "
                              "(README 2026-11-27, caution)")
        self.assertEqual(D.value_longshot_clause(finds[:5]), "")      # too few: nothing said


if __name__ == "__main__":
    unittest.main()

