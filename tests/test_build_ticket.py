import os
import sys
import math
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import build_ticket as B  # noqa: E402


def row(team, mc, gid="nba:1", price="-400"):
    return dict(mp=team, mc=mc, id=gid, p=price, abbr=team[:3].upper(), match="A @ B")


class JudgeWinnerTest(unittest.TestCase):
    def test_nov23_mistakes_are_left_off(self):
        # Thunder: 63%
        self.assertFalse(B.judge_winner(row("Thunder", 63), [], 0.6)[0])
        # Raptors: key players out -- a caution, not a cut (priced in on the record)
        ok, why = B.judge_winner(row("Raptors", 79), [("Kawhi Leonard", 33.0, "Out")], 0.75)
        self.assertTrue(ok)
        self.assertIn("caution: Kawhi Leonard (Out)", why)
        # Cavaliers-like: our number on the other side
        ok, why = B.judge_winner(row("Cavaliers", 76), [], 0.38)
        self.assertFalse(ok)
        self.assertIn("other side", why)
        self.assertIn("Star (Questionable)", B.judge_winner(row("X", 80), [("Star", 34.0, "Questionable")], 0.7)[1])
        # clean favourite passes
        self.assertEqual(B.judge_winner(row("Lakers", 85), [], 0.72), (True, ""))
        self.assertTrue(B.judge_winner(row("Lakers", 85), [], None)[0])


class BuildTest(unittest.TestCase):
    def test_layout_left_off_and_props(self):
        rows = {"nba": [row("Lakers", 85, "nba:1"), row("Raptors", 79, "nba:2")]}
        props = [{"id": "nba:1", "match": "UTAH @ LAL", "props": [
            dict(name="Good Player", label="Good Player: 10+ Points", p=0.87, imp=0.9, price="-900", market="Points", line="10+"),
            dict(name="Hurt Player", label="Hurt Player: 5+ Points", p=0.87, imp=0.95, price="-1900", market="Points", line="5+")]}]
        t = B.build(rows, props,
                    key_out_fn=lambda r: [("Kawhi Leonard", 33.0, "Out")] if r["mp"] == "Raptors" else [],
                    blind_fn=lambda r: 0.7,
                    status_fn=lambda n: "Questionable" if n == "Hurt Player" else None,
                    fav_fn=lambda gid: 85)
        legs = [L for g in t["games"].values() for L in g]
        self.assertEqual([L["kind"] for L in legs], ["ml", "ml", "prop"])
        self.assertIn("caution: Kawhi Leonard (Out)", legs[1]["label"])
        self.assertEqual(legs[2]["stat"], "PTS")
        self.assertEqual(legs[2]["line"], 10.0)
        self.assertIn("blowout", legs[2]["label"])
        reasons = dict(t["left_off"])
        self.assertTrue(any("Questionable" in v for v in reasons.values()))
        out = B.text(t)
        self.assertIn("3 legs", out)
        self.assertIn("Left off, and why:", out)


    def test_prop_locks_go_first_and_are_labelled(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name=f"P{i}", label=f"P{i}: 5+ Points", p=0.87, imp=0.9 - i / 100, price="-900", market="Points", line="5+")
            for i in range(5)]}]
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda gid: 0, prop_locks={"P4"})
        legs = [L for g in t["games"].values() for L in g]
        self.assertEqual(legs[0]["player"], "P4")
        self.assertIn("Prop Lock", legs[0]["label"])
        self.assertEqual(len(legs), B.PER_GAME)
        self.assertNotIn("Prop Lock", legs[1]["label"])


class BoardSlotTest(unittest.TestCase):
    def test_slot_by_date_and_stale(self):
        D = {"dates": {"today": "20261123", "tomorrow": "20261124"}}
        self.assertEqual(B.board_slot(D, "2026-11-23"), "today")
        self.assertEqual(B.board_slot(D, "2026-11-24"), "tomorrow")
        with self.assertRaises(B.StaleBoard):
            B.board_slot(D, "2026-11-25")

    def test_old_build_is_stale(self):
        import datetime as dt
        D = {"dates": {"today": "20261123", "tomorrow": "20261124"}, "at": "Nov 23, 7:56 PM ET"}
        at8 = dt.datetime(2026, 11, 24, 13, 5, tzinfo=dt.timezone.utc)          # 8:05 AM ET
        self.assertAlmostEqual(B.board_age_h(D, at8), 12.15, places=2)
        with self.assertRaises(B.StaleBoard):
            B.board_slot(D, "2026-11-24", now=at8)
        at9pm = dt.datetime(2026, 11, 24, 2, 0, tzinfo=dt.timezone.utc)          # 9 PM ET Nov 23
        self.assertEqual(B.board_slot(D, "2026-11-24", now=at9pm), "tomorrow")
        self.assertIsNone(B.board_age_h({"at": "soon"}, at8))
        jan = dt.datetime(2027, 1, 1, 6, 0, tzinfo=dt.timezone.utc)
        self.assertAlmostEqual(B.board_age_h({"at": "Dec 31, 11:00 PM ET"}, jan), 2.0)


class FallbackTest(unittest.TestCase):
    def test_winners_from_prices(self):
        rows = [dict(lg="nba", game="DAL @ DEN", id="9", home="DEN", away="DAL", home_ml=-322, away_ml=260,
                     market_home=0.73, blind_home=0.59),
                dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453,
                     market_home=0.21, blind_home=0.28),
                dict(lg="nhl", game="X @ Y", id="7", home="Y", away="X", home_ml=-400, away_ml=300,
                     market_home=0.78, blind_home=0.40)]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda rows: [])
        legs = [L for g in t["games"].values() for L in g]
        self.assertEqual([(L["team"], L["price"]) for L in legs], [("BOS", "-453")])
        reasons = dict(t["left_off"])
        self.assertTrue(any("under 75%" in v for v in reasons.values()))         # Denver 73%
        self.assertTrue(any("other side" in v for v in reasons.values()))       # Y: our number 40%
        self.assertIn("NOTE: The board has not rebuilt", B.text(t))


class BackToBackTest(unittest.TestCase):
    def test_caution_on_board_and_fallback_legs(self):
        t = B.build({"nba": [row("Celtics", 80, "nba:1")]}, [], key_out_fn=lambda r: [], blind_fn=lambda r: 0.7,
                    status_fn=lambda n: None, fav_fn=lambda g: 0, b2b_fn=lambda r: True)
        legs = [L for g in t["games"].values() for L in g]
        self.assertIn("back-to-back", legs[0]["label"])
        rows = [dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453,
                     market_home=0.21, blind_home=0.28)]
        f = B.fallback("2026-11-24", rows, b2b_fn=lambda team, day: team == "BOS", props_fn=lambda rows: [])
        self.assertIn("back-to-back", [L for g in f["games"].values() for L in g][0]["label"])


class FallbackPropsTest(unittest.TestCase):
    def test_fanduel_props_join_the_ticket(self):
        rows = [dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=500, away_ml=-700,
                     market_home=0.15, blind_home=0.28)]
        pg = [{"id": "nba:8", "match": "BOS @ WSH", "props": [
            dict(name="Jaylen Brown", label="Jaylen Brown: 15+ Points", p=0.87, imp=0.9, price="-900", market="Points", line="15+"),
            dict(name="Hurt Guy", label="Hurt Guy: 5+ Points", p=0.87, imp=0.95, price="-2000", market="Points", line="5+")]}]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda r: pg,
                       status_fn=lambda n: "Out" if n == "Hurt Guy" else None, minutes_fn=lambda g, n: {},
                       logs_fn=lambda g, n: {})
        legs = t["games"]["BOS @ WSH"]
        self.assertEqual([L["kind"] for L in legs], ["ml", "prop"])
        self.assertEqual(legs[1]["player"], "Jaylen Brown")
        self.assertIn("big favourite", legs[1]["label"])          # 85% favourite: blowout flag
        self.assertTrue(any("Out on the official injury report" in why for _, why in t["left_off"]))

    def test_fanduel_down_still_gives_winners(self):
        def boom(rows):
            raise OSError("down")
        rows = [dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453,
                     market_home=0.21, blind_home=0.28)]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=boom)
        self.assertIn("no props (FanDuel unreachable)", t["note"])
        self.assertEqual(len(t["games"]["BOS @ WSH"]), 1)


class MinutesCautionTest(unittest.TestCase):
    def test_low_minutes_props_carry_the_card_caution(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name="Bench Guy", label="Bench Guy: 4+ Rebounds", p=0.87, imp=0.9, price="-1200", market="Rebounds", line="4+"),
            dict(name="Starter", label="Starter: 15+ Points", p=0.87, imp=0.9, price="-1000", market="Points", line="15+")]}]
        seen = []
        def mins(gid, names):
            seen.append((gid, names))
            return {"Bench Guy": 14.2, "Starter": 33.0}
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda g: 0, minutes_fn=mins)
        legs = {L["player"]: L["label"] for L in t["games"]["A @ B"]}
        self.assertIn("caution: 14.2 min a game over his last 5", legs["Bench Guy"])
        self.assertNotIn("caution", legs["Starter"])
        self.assertEqual(seen, [("nba:1", ["Bench Guy", "Starter"])])     # one lookup per game
        self.assertEqual(len(t["games"]["A @ B"]), 2)                      # a caution, not a cut

    def test_minutes_failure_leaves_ticket_alone(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name="X", label="X: 4+ Rebounds", p=0.87, imp=0.9, price="-1200", market="Rebounds", line="4+")]}]
        def boom(g, n):
            raise OSError("down")
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda g: 0, minutes_fn=boom)
        self.assertEqual(t["games"]["A @ B"][0]["label"], "X: 4+ Rebounds -1200 (87%)")


class PropRecordTest(unittest.TestCase):
    def test_chance_uses_the_record_for_its_price_band(self):
        props = {f"k{i}": dict(league="nba", price="-1200", status="won" if i < 85 else "lost") for i in range(100)}
        props["open"] = dict(league="nba", price="-1200", status="open")
        props["nhl"] = dict(league="nhl", price="-1200", status="won")
        rec = B.prop_record(props)
        self.assertEqual(rec[("nba", (-1500, -1000))], (85, 100))
        t = {"games": {"A @ B": [dict(kind="prop", lg="nba", price="-1200", chance=0.8727, label="X: 4+ Rebounds"),
                                 dict(kind="prop", lg="nhl", price="-1200", chance=0.8727, label="Y: 1+ Shots"),
                                 dict(kind="ml", lg="nba", price="-453", chance=0.79, label="BOS")]}}
        B.apply_record(t, rec)
        legs = t["games"]["A @ B"]
        self.assertAlmostEqual(legs[0]["chance"], 0.85)
        self.assertIn("[props like it 85% on 100]", legs[0]["label"])
        self.assertEqual(legs[1]["chance"], 0.8727)                 # under RECORD_MIN graded: left as stated
        self.assertEqual(legs[2]["label"], "BOS")
        self.assertEqual(B._band("-300"), (-500, -300))
        self.assertIsNone(B._band("+150"))

    def test_record_never_raises_a_chance(self):
        rec = {("nba", (-10 ** 6, -2500)): (96, 100)}
        t = {"games": {"G": [dict(kind="prop", lg="nba", price="-3000", chance=0.8727, label="Z")]}}
        B.apply_record(t, rec)
        self.assertEqual(t["games"]["G"][0]["chance"], 0.8727)


class GoalieNoteTest(unittest.TestCase):
    def test_nhl_winner_carries_its_goalie(self):
        import nhl_goalies as NG
        gr = [dict(away="Vegas Golden Knights", home="Edmonton Oilers", away_goalie="Carter Hart", away_status="Unconfirmed",
                   away_at=None, home_goalie="Devon Levi", home_status="Confirmed", home_at=None)]
        ros = {"Edmonton Oilers": [("Stuart Skinner", 15, 0.9), ("Devon Levi", 2, 0.91)]}
        n = NG.leg_note("Edmonton Oilers", gr, ros, career_fn=lambda g: None)
        self.assertIn("goalie: Devon Levi (Confirmed)", n)
        self.assertIn("not the usual starter", n)
        self.assertNotIn("check the confirmed", n)
        self.assertIn("check the confirmed starter", NG.leg_note("Vegas Golden Knights", gr, {}, career_fn=lambda g: None))
        self.assertEqual(NG.leg_note("Boston Bruins", gr), "")
        mtl = [dict(away="Montréal Canadiens", away_goalie="Jacob Fowler", away_status="Confirmed", home="Colorado Avalanche")]
        self.assertIn("goalie: Jacob Fowler", NG.leg_note("Montreal Canadiens", mtl, {}, career_fn=lambda g: None))
        self.assertEqual(NG.leg_note("", mtl), "")
        rows = [dict(lg="nhl", game="VGK @ EDM", id="5", home="EDM", away="VGK", home_name="Edmonton Oilers",
                     away_name="Vegas Golden Knights", home_ml=-500, away_ml=380, market_home=0.82, blind_home=0.7)]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda r: [],
                       goalie_fn=lambda team: NG.leg_note(team, gr, ros, career_fn=lambda g: None),
                       nhl_b2b_fn=lambda *a: False)
        self.assertIn("goalie: Devon Levi", t["games"]["VGK @ EDM"][0]["label"])


class SafestTest(unittest.TestCase):
    def test_keeps_only_the_safest_bands(self):
        t = {"games": {"G": [dict(kind="prop", lg="nba", price="-3000", label="a"),
                             dict(kind="prop", lg="nba", price="-1600", label="b"),
                             dict(kind="prop", lg="nhl", price="-1600", label="c"),
                             dict(kind="ml", lg="ncaab", price="-2000", chance=0.94, label="d"),
                             dict(kind="ml", lg="nba", price="-400", chance=0.78, label="e")],
                       "H": [dict(kind="prop", lg="nba", price="-900", label="f")]}}
        got = B.safest(t)
        self.assertEqual([L["label"] for L in got["games"]["G"]], ["a", "c", "d"])
        self.assertNotIn("H", got["games"])


class SafestPerPlayerTest(unittest.TestCase):
    def test_best_paying_line_inside_the_safe_band(self):
        props = [dict(name="A", price="-1000"), dict(name="A", price="-3000"), dict(name="A", price="-6000"),
                 dict(name="B", price="-900"), dict(name="C", price="-1600")]
        self.assertEqual([(p["name"], p["price"]) for p in B.safest_per_player(props, "nba")], [("A", "-3000")])
        self.assertEqual([(p["name"], p["price"]) for p in B.safest_per_player(props, "nhl")],
                         [("A", "-3000"), ("C", "-1600")])


class TwoXLegsTest(unittest.TestCase):
    def test_the_saved_2x_is_the_printed_2x(self):
        legs = [dict(label=f"L{i}", price="-1000", chance=0.86) for i in range(9)]
        t = {"games": {"G": legs}}
        got = B.two_x_legs(t)
        self.assertEqual(len(got), 8)                                   # 1.1^8 = 2.14x, as two_x_text says
        self.assertIn(f"{len(got)} legs", B.two_x_text(legs))
        self.assertEqual(B.two_x_legs({"games": {"G": legs[:3]}}), [])  # cannot reach 2x
        self.assertEqual(B.two_x_legs({"games": {"G": [dict(label="x", price=None, chance=0.9)]}}), [])


class ChanceTextTest(unittest.TestCase):
    def test_small_chances_read_as_odds(self):
        self.assertEqual(B.chance_text(0.354), "about 35%")
        self.assertEqual(B.chance_text(0.87 ** 70), "about 1 in 17,000")
        self.assertEqual(B.chance_text(0.004), "about 1 in 250")
        self.assertEqual(B.chance_text(0.0), "about 0%")


class SaveTicketTest(unittest.TestCase):
    def test_saves_ticket_and_stand_in_and_never_overwrites(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "slate_x", "ticket.json")
        leg = dict(label="L", price="-500", chance=0.8, gid="nba:1", lg="nba", id="1", kind="ml", team="BOS")
        t = {"games": {"G": [leg, dict(leg, label="M", id="2")]}}
        out = B.save_ticket(t, path, combo=[leg])
        self.assertIn("saved:", out[0])
        self.assertEqual(len(json.load(open(path))), 2)
        lad = json.load(open(os.path.join(d, "slate_x", "ticket_ladder.json")))
        self.assertEqual([L["label"] for L in lad], ["L"])
        self.assertNotIn("chance", lad[0])                       # grade_picks' file format
        again = B.save_ticket({"games": {"G": [leg]}}, path, combo=[leg])
        self.assertIn("not saved", again[0])
        self.assertEqual(len(json.load(open(path))), 2)          # the sent ticket is untouched
        self.assertEqual(B.save_ticket(t, None), [])


class QuestionableNoteTest(unittest.TestCase):
    def test_note_only_when_someone_was_left_off_as_questionable(self):
        t = {"games": {}, "left_off": [("Giannis 4+ Assists", "Questionable on the official injury report")]}
        self.assertIn(B.QUESTIONABLE_NOTE, B.text(t))
        t = {"games": {}, "left_off": [("NY moneyline", "board chance 60% is under 75%")]}
        self.assertNotIn(B.QUESTIONABLE_NOTE, B.text(t))


class NflStatusTest(unittest.TestCase):
    def test_nfl_report_flattened(self):
        rows = {"Green Bay Packers": [["Josh Jacobs", "Questionable"], ["Luke Musgrave", "Out"]]}
        self.assertEqual(B.nfl_status(lambda: rows), {"Josh Jacobs": "Questionable", "Luke Musgrave": "Out"})

    def test_unreadable_report_is_empty(self):
        def boom():
            raise OSError("down")
        self.assertEqual(B.nfl_status(boom), {})

    def test_questionable_nfl_player_left_off(self):
        ok, why, _ = B.judge_prop({"name": "Josh Jacobs"}, B.nfl_status(lambda: {"GB": [["Josh Jacobs", "Questionable"]]})["Josh Jacobs"])
        self.assertFalse(ok)
        self.assertIn("Questionable", why)


class NcaabOptInTest(unittest.TestCase):
    def test_only_90_plus_favourites(self):
        rows = [dict(lg="ncaab", game="JAX @ IU", id="1", home="IU", away="JAX", home_ml=-100000, away_ml=5000, market_home=0.981),
                dict(lg="ncaab", game="GONZ VS KSU", id="2", home="KSU", away="GONZ", home_ml=900, away_ml=-1600, market_home=0.096),
                dict(lg="ncaab", game="A @ B", id="3", home="B", away="A", home_ml=-400, away_ml=300, market_home=0.78),
                dict(lg="ncaab", game="C @ D", id="4", home="D", away="C", home_ml=None, away_ml=None, market_home=None)]
        g = B.ncaab_legs(rows)
        self.assertEqual(sorted(g), ["GONZ VS KSU", "JAX @ IU"])
        self.assertEqual(g["GONZ VS KSU"][0]["team"], "GONZ")
        self.assertEqual(g["GONZ VS KSU"][0]["price"], "-1600")
        self.assertIn("opt-in", g["JAX @ IU"][0]["label"])

    def test_rows_from_espn_shape(self):
        ev = {"id": "9", "date": "2026-11-24T23:00Z", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"abbreviation": "IU", "displayName": "Indiana"}},
            {"homeAway": "away", "team": {"abbreviation": "JAX", "displayName": "Jacksonville"}}]}]}
        sm = {"pickcenter": [{"homeTeamOdds": {"moneyLine": -2000}, "awayTeamOdds": {"moneyLine": 1000}}]}
        get = lambda u: {"events": [ev]} if "scoreboard" in u else sm
        r = B.ncaab_rows("2026-11-24", get=get)
        self.assertEqual((r[0]["home"], r[0]["home_ml"], r[0]["blind_home"]), ("IU", -2000, None))
        self.assertGreater(r[0]["market_home"], 0.9)


class ResolveDayTest(unittest.TestCase):
    def test_words_and_dates(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 24, 3, 0, tzinfo=dt.timezone.utc)      # 10 PM Nov 23 in ET
        self.assertEqual(B.resolve_day("today", now), "2026-11-23")
        self.assertEqual(B.resolve_day(None, now), "2026-11-23")
        self.assertEqual(B.resolve_day("tomorrow", now), "2026-11-24")
        self.assertEqual(B.resolve_day("2026-11-25", now), "2026-11-25")
        with self.assertRaises(ValueError):
            B.resolve_day("tday", now)


class Last10CautionTest(unittest.TestCase):
    def test_under_70_percent_flagged(self):
        import nba_minutes as M
        reb = [4, 10, 6, 4, 3, 3, 2, 5, 1, 4]            # Gafford's last 10: 4+ in 6
        rows = [dict(d=f"2026-11-{20 - i:02d}", MIN=20.0, PTS=8.0, REB=float(r), AST=1.0) for i, r in enumerate(reb)]
        self.assertEqual(M.last10_hits(rows, "Rebounds", 4.0), (6, 10))
        self.assertIsNone(M.last10_hits(rows[:4], "Rebounds", 4.0))
        self.assertIsNone(M.last10_hits(rows, "Blocks", 1.0))
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name="Daniel Gafford", label="Daniel Gafford: 4+ Rebounds", p=0.87, imp=0.9, price="-1600", market="Rebounds", line="4+"),
            dict(name="Steady", label="Steady: 4+ Rebounds", p=0.87, imp=0.9, price="-1600", market="Rebounds", line="4+")]}]
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda g: 0, logs_fn=lambda g, n: {"Daniel Gafford": rows,
                                                             "Steady": [dict(r, REB=8.0) for r in rows]})
        lab = {L["player"]: L["label"] for L in t["games"]["A @ B"]}
        self.assertIn("caution: reached it in 6 of his last 10", lab["Daniel Gafford"])
        self.assertNotIn("caution", lab["Steady"])
        self.assertNotIn("no ESPN game log", lab["Steady"])

    def test_missing_game_log_is_said_not_skipped(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name="Ghost", label="Ghost: 4+ Rebounds", p=0.87, imp=0.9, price="-1600", market="Rebounds", line="4+")]}]
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda g: 0, logs_fn=lambda g, n: {})
        self.assertIn("no ESPN game log found, last-10 check skipped", t["games"]["A @ B"][0]["label"])

    def test_games_sorted_newest_first(self):
        import nba_minutes as M
        log = {"labels": ["MIN", "PTS", "REB", "AST"], "events": {"1": {"gameDate": "2026-11-01"}, "2": {"gameDate": "2026-11-20"}},
               "seasonTypes": [{"displayName": "2026-27 Regular Season", "categories": [{"events": [
                   {"eventId": "1", "stats": ["30", "10", "5", "2"]}, {"eventId": "2", "stats": ["31", "20", "6", "3"]}]}]}]}
        self.assertEqual([r["PTS"] for r in M.games(log)], [20.0, 10.0])


class NhlBackToBackTest(unittest.TestCase):
    def test_nhl_b2b_caution(self):
        import nhl_goalies as NG
        sched = {"club-schedule/EDM/week/2026-11-23": {"games": [{"gameDate": "2026-11-23"}, {"gameDate": "2026-11-24"}]}}
        self.assertTrue(NG.played_day_before("EDM", "2026-11-24", get=sched.get))
        self.assertFalse(NG.played_day_before("VGK", "2026-11-24", get=sched.get))
        rows = [dict(lg="nhl", game="VGK @ EDM", id="5", home="EDM", away="VGK", home_name="Edmonton Oilers",
                     away_name="Vegas Golden Knights", home_ml=-500, away_ml=380, market_home=0.82, blind_home=0.7)]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda r: [], goalie_fn=lambda t: "",
                       nhl_b2b_fn=lambda tri, d: tri == "EDM")
        self.assertIn("back-to-back (often the backup goalie", t["games"]["VGK @ EDM"][0]["label"])


class TwoXTest(unittest.TestCase):
    def test_two_x_line(self):
        legs = [dict(label=f"L{i} -1000 (87%)", price="-1000", chance=0.86) for i in range(9)]
        out = B.two_x_text(legs)
        self.assertTrue(out.startswith("Most likely 2x from these legs: 8 legs"))     # 1.1^8 = 2.14x
        self.assertEqual(B.two_x_text(legs[:3]), "")                                 # cannot reach 2x
        t = {"games": {"G": legs}, "left_off": []}
        self.assertIn("Most likely 2x", B.text(t))


class LadderFallbackTest(unittest.TestCase):
    def test_one_leg_per_game_in_band(self):
        t = {"games": {f"G{i}": [dict(label=f"leg{i}", price="-400", chance=0.80, lg="nba", id=str(i), gid=f"nba:{i}"),
                                  dict(label=f"leg{i}b", price="-400", chance=0.79, lg="nba", id=str(i), gid=f"nba:{i}")]
                       for i in range(8)}, "left_off": []}
        combo = B.ladder_fallback(t)
        self.assertTrue(combo)
        self.assertEqual(len({L["gid"] for L in combo}), len(combo))      # one per game
        pays = 1
        for L in combo:
            pays *= B._dec(L["price"])
        self.assertTrue(2.0 <= pays <= 5.0)
        self.assertIn("Ladder stand-in", B.ladder_text(combo))
        self.assertIn("nothing", B.ladder_text([]))

    def test_finds_combo_outside_the_likeliest_dozen(self):
        """2026-11-25: 12 likeliest legs were 1.06x shots legs; six games at
        1.1x-1.25x paid 2x and the old search said nothing did."""
        games = {f"H{i}": [dict(label=f"h{i}", price="-1600", chance=0.87, lg="nhl", id=f"h{i}")] for i in range(14)}
        games.update({f"N{i}": [dict(label=f"n{i}", price="-850", chance=0.84, lg="nba", id=f"n{i}")] for i in range(5)})
        games["ML"] = [dict(label="ml", price="-400", chance=0.77, lg="nba", id="ml")]
        combo = B.ladder_fallback({"games": games, "left_off": []})
        pays = math.prod(B._dec(L["price"]) for L in combo)
        self.assertTrue(2.0 <= pays <= 5.0, pays)
        self.assertLessEqual(len(combo), 6)
        self.assertEqual(len(combo), len({L["id"] for L in combo}))

    def test_matches_brute_force(self):
        """2026-11-25: a rounded-payout knapsack missed or under-picked 19 of 300
        random slates; the search must equal trying every combination."""
        import itertools
        import random
        rnd = random.Random(7)
        prices = ["-250", "-300", "-400", "-500", "-700", "-900", "-1100", "-1600", "+110"]
        for _ in range(60):
            g = {f"G{i}": [dict(label=f"{i}{j}", price=rnd.choice(prices), chance=round(rnd.uniform(.5, .9), 3))
                           for j in range(rnd.randint(1, 3))] for i in range(rnd.randint(1, 7))}
            best = 0.0
            for k in range(1, 7):
                for gs in itertools.combinations(g, k):
                    for pick in itertools.product(*[g[x] for x in gs]):
                        pay = math.prod(B._dec(L["price"]) for L in pick)
                        if 2 - 1e-12 <= pay <= 5 + 1e-12:
                            best = max(best, math.prod(L["chance"] for L in pick))
            got = B.ladder_fallback({"games": g})
            self.assertAlmostEqual(math.prod(L["chance"] for L in got) if got else 0.0, best, places=9)

    def test_one_leg_per_game_and_best_chance(self):
        g = {"A": [dict(label="a1", price="-400", chance=0.80), dict(label="a2", price="-300", chance=0.70)],
             "B": [dict(label="b1", price="-400", chance=0.80)], "C": [dict(label="c1", price="-400", chance=0.80)],
             "D": [dict(label="d1", price="-400", chance=0.80)]}
        combo = B.ladder_fallback({"games": g})
        # a2 + b1 + c1 pays 2.60x at 44.8%, beating four -400s (2.44x at 41.0%)
        self.assertEqual(sorted(L["label"] for L in combo), ["a2", "b1", "c1"])
        self.assertEqual(B.ladder_fallback({"games": {"A": g["A"]}}), [])     # one game cannot reach 2x


class SaveThenGradeTest(unittest.TestCase):
    def test_saved_ticket_grades(self):
        import grade_picks as G
        rows = [dict(lg="nhl", game="VGK @ EDM", id="5", home="EDM", away="VGK", home_ml=-500, away_ml=380,
                     market_home=0.82, blind_home=0.7)]
        pg = [{"id": "nhl:5", "match": "VGK @ EDM", "props": [
            dict(name="Matt Boldy", label="Matt Boldy: 2+ Shots on Goal", p=0.87, imp=0.9, price="-900",
                 market="Shots on Goal", line="2+")]}]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda r: pg, status_fn=lambda n: None,
                       goalie_fn=lambda team: "", nhl_b2b_fn=lambda *a: False)
        legs = B.ticket_legs(t)
        self.assertEqual([L["kind"] for L in legs], ["ml", "prop"])
        self.assertTrue(all("chance" not in L and "gid" not in L for L in legs))
        box = {"header": {"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
                   {"team": {"abbreviation": "EDM"}, "score": "4"}, {"team": {"abbreviation": "VGK"}, "score": "2"}]}]},
               "boxscore": {"players": [{"team": {"abbreviation": "EDM"}, "statistics": [
                   {"name": "forwards", "keys": ["shotsTotal"], "labels": ["S"],
                    "athletes": [{"athlete": {"id": "9", "displayName": "Matt Boldy"}, "stats": ["3"]}]}]}]}}
        got = [G.grade(L, {"EDM": 4.0, "VGK": 2.0}, True, box) for L in legs]
        self.assertEqual(got, ["won", "won"])


if __name__ == "__main__":
    unittest.main()
