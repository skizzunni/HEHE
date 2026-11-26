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


class SafestBand(unittest.TestCase):
    def test_in_safest_follows_build_ticket(self):
        self.assertTrue(G.in_safest({"kind": "prop", "lg": "nba", "price": "-3000"}))
        self.assertFalse(G.in_safest({"kind": "prop", "lg": "nba", "price": "-1500"}))
        self.assertTrue(G.in_safest({"kind": "prop", "lg": "nhl", "price": "-1500"}))
        self.assertTrue(G.in_safest({"kind": "prop", "lg": "nfl", "price": "-1000"}))
        self.assertFalse(G.in_safest({"kind": "ml", "price": "-424", "chance": 0.78}))

    def test_split_line(self):
        from unittest.mock import patch
        picks = [{"kind": "prop", "lg": "nba", "price": "-3000"}, {"kind": "prop", "lg": "nba", "price": "-1100"},
                 {"kind": "prop", "lg": "nba", "price": "-1100"}]
        with patch.object(G, "main", lambda path, get=None: (picks, ["won", "lost", "won"], {})):
            self.assertEqual(G.band_split("x"), "  safest bands 1/1 (100%), the rest 1/2 (50%)")


class SafeDrops(unittest.TestCase):
    def test_safe_2x_honours_the_safe_tickets_drops(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        legs = [{"label": "a"}, {"label": "b"}]
        json.dump(legs, open(os.path.join(d, "ticket_safe_2x.json"), "w"))
        json.dump(["a"], open(os.path.join(d, "ticket_safe.json.dropped"), "w"))
        self.assertEqual([L["label"] for L in G.load(os.path.join(d, "ticket_safe_2x.json"))], ["b"])


class BriefInProgress(unittest.TestCase):
    def test_no_stat_yet_in_a_live_game_is_not_not_started(self):
        """2026-11-26: LaPorta at 8:31 of the 1st, no catch yet, read 'not started'."""
        import json
        import tempfile
        from unittest import mock
        path = os.path.join(tempfile.mkdtemp(), "t.json")
        legs = [dict(label="a", id="1", lg="nfl", kind="prop", player="A", stat="YDS", line=15),
                dict(label="b", id="2", lg="nfl", kind="prop", player="B", stat="YDS", line=15)]
        json.dump(legs, open(path, "w"))
        rows = ["OPEN  a -- 8:31 - 1st: not in the box score yet",
                "OPEN  b -- 11/26 - 4:30 PM EST: not in the box score yet"]
        with mock.patch.object(G, "live", lambda p, get=None: rows):
            out = G.brief(path, get=lambda u: {})
        self.assertIn("OPEN  A 15+ YDS -- 8:31 - 1st: none yet", out)
        self.assertEqual(out[-1], "(1 not started yet)")


if __name__ == "__main__":
    unittest.main()
