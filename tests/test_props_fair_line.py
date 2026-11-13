import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import daily_review as dr                                         # noqa: E402


class PropsFair(unittest.TestCase):
    def test_view_and_line(self):
        P = {"a": dict(status="won", p_fair=0.94, imp=0.91, p=0.85),
             "b": dict(status="lost", p_fair=0.92, imp=0.90, p=0.85),
             "c": dict(status="won", p_fair=None, imp=0.8, p=0.8),        # no fair chance: out
             "d": dict(status="open", p_fair=0.9, imp=0.9, p=0.85)}       # not graded: out
        v = dr.props_fair_view(P)
        self.assertEqual((v["n"], v["won"], v["said_fair"], v["said_price"], v["said_stated"]), (2, 1, 93.0, 90.5, 85.0))
        self.assertEqual(dr.props_fair_line(v), "Ladder-consistency props (all time): 1/2 won (50.0%) vs 93.0% fair, "
                                                "90.5% price, 85.0% stated on the board (heavy props capped).")

    def test_missing_stated_and_empty(self):
        v = dr.props_fair_view({"a": dict(status="won", p_fair=0.9, imp=0.9)})
        self.assertIsNone(v["said_stated"])
        self.assertTrue(dr.props_fair_line(v).endswith("90.0% price."))
        self.assertIsNone(dr.props_fair_line(dr.props_fair_view({})))
        self.assertIsNone(dr.props_fair_line(None))


if __name__ == "__main__":
    unittest.main()
