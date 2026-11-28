import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import spread_study as s                                          # noqa: E402


def g(day, hs, as_, spread, hp=-110, ap=-110):
    return dict(day=day, home=dict(score=hs), away=dict(score=as_),
                odds=dict(home_spread=spread, home_spread_price=hp, away_spread_price=ap))


class SpreadStudy(unittest.TestCase):
    def test_cover_push_and_season(self):
        G = {"1": g("2024-10-12", 20, 24, 7.5),      # home dog +7.5 loses by 4: dog covers
             "2": g("2024-10-12", 30, 20, -7.5),     # home fav -7.5 wins by 10: fav covers
             "3": g("2024-10-12", 20, 27, 7.0),      # home dog +7 loses by 7: push, dropped
             "4": g("2025-01-05", 10, 13, -3.0),     # bowl in January -> 2024 season; road dog +3 wins: covers
             "5": dict(day="2024-10-12", home=dict(score=1), away=dict(score=0), odds={})}
        R = s.rows(G)
        self.assertEqual(len(R), 3)
        self.assertEqual(sorted((r["pts"], r["dog_cov"], r["home_dog"], r["season"]) for r in R),
                         [(3.0, True, False, "2024"), (7.5, False, False, "2024"), (7.5, True, True, "2024")])

    def test_table(self):
        R = [dict(season="2024", pts=10, dog_cov=True, home_dog=True, dp=-110, fp=-110),
             dict(season="2024", pts=10, dog_cov=False, home_dog=True, dp=-110, fp=-110)]
        line = [x for x in s.table(R) if x.startswith("dog getting 7.5-14")][0]
        self.assertIn("2024 n2 dog covered 50.0% roi -4.5%", line)
        self.assertTrue(line.endswith(" -- one season only"))

    def test_verdict(self):
        self.assertEqual(s.verdict([0.2, 6.1]), " -- ahead in every season")
        self.assertEqual(s.verdict([0.2, -9.2]), " -- not ahead in every season")
        R = [dict(season=y, pts=2, dog_cov=c, home_dog=True, dp=-110, fp=-110)
             for y, c in (("2023", True), ("2024", True), ("2025", False))]
        line = [x for x in s.table(R) if x.startswith("dog getting 0.5-3.5")][0]
        self.assertTrue(line.endswith(" -- not ahead in every season"))


if __name__ == "__main__":
    unittest.main()
