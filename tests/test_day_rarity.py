import unittest
import ledger


class DayRarity(unittest.TestCase):
    def test_exact_tail(self):
        rows = [dict(conf=50, status="lost", league="nhl"), dict(conf=50, status="won", league="nhl")]
        r = ledger.day_rarity(rows)
        self.assertEqual(r["expected_losses"], 1.0)
        self.assertEqual(r["as_bad_pct"], 75.0)          # 1 or 2 losses of two coin flips
        self.assertEqual(r["lost_by_league"], {"nhl": 1})

    def test_rare_day(self):
        rows = [dict(conf=90, status="lost", league="uel") for _ in range(3)]
        self.assertEqual(ledger.day_rarity(rows)["as_bad_pct"], 0.1)

    def test_no_losses_is_certain(self):
        r = ledger.day_rarity([dict(conf=80, status="won", league="mlb")])
        self.assertEqual((r["as_bad_pct"], r["lost_by_league"]), (100.0, {}))

    def test_empty(self):
        self.assertEqual(ledger.day_rarity([]), {})


class ReviewSweepLine(unittest.TestCase):
    def test_broken_sweep_says_how_unusual(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        text = daily_review.sweep_line(dict(won=17, lost=2, open=32, broke_on="arg San Lorenzo at 68%",
                                            expected_losses=5.3, as_bad_pct=98.5))
        self.assertIn("Board sweep: 17-2, 32 open -- broken (first loss: arg San Lorenzo at 68%); 5.3 losses expected"
                      " from the settled picks' chances, so 2 or more by now had a 98.5% chance.", text)
        self.assertEqual(daily_review.sweep_line(dict(won=5, lost=0, open=3, broke_on=None, expected_losses=0.9,
                                                      as_bad_pct=100.0)), "Board sweep: 5-0, 3 open -- still clean.")
        self.assertIsNone(daily_review.sweep_line({}))
        y = dict(day="2026-11-06", sweep=dict(won=40, lost=9, broke_on="arg San Lorenzo at 68%", expected_losses=13.3, as_bad_pct=95.0))
        self.assertEqual(daily_review.yesterday_line(y), "Yesterday (2026-11-06): board 40-9, sweep broken by arg San Lorenzo at 68%;"
                         " 13.3 losses expected, 9 came in (95% chance of that many or more).")
        self.assertEqual(daily_review.yesterday_line(dict(day="2026-11-05", sweep=dict(won=30, lost=0))),
                         "Yesterday (2026-11-05): board 30-0, clean sweep.")


class CallCautions(unittest.TestCase):
    def test_short_in_both_halves_only(self):
        book = {}
        for d in range(1, 9):
            for i in range(6):
                book[f"a{d}{i}"] = dict(league="ncaaf", conf=75, date=f"2026-11-0{d}", status="won" if i < 3 else "lost")
                book[f"b{d}{i}"] = dict(league="nfl", conf=75, date=f"2026-11-0{d}",
                                        status="won" if (i < 2 if d < 5 else i < 6) else "lost")   # short then long
        self.assertEqual(ledger.call_cautions(book), [dict(league="ncaaf", band=70, won=24, n=48, said=75)])
        self.assertEqual(ledger.call_cautions({}), [])


if __name__ == "__main__":
    unittest.main()
