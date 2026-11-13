import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import move_study as m                                            # noqa: E402


def p(day, st, first, close, conf=60, lg="nhl"):
    return dict(date=day, status=st, first_price=first, price=close, conf=conf, league=lg)


class Moves(unittest.TestCase):
    def test_move_sign(self):
        self.assertAlmostEqual(m.move(p("d", "won", "-150", "-120")), 100 * (120 / 220 - 0.6), places=6)
        self.assertIsNone(m.move(p("d", "won", None, "-120")))

    def test_halves(self):
        L = {"1": p("2026-10-01", "lost", "-150", "-110"),   # -7.6 pts: against
             "2": p("2026-10-01", "won", "-150", "-150"),
             "3": p("2026-10-02", "won", "-150", "-200"),    # moved for
             "4": p("2026-10-02", "won", "+100", "+100", lg="nba")}
        r = m.study(L, "nhl", cuts=(3,))
        self.assertEqual(r["mid"], "2026-10-02")
        self.assertEqual(r["3A"]["against"][:2], [0, 1])
        self.assertEqual(r["3A"]["rest"][:2], [1, 1])
        self.assertEqual(r["3B"]["rest"][:2], [1, 1])
        self.assertIsNone(r["3B"]["against"])
        self.assertAlmostEqual(r["3B"]["rest"][3], 50.0)    # -200 pays 0.5
        self.assertEqual(m.study(L, "all", cuts=(3,))["n"], 4)

    def test_empty(self):
        self.assertIsNone(m.study({}))


if __name__ == "__main__":
    unittest.main()
