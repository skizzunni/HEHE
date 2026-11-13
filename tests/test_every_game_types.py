import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import daily_review as dr                                         # noqa: E402


def g(day, label, won, p=0.9):
    return dict(date=day, label=label, p=p, status="won" if won else "lost", kind="game")


class EveryGameTypes(unittest.TestCase):
    def test_line(self):
        R = []
        for day in ("2026-11-01", "2026-11-10"):
            R += [g(day, "Over 210.5 points", True) for _ in range(10)]                          # 100% vs 90%: ahead
            R += [g(day, "Lakers to win", i < 7) for i in range(10)]                             # 70% vs 90%: short
        out = dr.every_game_type_line(R)
        self.assertIn("win 70% then 70% (vs 90%, 90%)", out)
        self.assertIn("total 100% then 100%", out)
        self.assertIn("Short in both halves: win.", out)
        self.assertTrue(out.endswith("Ahead in both halves: total."))

    def test_too_few(self):
        self.assertIsNone(dr.every_game_type_line([g("2026-11-01", "Over 1.5 goals", True)] * 5))


if __name__ == "__main__":
    unittest.main()
