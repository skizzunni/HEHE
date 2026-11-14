import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ladder_ticket as t                                         # noqa: E402


class Ticket(unittest.TestCase):
    def test_needs(self):
        self.assertEqual(t.needs("Franz Wagner: 6+ Assists"), "Franz Wagner: 6 or more assists")
        self.assertEqual(t.needs("Under 241.5 points"), "Both teams together: 241 or fewer points")
        self.assertEqual(t.needs("Over 5.5 goals"), "Both teams together: 6 or more goals")
        self.assertEqual(t.needs("Utah Mammoth under 3.5 goals"), "Utah Mammoth must score 3 or fewer goals")
        self.assertEqual(t.needs("NC State Wolfpack +15.5"), "NC State Wolfpack must win, or lose by 15 or fewer")
        self.assertEqual(t.needs("James Madison -3.5"), "James Madison must win by 4 or more")
        self.assertEqual(t.needs("Houston Cougars to win"), "Houston Cougars must win outright")
        self.assertEqual(t.needs("France or draw"), "France must win or draw")
        self.assertEqual(t.needs("Arsenal to win", "epl"), "Arsenal must win outright (a draw loses)")
        self.assertEqual(t.needs("Houston Cougars to win", "ncaaf"), "Houston Cougars must win outright")

    def test_lines(self):
        R = dict(runs=6, wins_needed=11, chance_to_target=1 / 7007,
                 today=dict(stake=4.95, pays=2.0, prob=0.4471, vs_top4=dict(prob=0.3558, pays=2.48),
                            no_props=dict(n=3, pays=2.005, prob=0.4421, labels=["A to win", "B to win"]),
                            legs=[dict(label="Franz Wagner: 6+ Assists", price="-400", p=0.7797, match="MIL @ ORL",
                                       lg="NBA", tip="7:00 PM", kind="prop", league="nba", market="Assists",
                                       kind_rec=dict(won=21, n=24), prop_rec=dict(won=107, n=138, said=78),
                                       outs={"Orlando Magic": ["X"]})]))
        L = t.lines(R)
        self.assertEqual(L[0], "Run 6, stake $4.95 (the whole bank) on 1 legs at 2.00x -> $9.90; 45% est. all win.")
        self.assertIn("Needs: Franz Wagner: 6 or more assists. Locks like it: 21 of 24.", L[1])
        self.assertIn("107 of 138 (78% vs 78% stated). Out: Orlando Magic without X.", L[1])
        self.assertEqual(L[2], "Plain top 4 instead: 36% at 2.48x.")
        self.assertTrue(L[3].startswith("Without props: 3 legs at 2.00x, 44%"))
        self.assertEqual(L[4], "11 straight wins at this price reach the target, about 1 in 7,007.")

    def test_new_run_line(self):
        R = dict(runs=6, best=9.57, ended=dict(peak=4.95, lost_on=["Houston Cougars to win"]),
                 history=[dict(status="lost", days=3, peak=4.95)],
                 today=dict(stake=1.0, pays=2.1, prob=0.45, legs=[dict(label="A to win", price="-300", p=0.75, match="A @ B",
                                                                      lg="NBA", tip="7:00 PM")]))
        L = t.lines(R)
        self.assertEqual(L[0], "New run: run 7 starts at $1. Run 6 lasted 3 day(s), peak $4.95, lost on Houston Cougars to win; "
                               "best ever $9.57.")
        self.assertTrue(L[1].startswith("Run 7, stake $1.00 (the whole bank) on 1 legs at 2.10x"))

    def test_no_ticket(self):
        self.assertEqual(t.lines({}), [])
        self.assertEqual(t.lines({"today": {"legs": []}}), [])


if __name__ == "__main__":
    unittest.main()
