import json
import os
import sys
import math
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import recheck_ticket as R  # noqa: E402


class RecheckTest(unittest.TestCase):
    def test_flags_newly_hurt_players_and_team_absences(self):
        legs = [dict(lg="nba", kind="prop", player="Paul Reed", label="Paul Reed: 4+ Rebounds"),
                dict(lg="nba", kind="prop", player="Ausar Thompson", label="Ausar Thompson: 15+ PRA"),
                dict(lg="nba", kind="ml", team="BOS", label="Celtics ML"),
                dict(lg="nhl", kind="prop", player="Mitchell Marner", label="Marner 1+ SOG")]
        st = {"Paul Reed": "Questionable", "Mitchell Marner": "Out"}
        flags = R.recheck(legs, st.get, team_out_fn=lambda t: [("Jaylen Brown", 34.1, "Out")] if t == "BOS" else [])
        self.assertEqual(flags, [("Paul Reed: 4+ Rebounds", "Paul Reed is now Questionable on the official report"),
                                 ("Celtics ML", "caution: Jaylen Brown (Out)")])
        self.assertIn("no leg affected", R.text([], "11/24/26 05:00 PM"))
        self.assertIn("Paul Reed is now Questionable", R.text(flags))

    def test_probable_and_lookup_failure_pass(self):
        legs = [dict(lg="nba", kind="prop", player="A B", label="A"), dict(lg="nba", kind="ml", team="X", label="X")]
        def boom(t):
            raise OSError
        self.assertEqual(R.recheck(legs, lambda n: "Probable", boom), [])

    def test_nfl_props_rechecked(self):
        legs = [dict(lg="nfl", kind="prop", player="Josh Jacobs", label="Jacobs 50+ Rush Yds"),
                dict(lg="nfl", kind="prop", player="Jordan Love", label="Love 200+")]
        nfl = {"Josh Jacobs": "Out"}
        self.assertEqual(R.recheck(legs, lambda n: None, nfl_status_fn=nfl.get),
                         [("Jacobs 50+ Rush Yds", "Josh Jacobs is now Out on ESPN's NFL injury report")])
        self.assertEqual(R.recheck(legs, lambda n: "Out"), [])     # the NBA report never judges an NFL leg

    def test_nfl_status_through_the_real_name_lookup(self):
        """2026-11-26: main() wraps the NFL dict in key_absences.status_of, which
        read only 'Last, First' keys; ESPN's 'First Last' never matched. This test
        goes through the same wrapper (the one above used dict.get directly)."""
        import key_absences as K
        legs = [dict(lg="nfl", kind="prop", player="Dalton Kincaid", label="Kincaid 10+ Rec Yds")]
        nfl = {"Dalton Kincaid": "Questionable"}
        self.assertEqual(R.recheck(legs, lambda n: None, nfl_status_fn=lambda n: K.status_of(n, nfl)),
                         [("Kincaid 10+ Rec Yds", "Dalton Kincaid is now Questionable on ESPN's NFL injury report")])


class PriceCheckTest(unittest.TestCase):
    def test_moved_and_gone(self):
        legs = [dict(kind="prop", player="Trae Young", market="Pts + Ast", line_text="15+", price="-1500", label="Trae"),
                dict(kind="prop", player="Paul Reed", market="Rebounds", line_text="4+", price="-1200", label="Reed"),
                dict(kind="prop", player="Gone Guy", market="Points", line_text="5+", price="-900", label="Gone"),
                dict(kind="ml", team="BOS", price="-453", label="BOS")]
        cur = {("Trae Young", "Pts + Ast", "15+"): "-1250", ("Paul Reed", "Rebounds", "4+"): "-1200"}
        got = R.price_check(legs, cur)
        self.assertEqual(got[0], ("Trae", "FanDuel now -1250 (was -1500), the market rates it less likely (93.8% -> 92.6%)"))
        self.assertTrue(got[1][1].startswith("this line is no longer posted at FanDuel"))


class MlCheckTest(unittest.TestCase):
    def test_moneyline_move(self):
        legs = [dict(kind="ml", id="8", team="BOS", price="-453", label="BOS ML"),
                dict(kind="ml", id="9", team="DEN", price="-324", label="DEN ML")]
        rows = [dict(id="8", home="WSH", away="BOS", home_ml=400, away_ml=-550, market_home=0.17),
                dict(id="9", home="DEN", away="DAL", home_ml=-324, away_ml=260, market_home=0.73)]
        self.assertEqual(R.ml_check(legs, rows), [("BOS ML", "DraftKings now -550 (was -453), 83% no-vig, the market rates it more likely (81.9% -> 84.6%)")])


class UnsubmittedTest(unittest.TestCase):
    def test_pending_teams_are_named(self):
        rep = {"not_submitted": [("11/24/2026", "BOS@WAS", "Boston Celtics"), ("11/24/2026", "MIA@PHI", "Miami Heat"),
                                 ("11/25/2026", "BOS@WAS", "Washington Wizards")]}
        legs = [dict(lg="nba", id="8", kind="ml", team="BOS", label="BOS")]
        rows = [dict(id="8", home_name="Washington Wizards", away_name="Boston Celtics")]
        self.assertEqual(R.unsubmitted(rep, "11/24/2026", legs, rows), ["Boston Celtics"])
        out = R.text([], "05:00 PM", ["Boston Celtics"])
        self.assertIn("Boston Celtics: report NOT YET SUBMITTED", out)
        self.assertIn("no leg affected among the teams that have reported", out)
        self.assertTrue(R.text([], "05:00 PM").endswith("no leg affected."))


class PriceLogTest(unittest.TestCase):
    def test_appends_a_snapshot(self):
        import datetime as dt
        import json
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "ticket.json")
        legs = [dict(kind="prop", player="Tomas Hertl", market="Shots on Goal", line_text="1+", label="Hertl"),
                dict(kind="ml", id="8", team="BOS", label="BOS")]
        cur = {("Tomas Hertl", "Shots on Goal", "1+"): "-950"}
        rows = [dict(id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453)]
        now = dt.datetime(2026, 11, 24, 18, 45, tzinfo=dt.timezone.utc)
        out = R.log_prices(path, legs, cur, rows, now)
        R.log_prices(path, legs, cur, rows, now)
        lines = [json.loads(x) for x in open(out)]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], {"t": "2026-11-24T18:45:00", "prices": {"Hertl": "-950", "BOS": -453}})


class MainEndToEndTest(unittest.TestCase):
    """main() with every network source faked: the glue between the injury
    report, NHL lines, FanDuel / DraftKings prices and the final view."""
    def test_main_final(self):
        import io
        import json
        import tempfile
        from unittest import mock
        import build_ticket as B
        import key_absences as K
        import nba_injury_report as NR
        import nhl_goalies as NG
        import slate_sheet
        d = tempfile.mkdtemp()
        path = os.path.join(d, "ticket.json")
        legs = [dict(lg="nba", id="8", kind="ml", team="BOS", price="-453", label="BOS ML"),
                dict(lg="nba", id="8", kind="prop", player="Cam Johnson", market="Points", line_text="10+", line=10.0,
                     price="-1000", label="Cam 10+"),
                dict(lg="nba", id="8", kind="prop", player="Steady Guy", market="Points", line_text="5+", line=5.0,
                     price="-1000", label="Steady 5+"),
                dict(lg="nhl", id="5", kind="prop", player="Mitchell Marner", market="Shots on Goal", line_text="1+",
                     line=1.0, price="-2000", label="Marner 1+")]
        json.dump(legs, open(path, "w"))
        rep = {"asof": "11/24/26 05:30 PM", "rows": [dict(date="11/24/2026", matchup="BOS@WAS", team="Boston Celtics",
                                                           player="Johnson, Cameron", status="Out")],
               "not_submitted": [("11/24/2026", "BOS@WAS", "Washington Wizards")]}
        rows = [dict(lg="nba", id="8", game="BOS @ WSH", home="WSH", away="BOS", home_name="Washington Wizards",
                     away_name="Boston Celtics", home_ml=400, away_ml=-550, market_home=0.17),
                dict(lg="nhl", id="5", game="VGK @ EDM", home="EDM", away="VGK", home_name="Edmonton Oilers",
                     away_name="Vegas Golden Knights", home_ml=-102, away_ml=-118, market_home=0.48)]
        fd = [{"id": "nba:8", "props": [dict(name="Cam Johnson", market="Points", line="10+", price="-1000"),
                                        dict(name="Steady Guy", market="Points", line="5+", price="-1000")]},
              {"id": "nhl:5", "props": [dict(name="Mitchell Marner", market="Shots on Goal", line="1+", price="-1800")]}]
        summary = {"header": {"competitions": [{"competitors": [{"team": {"displayName": "Edmonton Oilers"}},
                                                                {"team": {"displayName": "Vegas Golden Knights"}}]}]}}
        with mock.patch.object(NR, "latest", lambda: ("u", "txt")), mock.patch.object(NR, "parse", lambda t: rep), \
                mock.patch.object(K, "recent_minutes", lambda a, d: {}), \
                mock.patch.object(NG, "fetch_lineup", lambda team: {"Mitch Marner": ""} if "Vegas" in team else {"X Y": ""}), \
                mock.patch("urllib.request.urlopen", lambda *a, **k: io.StringIO(json.dumps(summary))), \
                mock.patch.object(slate_sheet, "main", lambda day: rows), mock.patch.object(B, "_fd_props", lambda r: fd):
            out = R.main(path, "2026-11-24", final=True)
        self.assertIn("NOTE: Washington Wizards has NOT YET SUBMITTED", out)
        self.assertIn("  BOS @ WSH", out)
        self.assertIn("DROP    Cam 10+ -- Cam Johnson is now Out", out)        # nickname matched to 'Johnson, Cameron'
        self.assertIn("KEEP    Steady 5+", out)
        self.assertIn("KEEP    BOS ML -- DraftKings now -550 (was -453), 83% no-vig, the market rates it more likely", out)
        self.assertIn("KEEP    Marner 1+ -- FanDuel now -1800 (was -2000), the market rates it less likely", out)   # Mitch / Mitchell: in the lines
        self.assertIn("3 of 4 legs stay.", out)
        self.assertIn("All 3 kept legs win: about", out)                        # the dropped Cam leg is left out
        self.assertTrue(os.path.exists(os.path.join(d, "price_log.jsonl")))


class AllWinTest(unittest.TestCase):
    def test_current_price_bands(self):
        kept = [dict(kind="prop", lg="nhl", label="Hertl", price="-1300"), dict(kind="ml", label="BOS", price="-453")]
        rec = {("nhl", (-1000, -500)): (80, 100), ("nhl", (-1500, -1000)): (87, 100)}
        line = R.all_win_line(kept, {"Hertl": "-950", "BOS": -453}, {"BOS": 0.79}, rec)
        self.assertEqual(line, "All 2 kept legs win: about 63% -- pays about 1.35x at current prices. "
                               "Each leg stands on its own; the size is your call.")      # 0.80 * 0.79, (1+100/950)(1+100/453)
        self.assertIn("unavailable", R.all_win_line([dict(kind="prop", label="X", price=None)], {}, {}, {}))


class Best2xTest(unittest.TestCase):
    def test_smallest_risk_reaching_2x(self):
        odds = [("a", 1.10, 0.86), ("b", 1.10, 0.86), ("c", 1.25, 0.79), ("d", 1.05, 0.90), ("e", 1.50, 0.60)]
        b = R.best_2x(odds)
        self.assertGreaterEqual(b["pays"], 2.0)
        # brute-force check: no subset reaching 2x is more likely
        import itertools
        bestp = max(math.prod(x[2] for x in c) for k in range(1, 6) for c in itertools.combinations(odds, k)
                    if math.prod(x[1] for x in c) >= 2.0)
        self.assertAlmostEqual(b["chance"], bestp)
        self.assertIsNone(R.best_2x([("a", 1.1, 0.9)]))


class GameNewsTest(unittest.TestCase):
    def test_either_team(self):
        legs = [dict(lg="nba", id="14", kind="prop", player="Jalen Suggs", label="Suggs")]
        rows = [dict(lg="nba", id="14", game="DET @ ORL", away="DET", home="ORL", away_name="Detroit Pistons",
                     home_name="Orlando Magic")]
        news = R.game_news(legs, rows, lambda a: [("Cade Cunningham", 34.1, "Out")] if a == "DET" else [])
        self.assertEqual(news, ["DET @ ORL: Detroit Pistons without Cade Cunningham (34.1 min, Out)"])
        self.assertEqual(R.game_news(legs, rows, lambda a: []), [])
        rep = [dict(date="11/24/2026", team="Orlando Magic", player="Banchero, Paolo", status="Out"),
               dict(date="11/24/2026", team="Orlando Magic", player="Isaac, Jonathan", status="Out"),
               dict(date="11/24/2026", team="Orlando Magic", player="Jones, Tre", status="Probable")]
        news = R.game_news(legs, rows, lambda a: [], rep, "11/24/2026")
        self.assertEqual(news, ["DET @ ORL: Orlando Magic has 2 Out on the report -- Jonathan Isaac, Paolo Banchero"])


class FinalViewTest(unittest.TestCase):
    def test_keep_caution_drop(self):
        legs = [dict(id="1", label="A"), dict(id="1", label="B"), dict(id="2", label="C"), dict(id="2", label="D")]
        flags = [("A", "A Guy is now Out on the official report"), ("B", "FanDuel now -900 (was -1100), the market rates it less likely (91.7% -> 90.0%)"),
                 ("C", "C Guy: a game-time decision"), ("C", "FanDuel now -1300 (was -1200)")]
        out = R.final_text(legs, flags, {"1": "DET @ ORL", "2": "VGK @ EDM"}, "05:30 PM")
        self.assertIn("  DET @ ORL", out)
        self.assertIn("DROP    A -- A Guy is now Out", out)
        self.assertIn("KEEP    B -- FanDuel now -900", out)
        self.assertIn("CAUTION C -- C Guy: a game-time decision; FanDuel now -1300", out)
        self.assertIn("KEEP    D", out)
        self.assertTrue(out.endswith("3 of 4 legs stay."))
        self.assertEqual(R.verdict(["this line is no longer posted at FanDuel"])[0], "DROP")


class NhlLineupTest(unittest.TestCase):
    def test_lineup_page_and_flags(self):
        import json
        import nhl_goalies as NG
        data = {"props": {"pageProps": {"combinations": {"sourceName": "Last Game (2026-11-21)", "players": [
            dict(name="Mitch Marner", categoryIdentifier="ev", groupIdentifier="f1", injuryStatus=None, gameTimeDecision=False),
            dict(name="Mitch Marner", categoryIdentifier="pp", groupIdentifier="pp1", injuryStatus=None, gameTimeDecision=False),
            dict(name="Hurt Guy", categoryIdentifier="oi", groupIdentifier="ir", injuryStatus="ir", gameTimeDecision=False),
            dict(name="Maybe Guy", categoryIdentifier="ev", groupIdentifier="f4", injuryStatus=None, gameTimeDecision=True)]}}}}
        html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + "</script>"
        pg = NG.lineup(html)
        self.assertEqual(pg["Mitch Marner"], "")
        self.assertTrue(R._same("Mitch Marner", "Mitchell Marner"))
        self.assertFalse(R._same("Matt Boldy", "Mike Boldy"))
        self.assertTrue(R._same("Juraj Slafkovsky", "Juraj Slafkovský"))                   # accents
        self.assertTrue(R._same("Sebastian Aho (CAR)", "Sebastian Aho"))                   # FanDuel team tag
        self.assertIn("injured list", pg["Hurt Guy"])
        self.assertEqual(pg["Maybe Guy"], "a game-time decision")
        self.assertEqual(NG.lineup("<html></html>"), {})
        self.assertEqual(NG.slug("Montréal Canadiens"), "montreal-canadiens")
        self.assertEqual(NG.slug("St. Louis Blues"), "st-louis-blues")
        legs = [dict(lg="nhl", kind="prop", id="5", player=n, label=n) for n in
                ("Mitchell Marner", "Hurt Guy", "Maybe Guy", "Scratched Guy")]
        flags = dict(R.recheck_nhl(legs, lambda gid: [pg, {}]))
        self.assertNotIn("Mitchell Marner", flags)
        self.assertIn("injured list", flags["Hurt Guy"])
        self.assertIn("game-time decision", flags["Maybe Guy"])
        self.assertIn("not in either team's projected lines (Last Game (2026-11-21))", flags["Scratched Guy"])
        self.assertEqual(R.recheck_nhl(legs, lambda gid: [{}, {}]), [])       # unreachable: silent


class BestCoverTest(unittest.TestCase):
    def test_large_ticket_matches_exhaustive_and_has_an_answer(self):
        """2026-11-25: past 16 legs best_2x returned None, so a 70-leg ticket
        printed no 2x line; the search past the cap must equal exhaustive."""
        import random
        rnd = random.Random(11)
        for _ in range(80):
            odds = [(i, 1 + rnd.choice([.06, .1, .15, .25, .33, 1.1]), round(rnd.uniform(.5, .95), 3))
                    for i in range(rnd.randint(1, 12))]
            a, b = R.best_2x(odds), R._best_cover(odds, 2.0)
            self.assertEqual(a is None, b is None)
            if a:
                self.assertAlmostEqual(a["chance"], b["chance"], places=9)
                self.assertGreaterEqual(b["pays"], 2.0 - 1e-9)
        big = [(i, 1.1, 0.86) for i in range(70)]
        got = R.best_2x(big)
        self.assertEqual(len(got["legs"]), 8)                   # 1.1^8 = 2.14x, fewest legs, best chance
        mixed = R.best_2x([(0, 1.1, 0.9)] * 3 + [(1, 1.05, 0.9)] * 14)              # 17 legs: past the cap
        self.assertGreaterEqual(mixed["pays"], 2.0)
        self.assertEqual(len(mixed["legs"]), 12)                 # all three 1.1s, then 1.05^8 = 1.97x, ^9 = 2.06x


class NoteDroppedTest(unittest.TestCase):
    def test_drops_recorded_beside_ticket_and_grader_skips_them(self):
        import json
        import tempfile
        import grade_picks as G
        path = os.path.join(tempfile.mkdtemp(), "ticket.json")
        legs = [dict(label="Malkin 1+ SOG"), dict(label="Karlsson 1+ SOG")]
        json.dump(legs, open(path, "w"))
        flags = [("Malkin 1+ SOG", "Evgeni Malkin: on the injured list (dtd)"), ("Karlsson 1+ SOG", "FanDuel now -2100")]
        self.assertEqual(R.note_dropped(path, legs, flags), ["Malkin 1+ SOG"])
        self.assertEqual(R.note_dropped(path, legs, []), ["Malkin 1+ SOG"])           # earlier drops kept
        self.assertEqual(R.note_dropped(path, legs, [], fresh=lambda L: False), ["Malkin 1+ SOG"])  # source not read
        self.assertEqual(R.note_dropped(path, legs, [], fresh=True), [])              # upgraded since: back on
        self.assertEqual([L["label"] for L in G.load(path)], ["Malkin 1+ SOG", "Karlsson 1+ SOG"])
        R.note_dropped(path, legs, flags)
        self.assertEqual([L["label"] for L in G.load(path)], ["Karlsson 1+ SOG"])
        self.assertEqual(len(json.load(open(path))), 2)                                # the ticket is untouched
        self.assertEqual(G.dropped_count(path), 1)
        lad = os.path.join(os.path.dirname(path), "ticket_ladder.json")
        json.dump([legs[0]], open(lad, "w"))
        self.assertEqual(G.load(lad), [])                                              # the stand-in follows


class SavedLineTest(unittest.TestCase):
    def test_morning_combo_at_current_prices_and_drops(self):
        legs = [dict(label="A", kind="ml", price="-400", lg="nba"), dict(label="B", kind="ml", price="-400", lg="nba")]
        out = R.final_text(legs, [], now_prices={"A": "-300"}, now_chance={"A": 0.74, "B": 0.79}, record={},
                           saved={"2x": ["A", "B"]})
        self.assertIn("Your morning 2x: 2 legs, now about 58% all win, pays 1.67x at current prices.", out)
        out = R.final_text(legs, [("B", "B is now Out on the official report")], now_prices={}, now_chance={}, record={},
                           saved={"2x": ["A", "B"]})
        self.assertIn("Your morning 2x: 1 of its 2 legs now DROP", out)


class LadderNowTest(unittest.TestCase):
    def test_one_per_game_at_current_prices(self):
        legs = [dict(label=f"G{i}", kind="ml", price="-400", lg="nba", id=str(i)) for i in range(4)]
        legs.append(dict(label="G0b", kind="ml", price="-400", lg="nba", id="0"))
        out = R.ladder_now(legs, {}, {L["label"]: 0.8 for L in legs}, {})
        self.assertTrue(out.startswith("Ladder stand-in now (one leg per game, 2x-5x): 4 legs, about 41% all win, pays 2.44x"), out)
        self.assertEqual(R.ladder_now(legs[:2], {}, {"G0": 0.8, "G1": 0.8}, {}), "")

    def test_started_games_left_out_of_fresh_suggestions(self):
        legs = [dict(label=f"G{i}", kind="ml", price="-400", lg="nba", id=str(i)) for i in range(5)]
        ch = {L["label"]: 0.8 for L in legs}
        out = R.final_text(legs, [], now_prices={}, now_chance=ch, record={}, started={"0", "1"})
        lad = [x for x in out.splitlines() if x.startswith("Ladder stand-in now")]
        self.assertEqual(lad, [])                                   # 3 open games at 1.25x cannot reach 2x
        out = R.final_text(legs, [], now_prices={}, now_chance=ch, record={}, started={"0"})
        self.assertIn("Ladder stand-in now (one leg per game, 2x-5x): 4 legs", out)
        self.assertNotIn("G0", out.split("Ladder stand-in now")[1])


class StartedPriceTest(unittest.TestCase):
    def test_started_leg_keeps_its_saved_price_in_the_payout(self):
        """2026-11-26 8 PM: in-play prices on games under way read '3.73x'."""
        legs = [dict(label="A", id="1", kind="ml", price="-500"), dict(label="B", id="2", kind="ml", price="-500")]
        out = R.final_text(legs, [], now_prices={"A": "+400", "B": "-500"}, now_chance={"A": 0.8, "B": 0.8},
                           record={}, started={"1"})
        self.assertIn("pays about 1.44x", out)                                     # 1.2 x 1.2, not 5.0 x 1.2

class FreshFnTest(unittest.TestCase):
    def test_undo_only_when_the_legs_own_sources_were_read(self):
        nba, nhl, nfl = dict(lg="nba", id="1"), dict(lg="nhl", id="7"), dict(lg="nfl", id="9")
        f = R.fresh_fn(True, True, {"7": [{"lines": 1}, {"lines": 2}]})
        self.assertTrue(f(nba) and f(nhl))
        self.assertFalse(f(nfl))                                              # NFL drops are kept
        self.assertFalse(R.fresh_fn(True, False, {"7": [1, 1]})(nba))         # prices not read
        self.assertFalse(R.fresh_fn(False, True, {})(nba))                    # report not read
        self.assertFalse(R.fresh_fn(True, True, {"7": [{"lines": 1}, None]})(nhl))   # one team's lines failed
        self.assertFalse(R.fresh_fn(True, True, {})(nhl))
        nfl = dict(lg="nfl", id="9")
        self.assertFalse(R.fresh_fn(True, True, {})(nfl))                       # NFL report not read
        self.assertTrue(R.fresh_fn(True, True, {}, nfl_ok=True)(nfl))           # both read: drop can be undone
        self.assertFalse(R.fresh_fn(True, False, {}, nfl_ok=True)(nfl))         # prices not read


class StartedNeverDroppedTest(unittest.TestCase):
    def test_a_leg_in_a_started_game_is_not_dropped_and_old_drops_stand(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "ticket.json")
        legs = [dict(label="Klay 5+", id="7"), dict(label="Malkin 1+", id="8")]
        json.dump(legs, open(path, "w"))
        R.note_dropped(path, legs, [("Malkin 1+", "Evgeni Malkin: on the injured list (dtd)")])
        pulled = [("Klay 5+", "this line is no longer posted at FanDuel (pulled)"),
                  ("Malkin 1+", "Evgeni Malkin: on the injured list (dtd)")]
        got = R.note_dropped(path, legs, pulled, fresh=True, started={"7", "8"})
        self.assertEqual(got, ["Malkin 1+"])       # Klay's game began: not dropped; Malkin's earlier drop stands

    def test_pull_history(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "ticket_safe.json")
        recs = [{"t": "2026-11-27T15:53:48", "prices": {"Kuminga: 5+ Points": None, "Shead: 2+ Assists": "-7000"}},
                {"t": "2026-11-27T15:55:08", "prices": {"Kuminga: 5+ Points": None, "Shead: 2+ Assists": "-7000"}},
                {"t": "2026-11-27T16:13:47", "prices": {"Kuminga: 5+ Points": "-10000", "Shead: 2+ Assists": None}}]
        open(os.path.join(d, "price_log.jsonl"), "w").write("\n".join(json.dumps(r) for r in recs) + "\n")
        self.assertEqual(R.pull_history(path), "Pulled earlier and posted again: Kuminga (down 15:53-15:55 UTC)")
        self.assertEqual(R.pull_history(os.path.join(tempfile.mkdtemp(), "t.json")), "")

    def test_injured_list_needs_a_second_source(self):
        leg = [dict(label="Kirill Marchenko: 1+ Shots on Goal -1500", lg="nhl", kind="prop",
                    player="Kirill Marchenko", id="1")]
        pages = lambda gid: [{"Kirill Marchenko": "on the injured list (ir)"}, {"x": ""}]
        alone = R.recheck_nhl(leg, pages, espn_injured={"Max Domi"})
        self.assertEqual(R.verdict([alone[0][1]])[0], "CAUTION")
        self.assertIn("DailyFaceoff only", alone[0][1])
        both = R.recheck_nhl(leg, pages, espn_injured={"Kirill Marchenko"})
        self.assertEqual(R.verdict([both[0][1]])[0], "DROP")
        unread = R.recheck_nhl(leg, pages)                 # ESPN not read: DailyFaceoff stands
        self.assertEqual(R.verdict([unread[0][1]])[0], "DROP")
        feed = {"injuries": [{"injuries": [{"athlete": {"displayName": "Max Domi"}}]}]}
        self.assertEqual(R.espn_nhl_injured(lambda u: feed), {"Max Domi"})
        self.assertIsNone(R.espn_nhl_injured(lambda u: 1 / 0))

    def test_pulled_hours_before_is_a_caution(self):
        import datetime as dt
        legs = [dict(label="Shead: 2+ Assists", kind="prop", player="Jamal Shead", market="Assists",
                     line_text="2+", price="-7000", id="9")]
        now = dt.datetime(2026, 11, 27, 16, 0, tzinfo=dt.timezone.utc)
        early = R.price_check(legs, {("x", "y", "z"): "-100"}, {"9": "2026-11-28T00:30Z"}, now)
        self.assertIn("not posted at FanDuel right now", early[0][1])
        self.assertEqual(R.verdict([early[0][1]])[0], "CAUTION")
        late = R.price_check(legs, {("x", "y", "z"): "-100"}, {"9": "2026-11-27T17:00Z"}, now)
        self.assertEqual(R.verdict([late[0][1]])[0], "DROP")
        self.assertEqual(R.verdict([R.price_check(legs, {("x", "y", "z"): "-100"})[0][1]])[0], "DROP")   # start unknown

    def test_text_one_line_per_leg_drop_first(self):
        """2026-11-27: Marchenko's injured-list note and his price move printed
        on separate lines; now one line, the drop reason first."""
        flags = [("K M: 1+ Shots on Goal -1500", "FanDuel now -1600 (was -1500)"),
                 ("X: 5+ Points -4000", "FanDuel now -3500 (was -4000)"),
                 ("K M: 1+ Shots on Goal -1500", "K M: on the injured list (ir)")]
        out = R.text(flags).split("\n")
        self.assertEqual(out[1], "  DROP: K M: 1+ Shots on Goal -1500 -- K M: on the injured list (ir); "
                                 "FanDuel now -1600 (was -1500)")
        self.assertEqual(out[2], "  X: 5+ Points -4000 -- FanDuel now -3500 (was -4000)")
        self.assertEqual(len(out), 3)

    def test_final_text_shows_started_legs_live_not_dropped(self):
        legs = [dict(label="Klay 5+", kind="ml", price="-400", lg="nba", id="7"),
                dict(label="Other", kind="ml", price="-400", lg="nba", id="9")]
        out = R.final_text(legs, [("Klay 5+", "this line is no longer posted at FanDuel")], now_prices={},
                           now_chance={"Klay 5+": 0.8, "Other": 0.8}, record={}, saved={"ladder": ["Klay 5+", "Other"]},
                           started={"7"})
        self.assertIn("LIVE    Klay 5+", out)
        self.assertIn("2 of 2 legs stay.", out)
        self.assertNotIn("now DROP", out)


class SavedFilesTest(unittest.TestCase):
    def test_each_ticket_reads_its_own_2x_and_ladder(self):
        import recheck_ticket as RT
        self.assertEqual(RT.saved_files("w/ticket.json"), [("ticket_2x.json", "2x"), ("ticket_ladder.json", "ladder stand-in")])
        self.assertEqual(RT.saved_files("w/ticket_safe.json"),
                         [("ticket_safe_2x.json", "2x"), ("ticket_safe_ladder.json", "ladder stand-in")])


if __name__ == "__main__":
    unittest.main()
