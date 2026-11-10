import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import nfl_rest_study as n                                         # noqa: E402


def g(i, date, h, a, hs, as_, oh=-150, oa=130):
    return dict(id=i, date=date + "T18:00Z", day=date, home=dict(id=h, score=hs), away=dict(id=a, score=as_),
                odds=dict(home=oh, away=oa))


class NflRest(unittest.TestCase):
    def test_rest_days_and_spots(self):
        G = {"1": g("1", "2024-09-08", "A", "B", 20, 10),
             "2": g("2", "2024-09-08", "C", "D", 20, 10),
             "3": g("3", "2024-09-22", "A", "C", 24, 17),   # A off 14 days (bye), C off 14 too: no spot
             "4": g("4", "2024-09-26", "B", "D", 13, 16),   # B 18 days, D 18 days: no spot
             "5": g("5", "2024-09-29", "C", "A", 10, 20)}   # C 7 days, A 7 days
        R = n.rows(G)
        self.assertEqual([(r["rh"], r["ra"]) for r in R], [(14, 14), (18, 18), (7, 7)])
        self.assertIsNone(n.spot(R[0]))
        self.assertEqual(n.spot(dict(rh=14, ra=7)), ("home", "off a bye v not"))
        self.assertEqual(n.spot(dict(rh=4, ra=7)), ("away", "rested v short week"))
        self.assertIsNone(n.spot(dict(rh=4, ra=4)))

    def test_table(self):
        R = [dict(season="2024", rh=14, ra=7, p_home=0.6, home_won=True, oh=-150, oa=130),
             dict(season="2024", rh=7, ra=14, p_home=0.6, home_won=True, oh=-150, oa=130)]
        line = n.table(R)[0]
        # bye side: home won at -150 (+0.667), then away lost (-1): 50% won, -16.7%
        self.assertEqual(line, "off a bye v not: 2024 n2 won 50.0% vs 50.0% priced, -16.7%")


if __name__ == "__main__":
    unittest.main()
