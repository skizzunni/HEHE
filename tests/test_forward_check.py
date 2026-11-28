import os
import sys
import unittest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "tools"), os.path.join(os.path.dirname(__file__), "..")]
import forward_check as F  # noqa: E402


class ForwardCheckTest(unittest.TestCase):
    def test_legs_once_per_day_and_table(self):
        a = dict(kind="prop", lg="nhl", label="Steven Stamkos: 1+ Shots on Goal -1600 (87%) -- note: x", price="-1600")
        b = dict(kind="prop", lg="nhl", label="Mark Scheifele: 1+ Shots on Goal -1050 (86%)", price="-1050")
        ml = dict(kind="ml", lg="nhl", label="BOS moneyline -378", price="-378")
        graded = [("11-27", [a, b, ml], ["lost", "won", "won"]),
                  ("11-27", [dict(a, label="Steven Stamkos: 1+ Shots on Goal -1600 (87%)")], ["lost"]),  # same leg
                  ("11-26", [b], ["open"])]
        found = F.legs(graded)
        self.assertEqual(len(found), 2)                     # Stamkos once, Scheifele once; ml and open left out
        rows = {(lg, band): (w, n) for lg, band, w, n, ex, z in F.table(found)}
        self.assertEqual(rows[("nhl", "-1500 or shorter")], (0, 1))
        self.assertEqual(rows[("nhl", "longer than -1500")], (1, 1))

    def test_by_scoring(self):
        found = {("11-27", "nba", "A"): (-2500, False, "1"), ("11-27", "nba", "B"): (-2500, True, "1"),
                 ("11-27", "nba", "C"): (-2500, True, "2"), ("11-27", "nba", "D"): (-2500, True, None)}
        sc = {"1": (198, 230.5), "2": (224, 218.5)}
        rows = {(lg, side): (g, w, n) for lg, side, g, w, n, ex, z in F.by_scoring(found, lambda lg, e: sc.get(e))}
        self.assertEqual(rows[("nba", "under")], (1, 1, 2))
        self.assertEqual(rows[("nba", "over")], (1, 1, 1))

    def test_implied_and_day(self):
        self.assertAlmostEqual(F.implied("-1500"), 0.9375)
        self.assertAlmostEqual(F.implied("+150"), 0.4)
        self.assertEqual(F.day_of("work/slate_nov27"), "11-27")
        self.assertIsNone(F.day_of("work/strategy_lab"))


if __name__ == "__main__":
    unittest.main()
