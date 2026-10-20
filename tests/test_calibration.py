"""Item 4: walk-forward calibration (fit only on earlier days, minimum 200
graded picks), whole-percent publishing, the calibration table and its
2-SE flags."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibration as C                                   # noqa: E402
import ledger                                             # noqa: E402


def picks(n, conf, hit, day0="2026-09-01", lg="ncaaf"):
    out, d0 = [], dt.date.fromisoformat(day0)
    for i in range(n):
        won = (i * hit) % 1 + hit >= 1
        out.append(dict(league=lg, conf=conf, price="-300", status="won" if won else "lost",
                        date=(d0 + dt.timedelta(days=i // 10)).isoformat()))
    return out


class WalkForward(unittest.TestCase):
    def test_needs_200_and_only_earlier_days(self):
        ent = picks(199, 70.0, 0.9)
        self.assertNotIn("a", C.fit(ent, "ncaaf", "2026-12-31"))         # 199: raw
        ent += picks(1, 70.0, 0.9, day0="2026-11-01")
        f = C.fit(ent, "ncaaf", "2026-12-31")
        self.assertEqual(f["n"], 200)
        # the same 200 picks, but the 200th is on the pick's own day: excluded
        self.assertNotIn("a", C.fit(ent, "ncaaf", "2026-11-01"))
        self.assertGreater(C.apply(f, 0.70), 0.70)                      # 70% that hit 90%

    def test_window_is_the_most_recent(self):
        ent = picks(300, 70.0, 0.5) + picks(400, 70.0, 0.9, day0="2026-10-01")
        f = C.fit(ent, "ncaaf", "2026-12-31")
        self.assertEqual((f["n"], f["train"][0]), (C.WINDOW, "2026-10-01"))

    def test_unpriced_never_trains(self):
        ent = [dict(e, price=None) for e in picks(250, 70.0, 0.9)]
        self.assertEqual(C.fit(ent, "ncaaf", "2026-12-31")["n"], 0)

    def test_publish_whole_percent_raw_while_off(self):
        pub = C.Publisher(picks(300, 70.0, 0.95), "2026-12-31")
        self.assertFalse(C.ENABLED)                     # failed its untouched test (README item 4)
        self.assertEqual(pub.publish("ncaaf", 0.6172)[0], 62)


class Recorded(unittest.TestCase):
    def test_ledger_records_whole_percent_and_raw(self):
        path = os.path.join(tempfile.mkdtemp(), "ledger.json")
        now = dt.datetime.now(dt.timezone.utc)
        at = now.isoformat(timespec="seconds")
        row = dict(id="nhl:3", mypick="Boston Bruins", myside="home", myconf=0.6172, label="A @ B",
                   legs=[dict(side="home", price="-160", at=at)], price_at=at,
                   mkt=dict(start=(now + dt.timedelta(hours=3)).isoformat()))
        state = dict(dates=("20261020", "20261021"), slots=dict(today={"nhl": [row]}, tomorrow={}))
        real, ledger.LEDGER = ledger.LEDGER, path
        C._PUB.clear()
        try:
            ledger.record(state)
            e = ledger.load()["nhl:3"]
        finally:
            ledger.LEDGER = real
        self.assertEqual((e["conf"], e["p_raw"]), (62, 61.7))


class Table(unittest.TestCase):
    def test_flags_a_bin_trailing_by_2se(self):
        t = C.table(picks(100, 85.0, 0.70) + picks(100, 65.0, 0.66, lg="nhl"))
        b = {x["bin"]: x for x in t["overall"]}
        self.assertTrue(b["80-90"]["flag"])             # 70% against 85%: 4.2 SE
        self.assertFalse(b["60-70"]["flag"])
        self.assertEqual(t["leagues"]["nhl"]["n"], 100)
        self.assertEqual(t["dates"], ["2026-09-01", "2026-09-10"])


if __name__ == "__main__":
    unittest.main()
