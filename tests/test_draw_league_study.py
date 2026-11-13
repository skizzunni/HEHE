import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import draw_league_study as d                                     # noqa: E402


def p(day, lg, st, sc, dc=False, conf=70, price="-200"):
    return dict(date=day, league=lg, status=st, scores=dict(zip("ab", sc)), dc=dc, conf=conf, price=price)


class DrawLeague(unittest.TestCase):
    def test_walk_forward(self):
        L = {}
        # first half: league x draws 2 of 2 (high), y none
        L["1"] = p("2026-10-01", "x", "lost", (1, 1), dc=True)
        L["2"] = p("2026-10-01", "x", "lost", (0, 0))
        L["3"] = p("2026-10-02", "y", "won", (2, 0))
        # second half
        L["4"] = p("2026-10-03", "x", "won", (2, 1))
        L["5"] = p("2026-10-03", "y", "lost", (1, 1))
        L["6"] = p("2026-10-04", "y", "won", (3, 0), dc=True)   # or-draw: not scored
        r = d.study(L, cut=0.5, min_n=2)
        self.assertEqual(r["mid"], "2026-10-03")
        self.assertEqual(r["B"]["leagues"], ["x"])
        self.assertEqual(r["B"]["high"][:2], [1, 1])
        self.assertEqual(r["B"]["other"][:2], [0, 1])
        self.assertAlmostEqual(r["B"]["high"][3], 50.0)          # -200 win pays 0.5
        self.assertEqual(r["B"]["other"][4], 1)                  # the draw

    def test_empty(self):
        self.assertIsNone(d.study({}))


if __name__ == "__main__":
    unittest.main()
