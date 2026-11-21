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
        self.assertEqual(w.safe_note(dict(label="J: 2+ Assists", line="2+", so_far=0.0, league="nba", live="5:00 - 3rd")),
                         "behind pace after halftime")
        self.assertEqual(w.safe_note(dict(label="J: 2+ Assists", line="2+", so_far=0.0, league="nba", live="5:00 - 2nd")), "")
        self.assertEqual(w.safe_note(dict(label="J: 10+ Points", line="10+", so_far=6.0, league="nba", live="11:00 - 3rd")), "")   # on pace for 11.5
        self.assertEqual(w.safe_note(dict(label="Under 254.5 points", league="nba", live="Halftime",
                                          live_score="Chicago Bulls 70 - San Antonio Spurs 60")),
                         "off pace after halftime (130 so far, line 254.5)")
        self.assertTrue(w._same("open | off pace after halftime (130 so far, line 254.5)",
                                "open | off pace after halftime (141 so far, line 254.5)"))       # one alert, not one per basket
        self.assertEqual(w.safe_note(dict(label="Under 254.5 points", league="nba", live="Halftime",
                                          live_score="Chicago Bulls 60 - San Antonio Spurs 56")), "")
        self.assertEqual(w.safe_note(dict(label="Under 254.5 points", league="nba", live="5:00 - 2nd",
                                          live_score="Chicago Bulls 70 - San Antonio Spurs 60")), "")
        self.assertEqual(w.safe_note(dict(label="USC Trojans to win", league="ncaab", live="10:00 - 2nd",
                                          live_score="USC Trojans 40 - California Golden Bears 52")), "down 10+ after halftime")
        self.assertEqual(w.safe_note(dict(label="USC Trojans to win", league="ncaab", live="10:00 - 2nd",
                                          live_score="USC Trojans 48 - California Golden Bears 52")), "")
        self.assertEqual(w.safe_note(dict(label="USC Trojans to win", league="ncaab", live="10:00 - 1st",
                                          live_score="USC Trojans 10 - California Golden Bears 30")), "")
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


    def test_all_leagues_with_why(self):
        book = {"a": dict(date="2026-11-11", league="nba", matchup="NO @ BKN", pick="New Orleans Pelicans", conf=56.2,
                          status="lost", scores={"Brooklyn Nets": 145, "New Orleans Pelicans": 111},
                          diagnosis="margin 34 · coin flip · blowout"),
                "b": dict(date="2026-11-11", league="epl", matchup="A @ B", pick="B", dc=True, conf=70, status="open")}
        g = w.games_snapshot(book, "2026-11-11", "all")
        self.assertEqual(g["GAME nba NO @ BKN"], "board pick New Orleans Pelicans (56%) = lost | Brooklyn Nets 145,"
                                                 " New Orleans Pelicans 111 | why: margin 34 · coin flip · blowout")
        self.assertEqual(g["GAME epl A @ B"], "board pick B or draw = open")          # no chance while open: drift is not news

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


class DecidedNoteOnce(unittest.TestCase):
    def test_running_total_after_decided_is_not_a_change(self):
        import ladder_watch as w
        a = {"Over 208.5 points": "open | already over (219, line 208.5)"}
        b = {"Over 208.5 points": "open | already over (226, line 208.5)"}
        self.assertEqual(w.changes(a, b), [])
        self.assertEqual(w.changes({"Under 7.5 goals": "open | gone over (8, line 7.5) -- lost"},
                                   {"Under 7.5 goals": "open | gone over (9, line 7.5) -- lost"}), [])

    def test_first_alert_and_settle_still_report(self):
        import ladder_watch as w
        self.assertEqual(w.changes({"Over 208.5 points": "open"}, {"Over 208.5 points": "open | already over (219, line 208.5)"}),
                         ["CHANGE: Over 208.5 points = open | already over (219, line 208.5)"])
        self.assertEqual(w.changes({"Over 208.5 points": "open | already over (226, line 208.5)"}, {"Over 208.5 points": "won"}),
                         ["CHANGE: Over 208.5 points = won"])


class FirstLook(unittest.TestCase):
    def test_summary(self):
        import ladder_watch as w
        after = {"Under 241.5 points": "open", "GAME nba POR @ SAC": "board pick Portland = open",
                 "GAME unl FRO @ SVK": "board pick Slovakia (67%) = lost | Faroe Islands 2, Slovakia 2 | why: drawn",
                 "GAME unl GER @ SRB": "board pick Germany (76%) = won | Germany 3, Serbia 1"}
        self.assertEqual(w.first_look(after), ["WATCHING: Under 241.5 points = open",
                                               "WATCHING: 3 board games -- 1 won, 1 lost (Slovakia), 1 open"])
        self.assertEqual(w.first_look({"A": "open"}), ["WATCHING: A = open"])


class NoHundred(unittest.TestCase):
    def test_heavy_pick_reads_99_plus(self):
        import ladder_watch as w
        book = {"k": dict(date="2026-11-13", league="ncaab", matchup="NAU @ UK", pick="Kentucky Wildcats", conf=100,
                          status="won", scores={"Kentucky Wildcats": 78, "Northern Arizona Lumberjacks": 77})}
        out = w.games_snapshot(book, "2026-11-13", "all")
        self.assertIn("Kentucky Wildcats (99%+) = won", list(out.values())[0])


class FirstLookSettled(unittest.TestCase):
    def test_settled_ticket_and_all_games_done(self):
        import ladder_watch as w
        after = {"Houston Cougars to win": "lost | Colorado Buffaloes 42 - Houston Cougars 32",
                 "SETTLED": "2026-11-13 lost bank 1.0",
                 "GAME ncaaf HOU @ COLO": "board pick Houston Cougars (75%) = lost | Colorado Buffaloes 42, Houston Cougars 32 | why: upset",
                 "GAME nba POR @ SAC": "board pick Portland Trail Blazers (79%) = won | Portland Trail Blazers 120, Sacramento Kings 107"}
        self.assertEqual(w.first_look(after), [
            "WATCHING: Houston Cougars to win = lost | Colorado Buffaloes 42 - Houston Cougars 32",
            "WATCHING: SETTLED = 2026-11-13 lost bank 1.0",
            "WATCHING: 2 board games -- 1 won, 1 lost (Houston Cougars), 0 open"])
        self.assertTrue(w.done(after))


class UfcSnapshot(unittest.TestCase):
    SB = {"events": [{"competitions": [
        {"format": {"regulation": {"periods": 3}}, "status": {"period": 1, "displayClock": "4:16", "type": {"completed": True}},
         "competitors": [{"athlete": {"displayName": "A"}, "winner": False}, {"athlete": {"displayName": "B"}, "winner": True}]},
        {"format": {"regulation": {"periods": 5}}, "status": {"period": 5, "displayClock": "5:00", "type": {"completed": True}},
         "competitors": [{"athlete": {"displayName": "C"}, "winner": True}, {"athlete": {"displayName": "D"}, "winner": False}]},
        {"status": {"period": 0, "type": {"completed": False}},
         "competitors": [{"athlete": {"displayName": "E"}}, {"athlete": {"displayName": "F"}}]},
        {"status": {"type": {"completed": True}}, "competitors": [{"athlete": {"displayName": "X"}}, {"athlete": {"displayName": "Y"}}]}]}]}

    def test_results(self):
        import ladder_watch as w
        out = w.ufc_snapshot("2026-11-14", {"A": 70, "C": 60, "F": 55}, fetch=lambda u: self.SB)
        self.assertEqual(out, {"UFC A vs B": "board pick A (70%) = lost | winner B, finish R1 4:16",
                               "UFC C vs D": "board pick C (60%) = won | winner C, decision",
                               "UFC E vs F": "board pick F = open"})

    def test_counts_in_done_and_first_look(self):
        import ladder_watch as w
        after = {"SETTLED": "x", "UFC E vs F": "board pick F = open", "UFC A vs B": "board pick A (70%) = lost | winner B"}
        self.assertFalse(w.done(after))
        self.assertIn("WATCHING: 2 board games -- 0 won, 1 lost (A), 1 open", w.first_look(after))


    def test_draw_is_void_and_settled(self):
        import ladder_watch as w
        sb = {"events": [{"competitions": [
            {"status": {"period": 3, "displayClock": "5:00", "type": {"completed": True}},
             "competitors": [{"athlete": {"displayName": "Holland"}, "winner": False},
                             {"athlete": {"displayName": "Medic"}, "winner": False}]}]}]}
        out = w.ufc_snapshot("2026-11-14", {"Medic": 60}, fetch=lambda u: sb)
        self.assertEqual(out, {"UFC Holland vs Medic": "board pick Medic (60%) = void | no winner (draw or no contest)"})
        self.assertTrue(w.done(dict(out, SETTLED="x")))
        self.assertEqual(w.ufc_record(dict(out, **{"UFC A vs B": "board pick A (70%) = won | winner A, decision"})),
                         "UFC tonight 1-0, 1 draw/no contest, card done")

    def test_feed_failure_is_empty(self):
        import ladder_watch as w

        def boom(u):
            raise OSError("down")
        self.assertEqual(w.ufc_snapshot("2026-11-14", {"A": 70}, fetch=boom), {})


class RememberedPicks(unittest.TestCase):
    def test_keeps_picks_that_left_the_board(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json.ufc_picks.json")
            self.assertEqual(w.remembered_picks(p, {"A": 54, "B": 80}), {"A": 54, "B": 80})
            self.assertEqual(w.remembered_picks(p, {"B": 81}), {"A": 54, "B": 81})   # A started, kept
            self.assertEqual(w.remembered_picks(p, {}), {"A": 54, "B": 81})          # page fetch failed

    def test_another_days_picks_are_dropped(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json.ufc_picks.json")
            w.remembered_picks(p, {"A": 54}, "2026-11-14")
            self.assertEqual(w.remembered_picks(p, {"B": 70}, "2026-11-14"), {"A": 54, "B": 70})
            self.assertEqual(w.remembered_picks(p, {"A": 61}, "2026-11-21"), {"A": 61})       # new card
            with open(p, "w") as fh:
                json.dump({"A": 54}, fh)                                                    # older flat file
            self.assertEqual(w.remembered_picks(p, {}, None), {"A": 54})
            self.assertEqual(w.remembered_picks(p, {}, "2026-11-14"), {})


class How(unittest.TestCase):
    def test_methods(self):
        self.assertEqual(w._how(dict(period=3, displayClock="5:00"), 3), "decision")
        self.assertEqual(w._how(dict(period=1, displayClock="3:23"), 3), "finish R1 3:23")
        self.assertEqual(w._how(dict(period=3, displayClock="-"), 3), "method not posted yet")
        self.assertEqual(w._how(dict(displayClock="5:00"), 3), "method not posted yet")
        self.assertEqual(w._how(dict(period=5, displayClock="5:00"), 5), "decision")
        self.assertEqual(w._how(dict(period=3, displayClock="5:00"), 5), "finish R3 5:00")


class UfcRecord(unittest.TestCase):
    def test_record_on_results(self):
        before = {"UFC A vs B": "board pick B = open", "UFC C vs D": "board pick D = open", "Over 1": "open"}
        after = {"UFC A vs B": "board pick B (88%) = lost | winner A, decision", "UFC C vs D": "board pick D = open",
                 "UFC E vs F": "board pick F (60%) = won | winner F, decision", "Over 1": "open"}
        self.assertEqual(w.ufc_record(after), "UFC tonight 1-1, 1 to go")
        out = w.changes(before, after)
        self.assertIn("CHANGE: UFC A vs B = board pick B (88%) = lost | winner A, decision | UFC tonight 1-1, 1 to go", out)
        self.assertEqual(w.ufc_record({"Over 1": "open"}), "")
        done = dict(after, **{"UFC C vs D": "board pick D (66%) = won | winner D, decision"})
        self.assertEqual(w.ufc_record(done), "UFC tonight 2-1, card done")


class TenLegWatch(unittest.TestCase):
    def test_record_changes_and_done(self):
        before = {"SETTLED": "x", "TEN Over 200.5 points (A @ B)": "open", "TEN Under 250.5 points (C @ D)": "open"}
        after = dict(before, **{"TEN Over 200.5 points (A @ B)": "won | B 110 - A 101"})
        self.assertEqual(w.ten_record(after), "10-leg: 1 won, 0 lost, 1 open")
        self.assertIn("CHANGE: TEN Over 200.5 points (A @ B) = won | B 110 - A 101 | 10-leg: 1 won, 0 lost, 1 open",
                      w.changes(before, after))
        self.assertFalse(w.done(after))
        lost = dict(after, **{"TEN Under 250.5 points (C @ D)": "lost | D 130 - C 125"})
        self.assertEqual(w.ten_record(lost), "10-leg: 1 won, 1 lost, 0 open -- ticket lost")
        self.assertTrue(w.done(lost))
        self.assertIn("WATCHING: 10-leg: 1 won, 0 lost, 1 open", w.first_look(after))
        self.assertEqual(w.ten_record({"SETTLED": "x"}), "")

    def test_snapshot_from_pool(self):
        import unittest.mock as m
        import locks
        eg = [dict(gid=f"g{i}", label=f"Over {200 + i}.5 points", price="-2000", p=0.93, league="nba",
                   match=f"T{i} @ U{i}", status="won" if i == 0 else "open", score="U0 110 - T0 101" if i == 0 else None)
              for i in range(10)]
        with m.patch.object(locks, "every_game", lambda legs, led=None: [dict(g) for g in eg]):
            snap = w.ten_snapshot("2026-11-18", {}, pool={"legs": []}, final_fn=lambda lg, eid, e: None)
        self.assertEqual(len(snap), 10)
        self.assertEqual(snap["TEN Over 200.5 points (T0 @ U0)"], "won | U0 110 - T0 101")
        self.assertEqual(snap["TEN Over 201.5 points (T1 @ U1)"], "open")
        self.assertEqual(w.ten_snapshot("2026-11-18", {}, pool={}), {})


class FinalNote(unittest.TestCase):
    def test_final_before_graded(self):
        res = {"live": False, "winner": "Buffalo Sabres", "scores": {"Washington Capitals": 3, "Buffalo Sabres": 6}}
        L = dict(label="Washington Capitals +1.5", gid="nhl:1", kind="game", status="open")
        self.assertEqual(w.final_note(L, lambda lg, eid, e: res),
                         "final, not graded yet (Washington Capitals 3, Buffalo Sabres 6)")
        self.assertIsNone(w.final_note(L, lambda lg, eid, e: {"live": True, "state": "2nd"}))
        self.assertIsNone(w.final_note(dict(L, status="won"), lambda lg, eid, e: res))
        self.assertIsNone(w.final_note(dict(L, kind="prop"), lambda lg, eid, e: res))
        self.assertIsNone(w.final_note(L, lambda lg, eid, e: 1 / 0))           # a feed error is not a result
        snap = w.snapshot({"today": {"legs": [L]}}, final_fn=lambda lg, eid, e: res)
        self.assertEqual(snap["Washington Capitals +1.5"], "open | final, not graded yet (Washington Capitals 3, Buffalo Sabres 6)")


class PickOf(unittest.TestCase):
    def test_pick_from_value(self):
        self.assertEqual(w._pick_of("board pick Vasco da Gama or draw (84%) = won | x"), "Vasco da Gama or draw")
        self.assertEqual(w._pick_of("board pick Kentucky Wildcats (99%+) = lost | why: upset"), "Kentucky Wildcats")
        self.assertEqual(w._pick_of("board pick Portland = open"), "Portland")
        self.assertIsNone(w._pick_of("open | already over (4, line 0.5)"))


class DecidedNote(unittest.TestCase):
    def test_totals_and_team_totals(self):
        sc = {"Edmonton Oilers": 4, "Carolina Hurricanes": 4}
        self.assertEqual(w.decided_note("Edmonton Oilers over 0.5 goals", None, None, sc), "already over (4, line 0.5)")
        self.assertEqual(w.decided_note("Under 9.5 goals", None, None, {"A": 6, "B": 4}), "gone over (10, line 9.5) -- lost")
        self.assertIsNone(w.decided_note("Under 9.5 goals", None, None, sc))
        self.assertIsNone(w.decided_note("Minnesota Wild +2.5", None, None, sc))
        self.assertIsNone(w.decided_note("Over 202.5 points", None, None, {"A": 1}))

    def test_ten_leg_live_note(self):
        import unittest.mock as m
        import locks
        eg = [dict(gid=f"nhl:{i}", label="Edmonton Oilers over 0.5 goals" if i == 0 else f"Under {9 + i}.5 goals",
                   price="-2000", p=0.92, league="nhl", kind="game", match=f"T{i} @ U{i}", status="open") for i in range(10)]
        res = {"live": True, "state": "2:41 - 2nd", "scores": {"Carolina Hurricanes": 4, "Edmonton Oilers": 4}}
        with m.patch.object(locks, "every_game", lambda legs, led=None: [dict(g) for g in eg]):
            snap = w.ten_snapshot("2026-11-21", {}, pool={"legs": []}, final_fn=lambda lg, eid, e: res if eid == "0" else None)
        self.assertEqual(snap["TEN Edmonton Oilers over 0.5 goals (T0 @ U0)"], "open | already over (4, line 0.5)")
        self.assertEqual(snap["TEN Under 10.5 goals (T1 @ U1)"], "open")


class CachedFinal(unittest.TestCase):
    def test_one_lookup_per_game_per_minute(self):
        calls = []
        f = lambda lg, eid, e: calls.append(eid) or {"live": True, "n": len(calls)}
        w._FINAL.clear()
        a = w.cached_final("nba", "1", {}, now=100.0, fetch=f)
        b = w.cached_final("nba", "1", {}, now=130.0, fetch=f)
        c = w.cached_final("nba", "1", {}, now=170.0, fetch=f)
        w.cached_final("nba", "2", {}, now=130.0, fetch=f)
        self.assertEqual((a["n"], b["n"], c["n"]), (1, 1, 2))
        self.assertEqual(calls, ["1", "1", "2"])
        w._FINAL.clear()


class FreshLive(unittest.TestCase):
    def test_espn_score_replaces_stale_report(self):
        L = dict(label="Over 226.5 points", gid="nba:9", kind="game", status="open",
                 live="10:37 - 4th", live_score="Chicago Bulls 73 - Washington Wizards 75")
        res = {"live": True, "state": "8:01 - 4th", "scores": {"Chicago Bulls": 78, "Washington Wizards": 87}}
        F = w.fresh_live(L, lambda lg, eid, e: res)
        self.assertEqual((F["live"], F["live_score"]), ("8:01 - 4th", "Chicago Bulls 78 - Washington Wizards 87"))
        self.assertIs(w.fresh_live(L, lambda lg, eid, e: {"missing": True}), L)
        self.assertIs(w.fresh_live(L, lambda lg, eid, e: 1 / 0), L)
        self.assertIs(w.fresh_live(dict(L, kind="prop"), lambda lg, eid, e: res)["live"], "10:37 - 4th")
        over = dict(L, label="Over 160.5 points")
        snap = w.snapshot({"today": {"legs": [over]}}, final_fn=lambda lg, eid, e: res)
        self.assertEqual(snap["Over 160.5 points"], "open | already over (165, line 160.5)")


class TenFinalNote(unittest.TestCase):
    def test_open_ten_leg_final_before_graded(self):
        import unittest.mock as m
        import locks
        eg = [dict(gid=f"nhl:{i}", label=f"Under {9 + i}.5 goals", price="-2000", p=0.92, league="nhl", kind="game",
                   match=f"T{i} @ U{i}", status="open") for i in range(10)]
        res = {"live": False, "winner": "U0", "scores": {"T0": 2, "U0": 3}}
        with m.patch.object(locks, "every_game", lambda legs, led=None: [dict(g) for g in eg]):
            snap = w.ten_snapshot("2026-11-19", {}, pool={"legs": []},
                                  final_fn=lambda lg, eid, e: res if eid == "0" else None)
        self.assertEqual(snap["TEN Under 9.5 goals (T0 @ U0)"], "open | final, not graded yet (T0 2, U0 3)")
        self.assertEqual(snap["TEN Under 10.5 goals (T1 @ U1)"], "open")
        self.assertEqual(w.ten_record(snap), "10-leg: 0 won, 0 lost, 10 open")    # the note does not count as graded


class AltSnapshot(unittest.TestCase):
    def _snap(self, st):
        import unittest.mock as m
        import locks
        eg = [dict(gid=f"g{i}", label=f"Over {200 + i}.5 points", price="-200", p=0.9 - i / 100, league="nba",
                   match=f"T{i} @ U{i}", status=st[i], score="U1 99 - T1 90" if st[i] == "lost" else None) for i in range(3)]
        with m.patch.object(locks, "every_game", lambda legs, led=None: [dict(g) for g in eg]):
            return w.alt_snapshot("2026-11-19", {}, pool={"legs": []})

    def test_one_line_open_lost_won(self):
        self.assertEqual(self._snap(["open", "open", "open"]), {"ALT2X": "open | 2 legs to 2.25x"})
        self.assertEqual(self._snap(["won", "open", "open"]),
                         {"ALT2X": "open | 1 of 2 legs won, waiting on Over 201.5 points (T1 @ U1)"})
        self.assertEqual(self._snap(["won", "lost", "open"]), {"ALT2X": "lost | Over 201.5 points (U1 99 - T1 90)"})
        self.assertEqual(self._snap(["won", "won", "open"]), {"ALT2X": "won | all 2 legs, 2.25x"})
        self.assertEqual(w.alt_snapshot("2026-11-19", {}, pool={}), {})
        self.assertIn("WATCHING: 2x alternative (every-game lines) = open | 2 legs to 2.25x", w.first_look({"ALT2X": "open | 2 legs to 2.25x"}))

    def test_change_line_named(self):
        self.assertEqual(w.changes({"ALT2X": "open | 14 legs to 2.00x"}, {"ALT2X": "lost | Under 9.5 goals"}),
                         ["CHANGE: 2x alternative (every-game lines) = lost | Under 9.5 goals"])

    def test_done_waits_for_alt(self):
        self.assertFalse(w.done({"SETTLED": "x", "ALT2X": "open | 14 legs to 2.00x"}))
        self.assertTrue(w.done({"SETTLED": "x", "ALT2X": "lost | Under 9.5 goals"}))
        self.assertTrue(w.done({"SETTLED": "x"}))


class FirstLookCountsAddUp(unittest.TestCase):
    def test_void_counted(self):
        after = {"GAME nba A @ B": "board pick B (70%) = won | x", "GAME nba C @ D": "board pick D (60%) = open",
                 "GAME ncaab E @ F": "board pick F (90%) = void | postponed"}
        self.assertIn("WATCHING: 3 board games -- 1 won, 0 lost, 1 open, 1 void or not graded", w.first_look(after))
        self.assertIn("WATCHING: 2 board games -- 1 won, 0 lost, 1 open",
                      w.first_look({k: v for k, v in after.items() if "E @ F" not in k}))
