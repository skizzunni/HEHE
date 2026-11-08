import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ufc_model as M                                            # noqa: E402


def fight(date, a, b, a_won, result="U-Dec"):
    return dict(date=date, a=dict(id=a, name=a, won=a_won), b=dict(id=b, name=b, won=not a_won), result=result)


class UFCModel(unittest.TestCase):
    def test_walk_forward_uses_only_earlier_fights(self):
        book = {"1": fight("2024-01-01", "x", "y", True, "KO/TKO"), "2": fight("2024-02-01", "x", "z", True),
                "3": fight("2024-03-01", "y", "z", True)}
        R, log = M.run(book)
        self.assertEqual(log[0][3], 0.5)                          # first fight: nobody rated yet
        self.assertGreater(log[1][3], 0.5)                        # x favoured after beating y
        self.assertGreater(R["x"], R["y"])
        s = M.score(log, since="2024-01-01", min_fights=0)
        self.assertEqual((s["n"], s["right"]), (3, 2))            # the 0.5 first fight counts as a pick of a

    def test_draws_skipped_and_methods(self):
        book = {"1": dict(date="2024-01-01", a=dict(id="x", name="x", won=False), b=dict(id="y", name="y", won=False))}
        self.assertEqual(M.run(book)[1], [])
        self.assertEqual([M.method(dict(result=r)) for r in ("KO/TKO", "Sub", "S-Dec", "U-Dec", None)],
                         ["KO", "Sub", "S-Dec", "U-Dec", None])

    def test_finish_rates(self):
        book = {"1": fight("2024-01-01", "x", "y", True, "Sub"), "2": fight("2024-02-01", "x", "z", True, "U-Dec")}
        self.assertEqual(M.finish_rates(book)["x"], [1, 2])


    def test_card_record(self):
        picks = {("A", "B"): dict(pick="A", conf=0.7), ("C", "D"): dict(pick="C", conf=0.55),
                 ("E", "F"): dict(pick="E", conf=0.8)}
        winners = {frozenset(("A", "B")): "A", frozenset(("C", "D")): "D"}           # E-F not finished
        r = M.card_record("20261107", picks=picks, winners=winners)
        self.assertEqual((r["won"], r["lost"], r["close"]), (1, 1, [0, 1]))
        self.assertEqual(r["losses"], ["C (55%) lost to D"])
        self.assertIsNone(M.card_record("x", picks={}, winners={}))


if __name__ == "__main__":
    unittest.main()
