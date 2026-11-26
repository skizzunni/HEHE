import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import grade_picks as G  # noqa: E402

LABELS = ["BS", "HT", "TK", "+/-", "TOI", "PPTOI", "S", "SM", "SOG"]
SUM = {"boxscore": {"players": [{"statistics": [{"labels": LABELS, "athletes": [
    {"athlete": {"displayName": "Alexis Lafrenière"},
     "stats": ["0", "3", "0", "0", "19:43", "3:27", "0", "0", "0"]}]}]}]}}


class IceTime(unittest.TestCase):
    def test_nhl_loss_shows_ice_time(self):
        """2026-11-25: Lafreniere lost 1+ shots with 0 in 19:43 -- a full night."""
        pick = {"kind": "prop", "lg": "nhl", "player": "Alexis Lafreniere", "stat": "S"}
        self.assertEqual(G.detail(pick, {}, SUM), " -- had 0 in 19:43 of ice time")

    def test_no_toi_column(self):
        self.assertIsNone(G._toi({"boxscore": {"players": []}}, "Anyone"))

    def test_nba_still_minutes(self):
        s = {"boxscore": {"players": [{"statistics": [{"labels": ["MIN", "AST"], "athletes": [
            {"athlete": {"displayName": "Jaylen Brown"}, "stats": ["17", "1"]}]}]}]}}
        pick = {"kind": "prop", "lg": "nba", "player": "Jaylen Brown", "stat": "AST"}
        self.assertEqual(G.detail(pick, {}, s), " -- had 1 in 17 min")


FIN = {"completed": True, "boxscore": {"players": [{"statistics": [{"labels": ["REC", "YDS"], "athletes": [
    {"athlete": {"displayName": "Tucker Kraft"}, "stats": ["3", "24"]}]}]}]}}


class DidNotPlay(unittest.TestCase):
    def test_absent_from_final_box_says_void(self):
        """2026-11-25: 'PUSH CJ Daniels' said nothing -- a game-day inactive."""
        pick = {"kind": "prop", "lg": "nfl", "player": "CJ Daniels", "stat": "YDS"}
        self.assertIn("did not play", G.detail(pick, {}, FIN))

    def test_not_said_before_the_final(self):
        live = dict(FIN, completed=False)
        pick = {"kind": "prop", "lg": "nfl", "player": "CJ Daniels", "stat": "YDS"}
        self.assertEqual(G.detail(pick, {}, live), "")

    def test_player_who_played_unchanged(self):
        pick = {"kind": "prop", "lg": "nfl", "player": "Tucker Kraft", "stat": "YDS"}
        self.assertEqual(G.detail(pick, {}, FIN), " -- had 24")


if __name__ == "__main__":
    unittest.main()
