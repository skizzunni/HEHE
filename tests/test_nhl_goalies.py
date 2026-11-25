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


class CareerTest(unittest.TestCase):
    def test_lookup_picks_the_goalie(self):
        pages = {G.SEARCH.format("Filip%20Gustavsson"): [
                     {"playerId": "1", "name": "Filip Chytil", "positionCode": "C"},
                     {"playerId": "8479406", "name": "Filip Gustavsson", "positionCode": "G"}],
                 G.NHL.format("player/8479406/landing"): {"careerTotals": {"regularSeason": {"gamesPlayed": 220, "savePctg": 0.91}}}}
        self.assertEqual(G.career("Filip Gustavsson", get=pages.get), (220, 0.91))
        self.assertIsNone(G.career("Nobody Here", get=lambda u: []))


class FlagTest(unittest.TestCase):
    def test_accents_do_not_make_a_stranger(self):
        roster = [("Leevi Meriläinen", 16, 0.905), ("Kevin Lankinen", 4, 0.890)]
        self.assertEqual(G.flag("Leevi Merilainen", roster, career_fn=lambda g: None), "")
        self.assertIn("not the usual starter", G.flag("Kevin Lankinen", roster, career_fn=lambda g: None))

    R = [("Jesper Wallstedt", 22, 0.924), ("Calvin Pickard", 3, 0.855)]

    def test_flags(self):
        self.assertEqual(G.flag("Jesper Wallstedt", self.R), "")
        self.assertIn("not the usual starter (3 starts, .855; Jesper Wallstedt has 22)", G.flag("Calvin Pickard", self.R))
        self.assertIn("NOT among this team's goalies", G.flag("Call Up", self.R, career_fn=lambda n: (4, 0.88)))
        self.assertIn("no NHL career found", G.flag("Nobody", self.R, career_fn=lambda n: None))
        est = G.flag("Filip Gustavsson", self.R, career_fn=lambda n: (220, 0.9108))
        self.assertIn("established NHL goalie (220 career games, .911)", est)
        self.assertNotIn("verify", est)
        self.assertEqual(G.flag("Anyone", []), "")

    def test_text_uses_rosters(self):
        rows = [dict(away="Minnesota Wild", home="San Jose Sharks", away_goalie="Filip Gustavsson", away_status="Confirmed",
                     away_at=None, home_goalie="Yaroslav Askarov", home_status="Confirmed", home_at=None)]
        t = G.text(rows, {"Minnesota Wild": self.R}, career_fn=lambda n: (220, 0.911))
        self.assertIn("Filip Gustavsson (Confirmed) -- first game for this team this season", t)

    def test_team_goalies_from_api(self):
        pages = {"standings/now": {"standings": [{"teamName": {"default": "Minnesota Wild"}, "teamAbbrev": {"default": "MIN"}}]},
                 "club-stats/MIN/now": {"goalies": [{"firstName": {"default": "Jesper"}, "lastName": {"default": "Wallstedt"},
                                                     "gamesStarted": 22, "savePercentage": 0.924}]}}
        self.assertEqual(G.team_goalies(get=pages.get), {"Minnesota Wild": [("Jesper Wallstedt", 22, 0.924)]})


if __name__ == "__main__":
    unittest.main()
