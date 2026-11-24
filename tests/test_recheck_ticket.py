import os
import sys
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


class PriceCheckTest(unittest.TestCase):
    def test_moved_and_gone(self):
        legs = [dict(kind="prop", player="Trae Young", market="Pts + Ast", line_text="15+", price="-1500", label="Trae"),
                dict(kind="prop", player="Paul Reed", market="Rebounds", line_text="4+", price="-1200", label="Reed"),
                dict(kind="prop", player="Gone Guy", market="Points", line_text="5+", price="-900", label="Gone"),
                dict(kind="ml", team="BOS", price="-453", label="BOS")]
        cur = {("Trae Young", "Pts + Ast", "15+"): "-1250", ("Paul Reed", "Rebounds", "4+"): "-1200"}
        self.assertEqual(R.price_check(legs, cur), [("Trae", "FanDuel now -1250 (was -1500), the market rates it less likely (93.8% -> 92.6%)"),
                                                    ("Gone", "this line is no longer posted at FanDuel")])


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


if __name__ == "__main__":
    unittest.main()
