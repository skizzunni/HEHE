import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import prereg_nhl_dog as P  # noqa: E402

G = dict(home_id="1", away_id="2", hs=3, as_=2)


def sides(home_ml, away_ml, home_pl, away_pl, home_pr, away_pr):
    return {"1": (home_ml, home_pl, home_pr), "2": (away_ml, away_pl, away_pr)}


class BetTest(unittest.TestCase):
    def test_big_favourite_gives_a_dog_bet(self):
        b = P.bet(G, sides(-220, 180, -1.5, 1.5, 140, -165))
        self.assertIsNotNone(b)
        self.assertEqual(b["price"], -165)
        self.assertTrue(b["won"])                  # home won by 1: dog +1.5 covers
        self.assertAlmostEqual(b["p"], P.imp(-165) / (P.imp(-165) + P.imp(140)))

    def test_dog_loses_by_two(self):
        b = P.bet(dict(G, hs=4, as_=2), sides(-220, 180, -1.5, 1.5, 140, -165))
        self.assertFalse(b["won"])

    def test_not_big_enough_favourite(self):
        self.assertIsNone(P.bet(G, sides(-180, 150, -1.5, 1.5, 160, -190)))

    def test_swapped_puck_line_skipped(self):
        self.assertIsNone(P.bet(G, sides(-220, 180, 1.5, -1.5, -165, 140)))

    def test_away_favourite(self):
        b = P.bet(dict(G, hs=1, as_=4), sides(200, -240, 1.5, -1.5, -150, 125))
        self.assertFalse(b["won"])                 # away fav won by 3


class StatusTest(unittest.TestCase):
    def test_waiting_then_verdict(self):
        self.assertEqual(P.status([])["verdict"], "waiting")
        few = [dict(p=0.6, price=-150, won=True)] * 10
        self.assertEqual(P.status(few)["verdict"], "waiting")
        lots = [dict(p=0.6, price=-150, won=i % 10 < 8) for i in range(150)]
        s = P.status(lots)
        self.assertEqual(s["verdict"], "supports")
        self.assertGreater(s["roi"], 0)
        flat = [dict(p=0.6, price=-150, won=i % 10 < 6) for i in range(150)]
        self.assertEqual(P.status(flat)["verdict"], "dropped")


if __name__ == "__main__":
    unittest.main()
