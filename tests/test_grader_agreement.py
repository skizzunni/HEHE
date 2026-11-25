import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import grader_agreement as A  # noqa: E402

BOX = {"header": {"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
    {"team": {"abbreviation": "GB"}, "score": "20"}, {"team": {"abbreviation": "LAR"}, "score": "17"}]}]},
       "boxscore": {"players": [{"team": {"abbreviation": "GB"}, "statistics": [
           {"name": "receiving", "keys": ["receivingYards"], "labels": ["YDS"], "athletes": [
               {"athlete": {"id": "9", "displayName": "Tucker Kraft"}, "stats": ["44"]}]}]}]}}


class AgreementTest(unittest.TestCase):
    def test_sample_takes_latest_graded_in_league_and_market(self):
        props = {"a": dict(league="nfl", status="won", gid="nfl:1", market="Receiving Yards", date="2026-11-01"),
                 "b": dict(league="nfl", status="open", gid="nfl:2", market="Receiving Yards", date="2026-11-02"),
                 "c": dict(league="nba", status="won", gid="nba:3", market="Points", date="2026-11-03"),
                 "d": dict(league="nfl", status="lost", gid="nfl:4", market="Passing Yards", date="2026-11-04")}
        self.assertEqual([r["gid"] for r in A.sample(props, "nfl", 5)], ["nfl:1", "nfl:4"])
        self.assertEqual([r["gid"] for r in A.sample(props, "nfl", 5, "Passing Yards")], ["nfl:4"])

    def test_counts_agreement_and_names_differences(self):
        rows = [dict(gid="nfl:1", name="Tucker Kraft", market="Receiving Yards", line="15+", status="won"),
                dict(gid="nfl:1", name="Tucker Kraft", market="Receiving Yards", line="50+", status="won")]
        ok, bad = A.agreement(rows, get=lambda u: BOX)
        self.assertEqual(ok, 1)
        self.assertEqual(bad, [("Tucker Kraft", "Receiving Yards", "50+", "won", "lost")])


if __name__ == "__main__":
    unittest.main()
