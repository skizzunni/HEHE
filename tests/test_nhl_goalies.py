import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import nhl_goalies as G  # noqa: E402

DATA = {"props": {"pageProps": {"data": [
    {"awayTeamName": "Calgary Flames", "homeTeamName": "Ottawa Senators", "awayGoalieName": "Devin Cooley",
     "homeGoalieName": "Linus Ullmark", "awayNewsStrengthName": "Confirmed", "homeNewsStrengthName": "Likely",
     "awayNewsCreatedAt": "2026-11-23T16:33:11.149Z", "homeNewsCreatedAt": None},
    {"awayTeamName": "Minnesota Wild", "homeTeamName": "San Jose Sharks", "awayGoalieName": "Jesper Wallstedt",
     "homeGoalieName": "Yaroslav Askarov"}]}}}
HTML = '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(DATA) + "</script></html>"


class ParseTest(unittest.TestCase):
    def test_rows(self):
        r = G.parse(HTML)
        self.assertEqual(len(r), 2)
        self.assertEqual((r[0]["away_goalie"], r[0]["away_status"], r[0]["away_at"]), ("Devin Cooley", "Confirmed", "11:33 AM"))
        self.assertEqual((r[0]["home_status"], r[0]["home_at"]), ("Likely", None))
        self.assertEqual((r[1]["away_status"], r[1]["home_status"]), ("Unconfirmed", "Unconfirmed"))
        t = G.text(r)
        self.assertIn("Calgary Flames @ Ottawa Senators: Devin Cooley (Confirmed, 11:33 AM ET) vs Linus Ullmark (Likely)", t)

    def test_no_data(self):
        self.assertEqual(G.parse("<html></html>"), [])
        self.assertIn("No goalie data", G.text([]))


class FlagTest(unittest.TestCase):
    R = [("Jesper Wallstedt", 22, 0.924), ("Calvin Pickard", 3, 0.855)]

    def test_flags(self):
        self.assertEqual(G.flag("Jesper Wallstedt", self.R), "")
        self.assertIn("not the usual starter (3 starts, .855; Jesper Wallstedt has 22)", G.flag("Calvin Pickard", self.R))
        self.assertIn("NOT among this team's goalies", G.flag("Filip Gustavsson", self.R))
        self.assertEqual(G.flag("Anyone", []), "")

    def test_text_uses_rosters(self):
        rows = [dict(away="Minnesota Wild", home="San Jose Sharks", away_goalie="Filip Gustavsson", away_status="Confirmed",
                     away_at=None, home_goalie="Yaroslav Askarov", home_status="Confirmed", home_at=None)]
        t = G.text(rows, {"Minnesota Wild": self.R})
        self.assertIn("Filip Gustavsson (Confirmed) -- NOT among", t)

    def test_team_goalies_from_api(self):
        pages = {"standings/now": {"standings": [{"teamName": {"default": "Minnesota Wild"}, "teamAbbrev": {"default": "MIN"}}]},
                 "club-stats/MIN/now": {"goalies": [{"firstName": {"default": "Jesper"}, "lastName": {"default": "Wallstedt"},
                                                     "gamesStarted": 22, "savePercentage": 0.924}]}}
        self.assertEqual(G.team_goalies(get=pages.get), {"Minnesota Wild": [("Jesper Wallstedt", 22, 0.924)]})


if __name__ == "__main__":
    unittest.main()
