import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import cfb_study as C  # noqa: E402


class CfbStudyTest(unittest.TestCase):
    def test_both_layouts_and_checks(self):
        lab = [dict(season=2024, day="2024-11-30", home=dict(score=20), away=dict(score=17),
                    odds=dict(h_ml=-300, a_ml=250, h_sp=-7, total=40.5, under=-110))]
        hist = {"1": dict(day="2025-11-29", home=dict(score=30), away=dict(score=24),
                          odds=dict(home=-200, away=170, home_spread=-4.5, total=44.5, under=-110)),
                "2": dict(day="2025-10-04", home=dict(score=10), away=dict(score=14),
                          odds=dict(home=-150, away=130, home_spread=-3, total=60, under=-110)),
                "3": dict(day="2025-10-04", home=dict(score=None), away=dict(score=None), odds={})}
        rows = C.games(lab) + C.games(hist)
        self.assertEqual(len(rows), 3)                          # no-score game left out
        lt = C.low_total_unders(rows)
        self.assertEqual(lt["2024"][:2], (1, 100.0))           # 37 < 40.5
        self.assertEqual(lt["2025"][:2], (1, 0.0))             # 54 > 44.5
        riv = C.favourites(rows, lambda r: C.rivalry(r["day"]))
        self.assertEqual(riv["2025"][:2], (1, 1))               # home fav won on Nov 29
        other = C.favourites(rows, lambda r: not C.rivalry(r["day"]))
        self.assertEqual(other["2025"][:2], (1, 0))             # home fav lost on Oct 4
        self.assertEqual(C.season_of("2026-01-05"), "2025")

    def test_merge_dedupes_by_id(self):
        g = dict(id="9", day="2025-11-29", home=dict(score=30), away=dict(score=24),
                 odds=dict(home=-200, away=170, total=44.5, under=-110))
        self.assertEqual(len(C.merge([{"9": g}, [dict(g)]])), 1)


if __name__ == "__main__":
    unittest.main()
