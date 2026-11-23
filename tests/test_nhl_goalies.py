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


if __name__ == "__main__":
    unittest.main()
