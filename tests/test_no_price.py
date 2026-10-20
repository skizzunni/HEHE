"""Item 2, no price, no call: a pick with no verifiable sportsbook price (a
Kalshi or model number alone) is a lean -- never a call, never recorded,
never in a ticket -- and is labelled with what informs it."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import dashboard                                          # noqa: E402
import freshness                                          # noqa: E402
import ledger                                             # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def tennis_lean():
    """The 2026-10 tennis rows: 'Kalshi 94%', no line."""
    return dict(id="wta:9", mypick="Player One", myside="away", myconf=0.94, label="Player One vs Player Two",
                why="rank 3 vs 88 · Kalshi 94%", src="Kalshi", legs=[],
                mkt=dict(start=(NOW + dt.timedelta(hours=3)).isoformat()))


class NoPriceNoCall(unittest.TestCase):
    def test_never_recorded(self):
        path = os.path.join(tempfile.mkdtemp(), "ledger.json")
        state = dict(dates=("20261020", "20261021"), slots=dict(today={"wta": [tennis_lean()]}, tomorrow={}))
        real, ledger.LEDGER = ledger.LEDGER, path
        try:
            ledger.record(state)
            self.assertNotIn("wta:9", ledger.load())
        finally:
            ledger.LEDGER = real

    def test_never_in_a_ticket_pool(self):
        priced = dict(tennis_lean(), id="wta:10", legs=[dict(side="away", price="-900", at=NOW.isoformat())],
                      price_at=NOW.isoformat())
        out = freshness.fresh_days({"today": {"wta": [tennis_lean(), priced]}}, NOW)
        self.assertEqual([r["id"] for r in out["today"]["wta"]], ["wta:10"])

    def test_source_is_labelled(self):
        """collect keeps the non-book source behind an unpriced pick."""
        start = NOW + dt.timedelta(hours=2)
        day = start.astimezone(dashboard.ET).strftime("%Y%m%d")
        comp = dict(id="77", date=start.strftime("%Y-%m-%dT%H:%MZ"), status=dict(type=dict(state="pre")),
                    competitors=[dict(homeAway="away", team=dict(displayName="Away FC")),
                                 dict(homeAway="home", team=dict(displayName="Home FC"))])
        cache = tempfile.mkdtemp()
        url = f"{dashboard.ESPN}/hockey/nhl/scoreboard?dates={day}"
        with open(os.path.join(cache, dashboard._ckey(url)), "w") as fh:
            json.dump(dict(events=[dict(competitions=[comp])]), fh)
        book = {"nhl": {("Away FC", "Home FC"): dict(pick="Away FC", conf=0.94, why="Kalshi 94%", src="Kalshi")}}
        real, dashboard._GET_CACHE = dashboard._GET_CACHE, cache
        try:
            r = dashboard.collect("nhl", "hockey/nhl", day, {}, book)[0]
        finally:
            dashboard._GET_CACHE = real
        self.assertEqual((r["legs"], r["src"]), ([], "Kalshi"))
        self.assertFalse(freshness.can_call(r))


if __name__ == "__main__":
    unittest.main()
