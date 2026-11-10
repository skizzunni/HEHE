import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import band_roi_study as b                                         # noqa: E402


def game(day, hs, as_, ho, ao):
    return dict(day=day, home=dict(score=hs), away=dict(score=as_), odds=dict(home=ho, away=ao))


class BandRoi(unittest.TestCase):
    def test_rows_seasons_and_sides(self):
        G = {"1": game("2024-11-02", 100, 90, -300, 250),    # home fav won, season 2024
             "2": game("2025-02-01", 80, 95, -300, 250),     # home fav lost, still season 2024
             "3": game("2025-10-30", 99, 98, 150, -170),     # away fav lost (home dog won), season 2025
             "4": game("2024-11-03", 1, 0, -300, 120),       # overround 0.97: dropped
             "5": dict(day="2024-11-04", home=dict(score=1), away=dict(score=0), odds=None)}
        R = sorted(b.rows(G), key=lambda r: r["season"])
        self.assertEqual([r["season"] for r in R], ["2024", "2024", "2025"])
        self.assertEqual([r["fav_won"] for r in R], [True, False, False])
        self.assertTrue(R[2]["home_dog"])
        self.assertAlmostEqual(R[0]["p"], 0.75 / (0.75 + 100 / 350), places=6)

    def test_table_roi(self):
        R = [dict(season="2024", p=0.75, fav_won=True, home_dog=False, fo=-300, do=250),
             dict(season="2024", p=0.75, fav_won=False, home_dog=False, fo=-300, do=250)]
        line = [x for x in b.table(R) if x.startswith("fav 70-80%")][0]
        # fav: +1/3 then -1 -> -33.3%; dog: -1 then +2.5 -> +75.0%
        self.assertIn("2024 n2 fav -33.3% dog +75.0%", line)


if __name__ == "__main__":
    unittest.main()
