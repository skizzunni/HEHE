"""Item 10: tickets only from the day's calls, strongest first, at most 3
legs, no two legs from one game or sharing a driver, the joint chance with a
penalty, the fair payout beside the actual one."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import call_tickets as T                                  # noqa: E402


def call(i, conf, price="-200", match=None, pick=None, **kw):
    c = dict(id=f"nhl:{i}", league="nhl", pick=pick or f"Team {i}", match=match or f"Opp {i} @ Team {i}",
             conf=conf, price=price, rank=i)
    c.update(kw)
    return c


class Tickets(unittest.TestCase):
    def test_strongest_first_max_three(self):
        cs = [call(1, 60), call(2, 80), call(3, 75), call(4, 70), call(5, 65)]
        ts = T.build(cs)
        self.assertEqual([len(t["legs"]) for t in ts], [2, 3])                  # never 4+
        self.assertEqual([L["id"] for L in ts[1]["legs"]], ["nhl:2", "nhl:3", "nhl:4"])

    def test_joint_with_penalty_and_payouts(self):
        t = T.build([call(1, 80, "-400"), call(2, 70, "-233")])[0]
        self.assertAlmostEqual(t["joint"], round(0.8 * 0.7 * T.PENALTY, 4))
        self.assertLess(t["joint"], t["independent"])
        self.assertAlmostEqual(t["fair_payout"], round(1 / t["joint"], 2))
        self.assertAlmostEqual(t["actual_payout"], round(1.25 * (1 + 100 / 233), 2))

    def test_no_shared_game_or_driver(self):
        cs = [call(1, 80, match="Boston Bruins @ Toronto Maple Leafs", pick="Toronto Maple Leafs"),
              call(2, 79, match="Boston Bruins @ Toronto Maple Leafs", pick="Boston Bruins", id="nhl:1"),  # same game
              call(3, 78, match="Toronto Maple Leafs @ Ottawa Senators", pick="Ottawa Senators"),          # shares a team
              call(4, 60)]
        t = T.build(cs)[0]
        self.assertEqual([L["pick"] for L in t["legs"]], ["Toronto Maple Leafs", "Team 4"])

    def test_pulled_started_and_unpriced_never_ride(self):
        cs = [call(1, 90, status="pulled"), call(2, 85, price=None), call(3, 80), call(4, 70), call(5, 60)]
        t = T.build(cs, started=lambda c: c["id"] == "nhl:3")[0]
        self.assertEqual([L["id"] for L in t["legs"]], ["nhl:4", "nhl:5"])

    def test_not_enough_calls(self):
        self.assertEqual(T.build([call(1, 80)]), [])
        self.assertEqual(len(T.build([call(1, 80), call(2, 70)])), 1)          # 2 calls: one 2-leg ticket

    def test_penalty_never_raises_the_chance(self):
        self.assertLessEqual(T.PENALTY, 1.0)
        t = T.build([call(1, 90), call(2, 90), call(3, 90)])[1]
        self.assertLess(t["joint"], math.prod([0.9] * 3))


if __name__ == "__main__":
    unittest.main()
