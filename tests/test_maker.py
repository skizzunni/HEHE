"""Maker bids: candidates at the Kalshi bid with sportsbook value, a fill
decided by the trade tape, ROI only on fills."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import maker as M                                         # noqa: E402
from test_venues import KB, START                         # noqa: E402

ROW = dict(id="nhl:1", label="BOS @ TOR",
           mkt=dict(home="Toronto Maple Leafs", away="Boston Bruins", home_abbr="TOR", away_abbr="BOS", start=START),
           legs=[dict(side="home", price="-175"), dict(side="away", price="+150")])


class Fee(unittest.TestCase):
    def test_maker_fee_rounds_up(self):
        # 0.0175 x 100 x 0.59 x 0.41 = $0.4233 -> $0.43 on 100 contracts
        self.assertAlmostEqual(M.fee(0.59), 0.0043)


class Candidates(unittest.TestCase):
    def setUp(self):
        self._lg = M.LEAGUES
        M.LEAGUES = ("nhl",)

    def tearDown(self):
        M.LEAGUES = self._lg

    def test_untested_league_has_no_candidates(self):
        M.LEAGUES = ("nfl",)
        self.assertEqual(M.candidates("nhl", ROW, KB), [])

    def test_bid_is_one_minus_the_other_ask_and_needs_value(self):
        c = M.candidates("nhl", ROW, KB)
        self.assertEqual(len(c), 1)
        x = c[0]
        self.assertEqual((x["side"], x["bid"], x["ask"]), ("YES", 0.59, 0.60))
        self.assertGreaterEqual(x["fair"], x["cost"])
        # the same leg at a price the books rate below cost is no candidate
        weak = dict(ROW, legs=[dict(side="home", price="-130"), dict(side="away", price="+110")])
        self.assertEqual(M.candidates("nhl", weak, KB), [])


class Fill(unittest.TestCase):
    T = [dict(taker_side="no", yes_price_dollars="0.5900", no_price_dollars="0.4100"),
         dict(taker_side="yes", yes_price_dollars="0.6000", no_price_dollars="0.4000")]

    def test_touch_strict_and_wrong_side(self):
        self.assertEqual(M.fill(self.T, "YES", 0.59), "touch")
        self.assertEqual(M.fill(self.T, "YES", 0.60), "strict")
        self.assertIsNone(M.fill(self.T, "YES", 0.58))
        # a YES taker at 60c fills a NO bid at 40c or better for the bidder
        self.assertEqual(M.fill(self.T, "NO", 0.41), "strict")


class Queue(unittest.TestCase):
    T = [dict(taker_side="no", yes_price_dollars="0.5900", count_fp="300.00"),
         dict(taker_side="no", yes_price_dollars="0.5900", count_fp="250.00")]

    def test_volume_at_the_bid_must_clear_the_queue(self):
        self.assertEqual(M.fill(self.T, "YES", 0.59, queue=500), "queue")     # 550 traded > 500 ahead
        self.assertEqual(M.fill(self.T, "YES", 0.59, queue=1000), "touch")    # not reached
        self.assertEqual(M.fill(self.T, "YES", 0.59), "touch")                # queue unknown

    def test_queue_read_from_the_book(self):
        book = {"orderbook_fp": {"yes_dollars": [["0.5800", "10"], ["0.5900", "123.5"]], "no_dollars": []}}
        with mock.patch.object(M, "_get", lambda url, tries=3: book):
            self.assertEqual(M.queue_ahead("T", "YES", 0.59), 123.5)
            self.assertEqual(M.queue_ahead("T", "YES", 0.60), 0.0)       # nobody at our price
        with mock.patch.object(M, "_get", lambda url, tries=3: None):
            self.assertIsNone(M.queue_ahead("T", "YES", 0.59))


class Grade(unittest.TestCase):
    def test_roi_only_on_fills(self):
        path = tempfile.mktemp(suffix=".json")
        now = dt.datetime(2026, 10, 22, 20, tzinfo=dt.timezone.utc)
        M.save({"bids": {
            "A|YES": dict(ticker="A", side="YES", bid=0.59, cost=0.5943, edge=0.01, start=START,
                          posted=now.isoformat(), status="open"),
            "B|YES": dict(ticker="B", side="YES", bid=0.59, cost=0.5943, edge=0.01, start=START,
                          posted=now.isoformat(), status="open")}}, path)
        tapes = {"A": Fill.T, "B": []}

        def fake(url, tries=3):
            t = url.split("ticker=")[-1].split("&")[0] if "trades" in url else url.rsplit("/", 1)[-1]
            return {"trades": tapes[t]} if "trades" in url else {"market": dict(result="yes")}
        with mock.patch.object(M, "_get", fake), mock.patch.object(M.time, "sleep", lambda s: None):
            M.grade(now=dt.datetime(2026, 10, 23, 3, tzinfo=dt.timezone.utc), path=path)
        r = M.report(path)
        os.remove(path)
        self.assertEqual((r["graded"], r["any"]["n"], r["unfilled_n"]), (2, 1, 1))
        self.assertAlmostEqual(r["any"]["roi"], round(100 * (1 - 0.5943) / 0.5943, 2))
        self.assertNotIn("strict", r)


if __name__ == "__main__":
    unittest.main()
