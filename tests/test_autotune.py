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
