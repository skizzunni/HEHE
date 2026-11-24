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


if __name__ == "__main__":
    unittest.main()
