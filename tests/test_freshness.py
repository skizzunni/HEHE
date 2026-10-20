"""Item 1, the price freshness gate: every price carries its book and capture
time, and a price older than 15 minutes (or untimed) is never a call, never
recorded and never in a ticket or pool."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import dashboard                                          # noqa: E402
import fanduel                                            # noqa: E402
import ledger                                             # noqa: E402
import locks                                              # noqa: E402
import parlays                                            # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def ago(minutes):
    return (NOW - dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


class Recording(unittest.TestCase):
    def record(self, at, legs=True):
        path = os.path.join(tempfile.mkdtemp(), "ledger.json")
        start = (NOW + dt.timedelta(hours=3)).isoformat()
        row = dict(id="nhl:7", mypick="Boston Bruins", myside="home", myconf=0.62, label="A @ B",
                   legs=[dict(side="home", price="-160", at=at)] if legs else [],
                   mkt=dict(start=start), price_at=at, price_book="DraftKings")
        state = dict(dates=("20261020", "20261021"), slots=dict(today={"nhl": [row]}, tomorrow={}))
        real, ledger.LEDGER = ledger.LEDGER, path
        try:
            ledger.record(state)
            return ledger.load().get("nhl:7")
        finally:
            ledger.LEDGER = real

    def test_fresh_price_recorded_with_book_and_time(self):
        e = self.record(ago(5))
        self.assertIsNotNone(e)
        self.assertEqual((e["price_book"], e["price_at"]), ("DraftKings", ago(5)))
        self.assertEqual(e["history"][-1]["price_at"], ago(5))

    def test_stale_price_never_recorded(self):
        self.assertIsNone(self.record(ago(20)))

    def test_no_timestamp_no_price(self):
        self.assertIsNone(self.record(None))


class Collect(unittest.TestCase):
    """dashboard.collect stamps every leg with its book and capture time."""

    def test_legs_carry_book_and_capture_time(self):
        start = NOW + dt.timedelta(hours=2)
        day = start.astimezone(dashboard.ET).strftime("%Y%m%d")
        comp = dict(id="55", date=start.strftime("%Y-%m-%dT%H:%MZ"), status=dict(type=dict(state="pre")),
                    competitors=[dict(homeAway="away", team=dict(displayName="Away FC", abbreviation="AWY")),
                                 dict(homeAway="home", team=dict(displayName="Home FC", abbreviation="HOM"))],
                    odds=[dict(provider=dict(name="DraftKings"),
                               moneyline=dict(away=dict(close=dict(odds="+150")),
                                              home=dict(close=dict(odds="-180"))))])
        cache = tempfile.mkdtemp()
        url = f"{dashboard.ESPN}/hockey/nhl/scoreboard?dates={day}"
        with open(os.path.join(cache, dashboard._ckey(url)), "w") as fh:
            json.dump(dict(events=[dict(competitions=[comp])]), fh)
        real, dashboard._GET_CACHE = dashboard._GET_CACHE, cache
        try:
            rows = dashboard.collect("nhl", "hockey/nhl", day, {}, None)
        finally:
            dashboard._GET_CACHE = real
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["price_book"], "DraftKings")
        self.assertTrue(all(L["book"] == "DraftKings" and L["at"] == r["price_at"] for L in r["legs"]))
        age = (dt.datetime.now(dt.timezone.utc)
               - dt.datetime.fromisoformat(r["price_at"])).total_seconds()
        self.assertLess(age, 60)


class Pools(unittest.TestCase):
    """A stale FanDuel quote never enters a Locks pool; a stale board price
    never enters a Card parlay."""

    def setUp(self):
        self._alts, self._elig, self._qt = fanduel.load_alts, locks._eligible, fanduel.quote_time
        locks._eligible = lambda r, d, n: True
        fanduel.load_alts = lambda g: [("dc", "Brighton", None, None, "d:1", "-600", "DC")]

    def tearDown(self):
        fanduel.load_alts, locks._eligible, fanduel.quote_time = self._alts, self._elig, self._qt

    def pool(self, quoted):
        from test_core import soccer_board, soccer_book
        start = (NOW + dt.timedelta(hours=3)).isoformat()
        fanduel.quote_time = lambda g: quoted
        return locks.build({"epl": [soccer_board(start)]}, {"epl"}, {}, soccer_book(start),
                           day="20261018", dec=locks.SAFE_DEC, band=locks.SAFE_BAND)["pool"]

    def test_locks_pool_fresh_only(self):
        self.assertTrue(self.pool(ago(5)))
        self.assertEqual(self.pool(ago(20)), [])
        self.assertEqual(self.pool(None), [])

    def test_card_parlays_skip_stale_rows(self):
        def row(i, st):
            return dict(mp=f"Team {i}", mc=80.0, hit=0.8, p="+100", d=False, nc=False, st=st,
                        id=f"nfl:{i}", lg="NFL", t="1:00 PM")
        res = parlays.build({"nfl": {"rows": [row(1, False), row(2, True), row(3, False)]}})
        self.assertEqual(res["pool"], 2)                     # Team 2's price is stale
        self.assertNotIn("Team 2", json.dumps(res))


if __name__ == "__main__":
    unittest.main()
