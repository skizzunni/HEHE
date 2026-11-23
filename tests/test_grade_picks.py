import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import grade_picks as G  # noqa: E402


class GradeTest(unittest.TestCase):
    S = {"MEM": 110.0, "CHA": 106.0}

    def test_spread_ml_totals(self):
        self.assertEqual(G.grade(dict(kind="spread", team="MEM", line=-2.5), self.S, True), "won")
        self.assertEqual(G.grade(dict(kind="spread", team="MEM", line=-4.0), self.S, True), "push")
        self.assertEqual(G.grade(dict(kind="spread", team="CHA", line=3.5), self.S, True), "lost")
        self.assertEqual(G.grade(dict(kind="ml", team="CHA"), self.S, True), "lost")
        self.assertEqual(G.grade(dict(kind="under", line=222.5), self.S, True), "won")
        self.assertEqual(G.grade(dict(kind="over", line=216.0), self.S, True), "push")
        self.assertEqual(G.grade(dict(kind="ml", team="MEM"), self.S, False), "open")

    def test_summary_units(self):
        picks = [dict(price=-116), dict(price=124), dict(price=-105), dict(price=-110)]
        s = G.summary(picks, ["won", "won", "lost", "open"])
        self.assertEqual((s["won"], s["lost"], s["open"]), (2, 1, 1))
        self.assertAlmostEqual(s["units"], round(100 / 116 + 1.24 - 1, 2))

    def test_final_from_espn_shape(self):
        page = {"header": {"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
            {"team": {"abbreviation": "NJ"}, "score": "4"}, {"team": {"abbreviation": "CBJ"}, "score": "2"}]}]}}
        scores, done = G.final("nhl", "1", get=lambda u: page)
        self.assertEqual((scores, done), ({"NJ": 4.0, "CBJ": 2.0}, True))


if __name__ == "__main__":
    unittest.main()
