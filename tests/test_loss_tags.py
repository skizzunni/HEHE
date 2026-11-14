"""Why a pick lost, in countable tags, and the review's loss line."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ledger                                             # noqa: E402
import daily_review                                       # noqa: E402


class LossTags(unittest.TestCase):
    def test_band_margin_and_drift(self):
        e = dict(league="nhl", conf=52, first_price="-140", price="-118", scores={"A": 2, "B": 3})
        self.assertEqual(ledger.loss_tags(e), ["coin flip", "close game", "price moved against it (4 pts)"])
        e = dict(league="nba", conf=82, price="-560", scores={"A": 98, "B": 120})
        self.assertEqual(ledger.loss_tags(e), ["upset", "blowout"])
        e = dict(league="nfl", conf=68, first_price="-200", price="-210", scores={"A": 20, "B": 30})
        self.assertEqual(ledger.loss_tags(e), ["favourite lost"])

    def test_draw_tag(self):
        e = dict(league="epl", conf=66, price="-245", scores={"A": 0, "B": 0})
        self.assertEqual(ledger.loss_tags(e), ["favourite lost", "drawn"])

    def test_diagnose_says_drawn_once(self):
        d = ledger.diagnose(dict(league="epl", pick="A", conf=66, market_agrees=True), {"scores": {"A": 0, "B": 0}})
        self.assertEqual(d.count("drawn"), 1, d)

    def test_diagnose_carries_the_tags(self):
        d = ledger.diagnose(dict(league="nhl", pick="A", conf=52, market_agrees=True), {"scores": {"A": 2, "B": 3}})
        self.assertIn("coin flip", d)
        self.assertIn("close game", d)


class LossLine(unittest.TestCase):
    def test_line_names_pick_score_reason(self):
        line = daily_review.loss_line(dict(league="nhl", pick="Pittsburgh Penguins", said=52, price="-118",
                                           score={"Pittsburgh Penguins": 2, "Vegas Golden Knights": 3},
                                           why="margin 1", tags=["coin flip", "close game"]))
        self.assertEqual(line, "- LOST nhl Pittsburgh Penguins at 52% (-118), Pittsburgh Penguins 2 - "
                               "Vegas Golden Knights 3: margin 1 [coin flip, close game]")


class NoRepeat(unittest.TestCase):
    def test_tags_already_in_why_not_repeated(self):
        line = daily_review.loss_line(dict(league="ucl", pick="Liverpool", said=83, price="-700",
                                           why="margin 1 · called at 83% · upset · close game", tags=["upset", "close game"]))
        self.assertTrue(line.endswith("margin 1 · called at 83% · upset · close game"))


if __name__ == "__main__":
    unittest.main()
