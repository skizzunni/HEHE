"""My own picks with prices hidden, head to head with the market."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ledger                                             # noqa: E402


def e(date, status, agrees, model_away, mkt_away):
    return dict(date=date, status=status, market_agrees=agrees, matchup="AAA @ HHH", price="-150",
                history=[dict(p_model_away=model_away, p_market_away=mkt_away)])


class OwnView(unittest.TestCase):
    def test_head_to_head_and_disagreements(self):
        book = {"nba:1": e("2026-11-03", "won", True, 0.6, 0.6),     # both took away; won
                "nba:2": e("2026-11-03", "won", True, 0.4, 0.6),     # market away won; mine wrong
                "nba:3": e("2026-11-03", "lost", True, 0.4, 0.6),    # market away lost; mine right
                "nba:4": e("2026-11-04", "open", True, 0.4, 0.6)}    # today, a disagreement
        orig = ledger.record_priced
        ledger.record_priced = lambda x: True
        try:
            v = ledger.own_view(book, "2026-11-04")
        finally:
            ledger.record_priced = orig
        self.assertEqual((v["n"], v["own"], v["market"]), (3, 2, 2))
        self.assertEqual(v["today"], [dict(league="nba", match="AAA @ HHH", own="HHH", own_p=60, market="AAA", market_p=60)])


if __name__ == "__main__":
    unittest.main()
