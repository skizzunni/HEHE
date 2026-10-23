"""Item 5: every day, the TOP_N strongest published chances from fresh,
verified prices are the day's calls -- frozen once set, topped up when fewer
qualified, never padded with a softer number, every one in the record."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calls                                              # noqa: E402
import ledger                                             # noqa: E402

ET = calls._ET
NINE = dt.datetime(2026, 10, 20, 9, 0, tzinfo=ET).astimezone(dt.timezone.utc)


def row(i, conf, price_age=2, started=False, dc=False, legs=True, lg="nhl"):
    at = (NINE - dt.timedelta(minutes=price_age)).isoformat()
    start = NINE + dt.timedelta(hours=-1 if started else 4)
    return dict(id=f"{lg}:{i}", mypick=f"Team {i}", myside="home", myconf=conf, label=f"A{i} @ Team {i}",
                tip="1:00 PM", dc=dc, mkt=dict(start=start.isoformat()), price_at=at, price_book="DraftKings",
                legs=[dict(side="home", price="-150", at=at)] if legs else [])


def state(rows):
    return dict(dates=("20261020", "20261021"), slots=dict(today={"nhl": rows}, tomorrow={}))


class DailyCalls(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "calls.json")
        import news
        self._sum, news.summary = news.summary, lambda lg, gid: None        # no network
        # these tests are about selection, freezing and gates on one sport;
        # the per-sport cap has its own test below
        self._per, calls.PER_SPORT = calls.PER_SPORT, 99
        self._pol = (calls.MIN_DEC, calls.BENCHED)
        calls.MIN_DEC, calls.BENCHED = 1.0, set()          # not the live auto-tuned file

    def tearDown(self):
        import news
        news.summary = self._sum
        calls.PER_SPORT = self._per
        calls.MIN_DEC, calls.BENCHED = self._pol

    def test_benched_sport_gets_no_calls(self):
        calls.PER_SPORT, calls.BENCHED = 2, {"nhl"}
        rows = {"nhl": [row(1, 0.90), row(2, 0.85)], "nba": [row(3, 0.60, lg="nba")]}
        st = dict(dates=("20261020", "20261021"), slots=dict(today=rows, tomorrow={}))
        self.assertEqual(self.ids(calls.update_daily(st, NINE, self.path)), ["nba:3"])

    def test_at_most_two_per_sport_soccer_as_one(self):
        calls.PER_SPORT = 2
        rows = {"uel": [row(1, 0.85, lg="uel"), row(2, 0.84, lg="uel")],
                "uecl": [row(3, 0.83, lg="uecl"), row(4, 0.82, lg="uecl")],
                "nhl": [row(5, 0.70), row(6, 0.69), row(7, 0.68)],
                "nba": [row(8, 0.60, lg="nba")]}
        st = dict(dates=("20261020", "20261021"), slots=dict(today=rows, tomorrow={}))
        rec = calls.update_daily(st, NINE, self.path)
        # 2 soccer (the two strongest, across both soccer leagues), 2 NHL, then NBA
        self.assertEqual(self.ids(rec), ["uel:1", "uel:2", "nhl:5", "nhl:6", "nba:8"])

    def test_one_sport_day_gives_fewer_calls_not_softer_ones(self):
        calls.PER_SPORT = 2
        rec = calls.update_daily(state([row(i, 0.70 - i / 100) for i in range(6)]), NINE, self.path)
        self.assertEqual(self.ids(rec), ["nhl:0", "nhl:1"])

    def ids(self, rec):
        return [c["id"] for c in rec["calls"]]

    def test_top5_strongest_first_from_fresh_priced_unstarted(self):
        rows = [row(i, 0.55 + i / 100) for i in range(8)]                 # 55% .. 62%
        rows += [row(20, 0.95, price_age=30), row(21, 0.94, legs=False),  # stale, unpriced
                 row(22, 0.93, started=True), row(23, 0.92, dc=True)]     # started, double chance
        rec = calls.update_daily(state(rows), NINE, self.path)
        self.assertEqual(self.ids(rec), ["nhl:7", "nhl:6", "nhl:5", "nhl:4", "nhl:3"])
        self.assertEqual([c["conf"] for c in rec["calls"]], [62, 61, 60, 59, 58])

    def test_not_before_8am(self):
        early = NINE - dt.timedelta(hours=1, minutes=30)
        rec = calls.update_daily(state([row(1, 0.7)]), early, self.path)
        self.assertEqual(rec["calls"], [])

    def test_frozen_then_topped_up(self):
        calls.update_daily(state([row(1, 0.70), row(2, 0.60)]), NINE, self.path)    # 2 games: both called
        later = NINE + dt.timedelta(hours=1)
        rows = [row(1, 0.50), row(2, 0.90)] + [row(i, 0.80 - i / 100, price_age=-60) for i in range(3, 9)]
        rec = calls.update_daily(state(rows), later, self.path)
        self.assertEqual(self.ids(rec)[:2], ["nhl:1", "nhl:2"])           # never taken back
        self.assertEqual(rec["calls"][0]["conf"], 70)                     # at the chance it was called
        self.assertEqual(self.ids(rec)[2:], ["nhl:3", "nhl:4", "nhl:5"])  # topped up to 5, strongest
        self.assertEqual(len(calls.update_daily(state(rows), later, self.path)["calls"]), calls.TOP_N)

    def test_shadow_tickets_archived_once(self):
        rows = [row(i, 0.80 + i / 100) for i in range(6)]
        from test_news import goalies
        for r_ in rows:
            r_["legs"][0]["price"] = "-160"
            r_["comp"] = goalies("confirmed", "confirmed")
        rec = calls.update_daily(state(rows), NINE, self.path)
        sh = rec["shadow"]
        self.assertEqual(sh["version"], 2)
        self.assertEqual(len(sh["strategies"]["strongest_2x"]), 2)
        self.assertTrue(sh["strategies"]["optimizer_2x"])                                # -160 x2 = 2.62x: 2 legs
        later = calls.update_daily(state(rows), NINE + dt.timedelta(minutes=30), self.path)
        self.assertEqual(later["shadow"], sh)                             # never revised
        import sys as _s
        _s.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import shadow
        book = {c["id"]: dict(status="won", pick=c["pick"], winner=c["pick"], dc=c.get("dc")) for c in sh["pool"]}
        g = shadow.report(shadow.grade({"2026-10-20": rec}, book))
        self.assertEqual(g["strongest_2x"]["cashed"], 1)

    def test_close_call_label(self):
        real = dict(calls._MIN)
        calls._MIN.clear()
        calls._MIN["nhl"] = 0.70
        try:
            rec = calls.update_daily(state([row(1, 0.58), row(2, 0.75)]), NINE, self.path)
        finally:
            calls._MIN.clear()
            calls._MIN.update(real)
        lab = {c["id"]: c["close"] for c in rec["calls"]}
        self.assertEqual(lab, {"nhl:1": True, "nhl:2": False})            # 58% published as 58%, close

    def test_ledger_marks_calls(self):
        calls.update_daily(state([row(1, 0.7), row(2, 0.6)]), NINE, self.path)
        lpath = os.path.join(tempfile.mkdtemp(), "ledger.json")
        real_l, real_d = ledger.LEDGER, calls.DAILY
        ledger.LEDGER, calls.DAILY = lpath, self.path
        now = dt.datetime.now(dt.timezone.utc)
        rows = [dict(row(1, 0.7), price_at=now.isoformat(), mkt=dict(start=(now + dt.timedelta(hours=3)).isoformat()),
                     legs=[dict(side="home", price="-150", at=now.isoformat())])]
        try:
            ledger.record(state(rows))
            e = ledger.load()["nhl:1"]
        finally:
            ledger.LEDGER, calls.DAILY = real_l, real_d
        self.assertTrue(e.get("call"))
        self.assertEqual(e.get("call_rank"), 1)


if __name__ == "__main__":
    unittest.main()
