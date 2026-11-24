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
        self.assertEqual(R.price_check(legs, cur), [("Trae", "FanDuel now -1250 (was -1500)"),
                                                    ("Gone", "this line is no longer posted at FanDuel")])


class MlCheckTest(unittest.TestCase):
    def test_moneyline_move(self):
        legs = [dict(kind="ml", id="8", team="BOS", price="-453", label="BOS ML"),
                dict(kind="ml", id="9", team="DEN", price="-324", label="DEN ML")]
        rows = [dict(id="8", home="WSH", away="BOS", home_ml=400, away_ml=-550, market_home=0.17),
                dict(id="9", home="DEN", away="DAL", home_ml=-324, away_ml=260, market_home=0.73)]
        self.assertEqual(R.ml_check(legs, rows), [("BOS ML", "DraftKings now -550 (was -453), 83% no-vig")])


class FinalViewTest(unittest.TestCase):
    def test_keep_caution_drop(self):
        legs = [dict(id="1", label="A"), dict(id="1", label="B"), dict(id="2", label="C"), dict(id="2", label="D")]
        flags = [("A", "A Guy is now Out on the official report"), ("B", "FanDuel now -900 (was -1100)"),
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
