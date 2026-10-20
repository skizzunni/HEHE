"""Item 7: closing line value for every graded pick, the weekly report, and
the hard rule -- no beating the close on Brier over the last 300 graded
picks, every model weight is 0."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import clv                                                # noqa: E402
import policy                                             # noqa: E402


def summary(away, home):
    return dict(pickcenter=[dict(provider=dict(name="DraftKings"),
                                 awayTeamOdds=dict(moneyLine=away), homeTeamOdds=dict(moneyLine=home))])


class Closing(unittest.TestCase):
    def test_closing_chance_and_clv(self):
        e = dict(league="nhl", myside="home", status="won", conf=60, price="-150", date="2026-10-18",
                 first=dict(conf=60))
        book = {"picks": {}}
        n = clv.update({"nhl:1": e}, book, get=lambda u: summary(150, -180))
        self.assertEqual(n, 1)
        r = book["picks"]["nhl:1"]
        imp_h, imp_a = 180 / 280, 100 / 250
        self.assertAlmostEqual(r["close"], imp_h / (imp_h + imp_a), places=4)   # proportional for nhl
        self.assertAlmostEqual(r["clv"], round(100 * (r["close"] - 0.60), 2))
        self.assertGreater(r["clv"], 0)                                          # market moved to the call

    def test_unpriced_never_logged(self):
        e = dict(league="wta", myside="away", status="won", conf=90, price=None, date="2026-10-18")
        book = {"picks": {}}
        self.assertEqual(clv.update({"wta:1": e}, book, get=lambda u: summary(-900, 600)), 0)

    def test_report_and_weekly(self):
        book = {"picks": {f"g{i}": dict(day="2026-10-1" + str(3 + i % 5), league="nhl", won=i % 2,
                                         call=i < 4, published=0.6, close=0.55 + (i % 3) / 20,
                                         clv=round(100 * (0.55 + (i % 3) / 20 - 0.6), 2)) for i in range(20)}}
        rep = clv.report(list(book["picks"].values()))
        self.assertEqual(rep["n"], 20)
        self.assertIn("brier_close", rep)
        wk = clv.weekly(book)
        self.assertEqual(sorted(wk), ["2026-W42"])
        self.assertEqual(wk["2026-W42"]["calls"]["n"], 4)


class HardRule(unittest.TestCase):
    def rows(self, pub, close, n=300):
        return {"picks": {f"g{i}": dict(day="2026-10-15", league="nhl", won=int(i % 10 < 7), published=pub,
                                         close=close, clv=round(100 * (close - pub), 2)) for i in range(n)}}

    def test_market_is_the_model_when_close_wins(self):
        v = clv.rule(self.rows(0.55, 0.70))                    # close nearer the 70% truth
        self.assertTrue(v["market_is_model"])
        v = clv.rule(self.rows(0.70, 0.55))
        self.assertFalse(v["market_is_model"])

    def test_weights_go_to_zero(self):
        path = os.path.join(tempfile.mkdtemp(), "clv.json")
        real_p, real_w = policy.CLV, policy._W
        try:
            policy._W = {"default": 0.3, "weights": {"nfl": 0.3}}
            policy.CLV = path
            with open(path, "w") as fh:
                json.dump(dict(market_is_model=False), fh)
            self.assertEqual(policy.model_weight("nfl"), 0.3)
            with open(path, "w") as fh:
                json.dump(dict(market_is_model=True), fh)
            self.assertEqual(policy.model_weight("nfl"), 0.0)
            self.assertEqual(policy.home_edge("ncaaf"), 0.0)
            os.remove(path)
            self.assertEqual(policy.model_weight("nfl"), 0.0)    # no verdict yet: the market
        finally:
            policy.CLV, policy._W = real_p, real_w


if __name__ == "__main__":
    unittest.main()
