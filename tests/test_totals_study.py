import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import totals_study as t                                          # noqa: E402


def g(day, hs, as_, total, oo=-110, uo=-110):
    return dict(day=day, home=dict(score=hs), away=dict(score=as_), odds=dict(total=total, over=oo, under=uo))


class Totals(unittest.TestCase):
    def test_rows_and_summary(self):
        G = {"1": g("2024-10-01", 30, 20, 45.5),     # 50 > 45.5: over
             "2": g("2024-10-02", 20, 20, 45.5),     # 40: under
             "3": g("2024-10-03", 20, 25, 45.0),     # push: dropped
             "4": g("2025-01-05", 10, 10, 41.5),     # January -> 2024 season, under
             "5": dict(day="2024-10-04", home=dict(score=1), away=dict(score=1), odds={})}
        R = t.rows(G)
        self.assertEqual(sorted((r["season"], r["over"]) for r in R), [("2024", False), ("2024", False), ("2024", True)])
        line = t.summary(R)[0]
        self.assertIn("2024 n3 over 33.3% vs 50.0% priced", line)
        self.assertIn("over -36.4%", line)              # +0.909 -1 -1 over 3
        self.assertIn("under +27.3%", line)             # -1 +0.909 +0.909 over 3


if __name__ == "__main__":
    unittest.main()
