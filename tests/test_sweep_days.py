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


if __name__ == "__main__":
    unittest.main()
