"""Item 8: lineup gates per league, news freezes a league's calls until a
price captured after it, and the 3-point move rule re-derives or pulls."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calls                                              # noqa: E402
import ledger                                             # noqa: E402
import news                                               # noqa: E402

NINE = dt.datetime(2026, 10, 20, 9, 0, tzinfo=calls._ET).astimezone(dt.timezone.utc)


def goalies(*status):
    return dict(competitors=[dict(team=dict(abbreviation=t), probables=[dict(
        name="probableStartingGoalie", athlete=dict(displayName=f"G{t}"), status=dict(type=s))])
        for t, s in zip(("AAA", "BBB"), status)])


def xi(n):
    return dict(rosters=[dict(team=dict(abbreviation=t), roster=[dict(athlete=dict(displayName=f"{t}{i}"),
                                                                     starter=i < n) for i in range(18)])
                         for t in ("AAA", "BBB")])


class Gates(unittest.TestCase):
    def test_nhl_needs_confirmed_goalies(self):
        self.assertFalse(news.status("nhl", dict(comp=goalies("expected", "confirmed")), {})[0])
        self.assertFalse(news.status("nhl", dict(comp=goalies("probable", "probable")), {})[0])
        self.assertTrue(news.status("nhl", dict(comp=goalies("confirmed", "confirmed")), {})[0])

    def test_soccer_needs_both_xis(self):
        self.assertFalse(news.status("epl", {}, xi(0))[0])
        self.assertTrue(news.status("epl", {}, xi(11))[0])

    def test_mlb_needs_starters_and_lineups(self):
        comp = dict(competitors=[dict(team=dict(abbreviation=t), probables=[dict(
            name="probableStartingPitcher", athlete=dict(displayName="P"), status=dict(type="confirmed"))])
            for t in ("AAA", "BBB")])
        self.assertFalse(news.status("mlb", dict(comp=comp), xi(0))[0])
        self.assertTrue(news.status("mlb", dict(comp=comp), xi(9))[0])

    def test_news_changes_the_fingerprint(self):
        a = news.status("nhl", dict(comp=goalies("expected", "expected")), {})[2]
        b = news.status("nhl", dict(comp=goalies("confirmed", "expected")), {})[2]
        self.assertNotEqual(a, b)


class MoveRule(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "calls.json")
        self.comp = goalies("expected", "expected")

    def row(self, p_home, at, i=1):
        return dict(id=f"nhl:{i}", mypick=f"Team {i}", myside="home", myconf=p_home, label="A @ B", tip="7:00 PM",
                    comp=self.comp, mkt=dict(start=(NINE + dt.timedelta(hours=10)).isoformat()),
                    price_at=at.isoformat(), price_book="DraftKings",
                    legs=[dict(side="home", prob=p_home, price="-200", at=at.isoformat()),
                          dict(side="away", prob=1 - p_home, price="+170", at=at.isoformat())])

    def run_at(self, t, p, comp=None):
        if comp:
            self.comp = comp
        st = dict(dates=("20261020", "20261021"), slots=dict(today={"nhl": [self.row(p, t)]}, tomorrow={}))
        return calls.update_daily(st, t, self.path, n=1, summary=lambda lg, gid: {})

    def test_freeze_then_rederive_then_pull(self):
        c = self.run_at(NINE, 0.70)["calls"][0]
        self.assertEqual(c["conf"], 70)
        # a goalie is confirmed at 10:00; the price in that build is from
        # before the news, so the league is frozen even though it moved 6 pts
        t1 = NINE + dt.timedelta(hours=1)
        rec = self.run_at(t1, 0.76, goalies("confirmed", "expected"))
        self.assertEqual(rec["frozen"], ["nhl"])
        self.assertEqual(rec["calls"][0]["conf"], 70)
        self.assertEqual(rec["calls"][0]["log"][-1]["event"], "news")
        # the next build has a price captured after the news: re-derived
        t2 = t1 + dt.timedelta(minutes=5)
        rec = self.run_at(t2, 0.76)
        self.assertEqual(rec["frozen"], [])
        self.assertEqual((rec["calls"][0]["conf"], rec["calls"][0]["log"][-1]["event"]), (76, "re-derived"))
        # within 3 points: unchanged
        rec = self.run_at(t2 + dt.timedelta(minutes=5), 0.78)
        self.assertEqual(rec["calls"][0]["conf"], 76)
        # the side is no longer the favourite: pulled, logged, slot left empty
        rec = self.run_at(t2 + dt.timedelta(minutes=10), 0.45)
        self.assertEqual(rec["calls"][0]["status"], "pulled")
        self.assertEqual(len(rec["calls"]), 1)

    def test_pulled_call_does_not_count(self):
        self.run_at(NINE, 0.70)
        t = NINE + dt.timedelta(minutes=5)
        self.run_at(t, 0.40)
        lpath = os.path.join(tempfile.mkdtemp(), "ledger.json")
        real_l, real_d = ledger.LEDGER, calls.DAILY
        ledger.LEDGER, calls.DAILY = lpath, self.path
        now = dt.datetime.now(dt.timezone.utc)
        r = self.row(0.40, now)
        r["mkt"]["start"] = (now + dt.timedelta(hours=2)).isoformat()
        r["mypick"], r["myside"], r["myconf"] = "Team 1", "home", 0.6     # still recorded as a board pick
        try:
            ledger.record(dict(dates=("20261020", "20261021"), slots=dict(today={"nhl": [r]}, tomorrow={})))
            e = ledger.load()["nhl:1"]
        finally:
            ledger.LEDGER, calls.DAILY = real_l, real_d
        self.assertFalse(e["call"])
        self.assertTrue(e["call_pulled"])


if __name__ == "__main__":
    unittest.main()
