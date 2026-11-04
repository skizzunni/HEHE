"""The whole board day by day, for the board-sweep tile."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ledger                                             # noqa: E402


class SweepDays(unittest.TestCase):
    def test_days_before_today_newest_first(self):
        done = [dict(date="2026-11-02", status="won"), dict(date="2026-11-02", status="lost"),
                dict(date="2026-11-03", status="won"), dict(date="2026-11-04", status="won")]
        got = ledger.sweep_days(done, lambda e: e["date"], "2026-11-04")
        self.assertEqual(got, [dict(day="2026-11-03", won=1, lost=0), dict(day="2026-11-02", won=1, lost=1)])


class NextUp(unittest.TestCase):
    def test_earliest_open_picks_today(self):
        book = {"a": dict(status="open", date="2026-11-04", tip="7:00 PM", pick="A", conf=60, price="-150", league="nba"),
                "b": dict(status="open", date="2026-11-04", tip="12:45 PM", pick="B", conf=78, price="-450", league="ucl"),
                "c": dict(status="won", date="2026-11-04", tip="10:00 AM", pick="C", conf=70),
                "d": dict(status="open", date="2026-11-05", tip="9:00 AM", pick="D", conf=70)}
        orig = ledger.record_priced
        ledger.record_priced = lambda e: True
        try:
            got = ledger.next_up(book, "2026-11-04")
        finally:
            ledger.record_priced = orig
        self.assertEqual([x["pick"] for x in got], ["B", "A"])
        self.assertEqual(ledger._tip_min("12:45 PM"), 765)


if __name__ == "__main__":
    unittest.main()
