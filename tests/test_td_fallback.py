import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import td_fallback as T  # noqa: E402


class LegsTest(unittest.TestCase):
    def test_top_two_per_game_in_grader_format(self):
        import grade_picks as G
        g = [dict(id="nfl:9", players=[dict(name="A B", p=0.6, price="-150"), dict(name="C D", p=0.5, price="+100"),
                                       dict(name="E F", p=0.4, price="+150")])]
        L = T.legs(g)
        self.assertEqual([x["player"] for x in L], ["A B", "C D"])
        box = {"header": {"competitions": [{"status": {"type": {"completed": True}}}]},
               "boxscore": {"players": [{"team": {"abbreviation": "X"}, "statistics": [
                   {"name": "rushing", "keys": ["rushingTouchdowns"], "labels": ["TD"],
                    "athletes": [{"athlete": {"id": "1", "displayName": "A B"}, "stats": ["1"]}]}]}]}}
        self.assertIn(G.board_prop(L[0], box), ("won", None))


class RowsTest(unittest.TestCase):
    def test_rows_from_scoreboard_and_summary(self):
        sb = {"events": [{"id": "9", "shortName": "CHI @ DET", "date": "2026-11-26T17:30Z", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": "Detroit Lions"}},
            {"homeAway": "away", "team": {"displayName": "Chicago Bears"}}]}]}]}
        sm = {"pickcenter": [{"overUnder": 55.5}]}
        got = T.rows("2026-11-26", get=lambda u: sb if "scoreboard" in u else sm)
        self.assertEqual(got, [dict(id="nfl:9", label="CHI @ DET", tip="2026-11-26T17:30Z",
                                    mkt=dict(away="Chicago Bears", home="Detroit Lions", total=55.5))])

    def test_text(self):
        g = [dict(match="CHI @ DET", total=55.5, basis="scaled", players=[
            dict(name="Jahmyr Gibbs", p=0.61, price="-290", p2=0.24, pfirst=0.16)])]
        self.assertEqual(T.text(g).splitlines()[1:], ["CHI @ DET (total 55.5; scaled)",
                                                     "  Jahmyr Gibbs: anytime 61% (-290), 2+ 24%, first TD 16%"])
        self.assertEqual(T.text(g).splitlines()[0], T.NOTE)
        g[0]["players"][0]["imp"] = 0.744
        self.assertIn("(-290, FanDuel 74%)", T.text(g))
        self.assertEqual(T.text([]), "No NFL anytime-TD market posted yet.")


if __name__ == "__main__":
    unittest.main()
