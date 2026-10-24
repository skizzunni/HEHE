"""Value bets (a venue above the fair chance) and sure bets (both sides
cost under the payout), archived once when first seen and graded."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value_bets as V                                    # noqa: E402
from test_venues import FD, KB, START                     # noqa: E402

NOW = dt.datetime(2026, 10, 22, 18, tzinfo=dt.timezone.utc)


def row(p_home, home_price, away_price):
    at = NOW.isoformat()
    return dict(id="nhl:7", label="Boston Bruins @ Toronto Maple Leafs", tip="7:00 PM", price_book="DraftKings",
                price_at=at, mkt=dict(home="Toronto Maple Leafs", away="Boston Bruins", home_abbr="TOR",
                                      away_abbr="BOS", start=START),
                legs=[dict(side="home", who="Toronto Maple Leafs", prob=p_home, price=home_price, at=at),
                      dict(side="away", who="Boston Bruins", prob=1 - p_home, price=away_price, at=at)])


class Value(unittest.TestCase):
    def test_fanduel_above_fair_is_a_value_bet(self):
        # DraftKings -160/+135: Shin fair home ~59.7%; FanDuel -140 pays 1.714
        import devig
        fair = devig.fair(-160, 135, method="shin")[0]
        val, sure = V.scan("nhl", row(0.60, "-160", "+135"), FD, KB)
        fd = [v for v in val if v["venue"] == "FanDuel" and v["side"] == "home"]
        self.assertEqual(len(fd), 1)
        self.assertAlmostEqual(fd[0]["ev"], round(fair * (1 + 100 / 140) - 1, 4))
        self.assertAlmostEqual(fd[0]["fair"], round(fair, 4))
        self.assertTrue(all(v["venue"] != "DraftKings" for v in val))     # the reference is never a find

    def test_longshot_fair_is_shin_not_proportional(self):
        import devig
        prop = devig.fair(-900, 600, method="proportional")[1]
        shin = devig.fair(-900, 600, method="shin")[1]
        self.assertLess(shin, prop)                                        # the longshot gets less

    def test_no_value_when_every_price_is_below_fair(self):
        val, _ = V.scan("nhl", row(0.55, "-130", "+110"), FD, {})
        self.assertEqual([v for v in val if v["side"] == "home"], [])  # 0.55 x 1.714 < 1.01

    def test_sure_bet(self):
        # best home FanDuel -140 (1.714), best away DraftKings +160 (2.6): 0.583 + 0.385 < 1
        _, sure = V.scan("nhl", row(0.6, "-160", "+160"), FD, KB)
        self.assertIsNotNone(sure)
        cost = 1 / (1 + 100 / 140) + 1 / 2.6
        self.assertAlmostEqual(sure["profit"], round(1 / cost - 1, 4))
        self.assertAlmostEqual(sum(l["stake_share"] for l in sure["legs"]), 1.0, places=3)
        self.assertIsNone(V.scan("nhl", row(0.6, "-160", "+120"), FD, {})[1])

    def test_archived_once_and_graded(self):
        path = os.path.join(tempfile.mkdtemp(), "value.json")
        val, sure = V.scan("nhl", row(0.60, "-160", "+135"), FD, KB)
        self.assertGreater(V.record(val, [], NOW, path), 0)
        first = V.load(path)["finds"]
        val2 = [dict(v, ev=0.5) for v in val]
        self.assertEqual(V.record(val2, [], NOW + dt.timedelta(minutes=5), path), 0)
        self.assertEqual(V.load(path)["finds"], first)                     # never revised
        V.grade({"nhl:7": dict(status="won", winner="Toronto Maple Leafs",
                                scores={"Toronto Maple Leafs": 4, "Boston Bruins": 2})}, path)
        rep = V.report(path)
        self.assertEqual(rep["won"], sum(1 for v in val if v["team"] == "Toronto Maple Leafs"))


class Parlays(unittest.TestCase):
    def find(self, i, fair, price, venue="FanDuel"):
        import venues
        d = venues.dec(price)
        return dict(id=f"nhl:{i}", league="nhl", side="home", team=f"T{i}", venue=venue, price=price,
                    dec=round(d, 4), fair=fair, ev=round(fair * d - 1, 4))

    def test_parlay_of_value_legs_keeps_positive_ev(self):
        finds = [self.find(1, 0.62, "-150"), self.find(2, 0.55, "+100"), self.find(3, 0.45, "+140"),
                 self.find(4, 0.70, "-200", venue="Kalshi")]
        ps = V.value_parlays(finds, targets=(2.0, 3.0))
        self.assertTrue(ps)
        for p in ps:
            self.assertEqual(p["venue"], "FanDuel")                       # one book; Kalshi left out
            self.assertGreater(p["ev"], 0)
            self.assertGreaterEqual(p["payout"], p["target"])
            self.assertEqual(len({L["id"] for L in p["legs"]}), len(p["legs"]))

    def test_parlay_archived_and_graded(self):
        path = os.path.join(tempfile.mkdtemp(), "value.json")
        p = V.value_parlays([self.find(1, 0.62, "-150"), self.find(2, 0.55, "+100")], targets=(2.0,))
        self.assertEqual(V.record_parlays(p, NOW, path), 1)
        self.assertEqual(V.record_parlays(p, NOW, path), 0)
        V.grade_parlays({"nhl:1": dict(status="won", winner="T1"), "nhl:2": dict(status="won", winner="T2")}, path)
        self.assertEqual(V.parlay_report(path)["won"], 1)


class Lines(unittest.TestCase):
    def test_spread_and_total_settle_from_scores(self):
        e = dict(status="won", winner="Toronto Maple Leafs", scores={"Toronto Maple Leafs": 4, "Boston Bruins": 2})
        sp = lambda line: dict(team="Toronto Maple Leafs", spec=dict(t="spread", team="Toronto Maple Leafs", line=line))
        self.assertEqual(V.settle(sp(-1.5), e), "won")
        self.assertEqual(V.settle(sp(-2.0), e), "void")              # landed exactly: a push
        self.assertEqual(V.settle(sp(-2.5), e), "lost")
        self.assertEqual(V.settle(dict(spec=dict(t="over", line=5.5)), e), "won")
        self.assertEqual(V.settle(dict(spec=dict(t="under", line=6.0)), e), "void")
        self.assertIsNone(V.settle(dict(spec=dict(t="over", line=5.5)), dict(status="open")))

    def test_line_markets_fair_by_shin(self):
        import devig
        r = row(0.6, "-160", "+135")
        r["mkt"].update(ps_home=[-1.5, "+150"], ps_away=[1.5, "-180"], total=5.5, over="-110", under="-110")
        mk = {lab: (spec, p) for spec, lab, p, _ in V.line_markets(r)}
        self.assertAlmostEqual(mk["Toronto Maple Leafs -1.5"][1], devig.fair(150, -180, method="shin")[0])
        self.assertAlmostEqual(mk["over 5.5"][1], 0.5)
        r["mkt"]["ps_away"] = [2.5, "-180"]                            # lines that do not mirror: skipped
        self.assertNotIn("Toronto Maple Leafs -1.5", {lab for _, lab, _, _ in V.line_markets(r)})


class PropValue(unittest.TestCase):
    def game(self, props):
        return [dict(id="nfl:1", match="A @ B", tip="1:00 PM", props=props)]

    def P(self, p, fd_price, dk_price, two=True, line="249.5"):
        return dict(name="QB One", market="Passing Yards", line=line, label=f"QB One: Over {line} Passing Yards",
                    price=fd_price, p=p, two_sided=two, alt=dict(book="DraftKings", price=dk_price))

    def test_dk_above_fanduel_two_sided_fair(self):
        f = V.prop_value(self.game([self.P(0.52, "-115", "+100")]))
        self.assertEqual(len(f), 1)
        self.assertAlmostEqual(f[0]["ev"], round(0.52 * 2.0 - 1, 4))
        self.assertEqual(f[0]["venue"], "DraftKings")

    def test_no_find_without_an_honest_fair(self):
        self.assertEqual(V.prop_value(self.game([self.P(0.52, "-115", "+100", two=False)])), [])   # one-sided
        self.assertEqual(V.prop_value(self.game([self.P(0.30, "+230", "+260")])), [])              # longshot
        self.assertEqual(V.prop_value(self.game([self.P(0.52, "-115", "-120")])), [])              # below fair
        self.assertEqual(V.prop_value(self.game([self.P(0.48, "-110", "+120", line="u249.5")])), [])  # under side

    def test_logged_in_the_props_ledger(self):
        import props_ledger
        tmp = tempfile.mkdtemp()
        with mock.patch.object(props_ledger, "LEDGER", os.path.join(tmp, "props.json")):
            f = V.prop_value(self.game([self.P(0.52, "-115", "+100")]))
            path = os.path.join(tmp, "value.json")
            self.assertEqual(V.record_props(f, "2026-10-22", NOW, path), 1)
            self.assertEqual(V.record_props(f, "2026-10-22", NOW, path), 0)
            led = props_ledger.load()
            k = props_ledger.prop_key(f[0])
            self.assertTrue(led[k]["value_find"])
            led[k]["status"] = "won"
            props_ledger.save(led)
            self.assertEqual(V.prop_report(path)["won"], 1)


if __name__ == "__main__":
    unittest.main()
