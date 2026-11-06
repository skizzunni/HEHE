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


if __name__ == "__main__":
    unittest.main()
