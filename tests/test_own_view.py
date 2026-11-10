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
        # two disagreements, my side the market dog at 40%: one lost (-1), one won (+1.5)
        self.assertEqual((v["dog_n"], v["dog_roi"]), (2, 25.0))
        self.assertEqual(v["today"], [dict(league="nba", match="AAA @ HHH", own="HHH", own_p=60, market="AAA", market_p=60)])


class Upsets(unittest.TestCase):
    def test_live_dogs_and_record(self):
        book = {"nhl:1": dict(date="2026-11-03", status="lost", conf=55, price="-120", first_price="-150", matchup="OTT @ BUF", pick="BUF",
                              history=[dict(p_model_away=0.6, p_market_away=0.45)]),
                "nhl:2": dict(date="2026-11-04", status="open", conf=54, price="-130", first_price="-148", matchup="OTT @ BUF", pick="BUF",
                              history=[dict(p_model_away=0.52, p_market_away=0.46)]),
                "nba:3": dict(date="2026-11-04", status="open", conf=80, price="-400", matchup="A @ B", pick="B", history=[])}
        orig = ledger.record_priced
        ledger.record_priced = lambda x: True
        try:
            u = ledger.upset_view(book, "2026-11-04")
        finally:
            ledger.record_priced = orig
        self.assertEqual([(x["dog"], x["chance"], x["signals"]) for x in u["today"]],
                         [("OTT", 46, ["my model picks them", "price moving their way"])])
        self.assertEqual((u["record"]["n"], u["record"]["won"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
