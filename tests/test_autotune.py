"""The calls' rule and bench adapt to the record, only on strong evidence."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotune as A                                      # noqa: E402


def day(i):
    return f"2026-09-{1 + i:02d}"


def hist_one_sport_loses(days=28):
    """Each day: three 'nhl' picks rated strongest that lose, two 'nba' that win."""
    out = []
    for i in range(days):
        out += [dict(day=day(i), group="nhl", conf=90 - j, dec=1.5, won=False) for j in range(3)]
        out += [dict(day=day(i), group="nba", conf=60 - j, dec=1.5, won=True) for j in range(2)]
        out += [dict(day=day(i), group="mlb", conf=55 - j, dec=1.5, won=True) for j in range(2)]
    return out


class Choose(unittest.TestCase):
    def test_challenger_must_win_both_halves(self):
        h = hist_one_sport_loses()
        new, ev = A.choose(h, dict(per_sport=None, min_dec=1.0))
        self.assertTrue(ev["changed"])
        self.assertEqual(new["per_sport"], 1)        # fewest losing nhl picks per day

    def test_keeps_current_when_nothing_is_clearly_better(self):
        h = [dict(day=day(i), group=g, conf=70, dec=1.5, won=(i + j) % 2 == 0)
             for i in range(28) for j, g in enumerate(("a", "b", "c", "d", "e", "f"))]
        cur = dict(per_sport=2, min_dec=1.0)
        new, ev = A.choose(h, cur)
        self.assertEqual(new, cur)

    def test_too_little_history_changes_nothing(self):
        cur = dict(per_sport=2, min_dec=1.0)
        self.assertEqual(A.choose(hist_one_sport_loses(days=10), cur)[0], cur)


class Bench(unittest.TestCase):
    def test_clearly_losing_sport_is_benched_and_reinstated(self):
        h = hist_one_sport_loses()
        b = A.bench(h, "2026-09-28")
        self.assertTrue(b["nhl"]["benched"])
        self.assertFalse(b["nba"]["benched"])
        # the same sport winning at its price again is not benched
        h2 = [dict(x, won=True) if x["group"] == "nhl" else x for x in h]
        self.assertFalse(A.bench(h2, "2026-09-28")["nhl"]["benched"])

    def test_small_sample_is_never_benched(self):
        h = [dict(day=day(i), group="ufc", conf=70, dec=1.3, won=False) for i in range(A.BENCH_MIN - 1)]
        self.assertFalse(A.bench(h, "2026-09-28")["ufc"]["benched"])


class ValueBench(unittest.TestCase):
    def finds(self, n, won, dec, venue="FanDuel"):
        return [dict(kind="value", status="won" if i < won else "lost", dec=dec, venue=venue) for i in range(n)]

    def test_slice_that_cannot_break_even_is_benched(self):
        # 40 longshots at 6.0 (break-even 16.7%) that won 1: best case under break-even
        v = A.value_bench(self.finds(40, 1, 6.0))
        self.assertTrue(v["FanDuel longshot, single"]["benched"])

    def test_profitable_or_small_slices_stay(self):
        self.assertFalse(A.value_bench(self.finds(40, 22, 2.0))["FanDuel middle, single"]["benched"])
        self.assertFalse(A.value_bench(self.finds(A.VALUE_MIN - 1, 0, 6.0))["FanDuel longshot, single"]["benched"])

    def test_confirmed_and_single_are_judged_apart(self):
        fs = [dict(f, fair_source="DraftKings (Shin) + Polymarket") for f in self.finds(40, 8, 6.0)]
        fs += self.finds(40, 1, 6.0)
        v = A.value_bench(fs)
        self.assertFalse(v["FanDuel longshot, confirmed"]["benched"])     # 8 of 40 at 6.0: can still pay
        self.assertTrue(v["FanDuel longshot, single"]["benched"])

    def test_scan_leaves_out_benched_slices(self):
        import value_bets
        from unittest import mock
        rows = {"nhl": [dict(id="nhl:1")]}
        c = "consensus of 2 other venues"
        fake = [dict(id="nhl:1", venue="FanDuel", dec=6.0, ev=0.05, fair_source=c),
                dict(id="nhl:1", venue="FanDuel", dec=2.0, ev=0.02, fair_source=c)]
        with mock.patch.object(value_bets, "scan", lambda *a, **k: (list(fake), None)), \
             mock.patch("freshness.can_call", lambda r, now: True), \
             mock.patch("freshness.parse", lambda s: __import__("datetime").datetime(2099, 1, 1,
                        tzinfo=__import__("datetime").timezone.utc)), \
             mock.patch.object(A, "value_benched", lambda path=None: {"FanDuel longshot, confirmed"}):
            v, _ = value_bets.scan_all(rows)
        self.assertEqual([x["dec"] for x in v], [2.0])


class Run(unittest.TestCase):
    def test_log_records_changes(self):
        path = tempfile.mktemp(suffix=".json")
        import json
        A.history = lambda book, _h=hist_one_sport_loses(): _h
        try:
            out = A.run({}, "2026-09-28", path)
            self.assertEqual(out["benched"], ["nhl"])
            self.assertIn("benched", [x["what"] for x in out["log"]])
            self.assertEqual(json.load(open(path))["rule"]["per_sport"], 1)
        finally:
            import importlib
            importlib.reload(A)
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
