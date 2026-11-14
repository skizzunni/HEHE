import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import locks                                                      # noqa: E402

W = [dict(league="ncaaf", band="getting 7-13.5", won=1, n=2, said=80),
     dict(league="nfl", band="getting 7-13.5", won=1, n=2, said=80),
     dict(league="nfl", band="getting 14+", won=168, n=221, said=84)]


class Prereg(unittest.TestCase):
    def test_fine_drops_the_tested_band_only(self):
        out = locks.apply_prereg(W, dict(verdict="fine"))
        self.assertEqual(out, [W[2]])

    def test_other_verdicts_keep_everything(self):
        for v in ("waiting", "short", None):
            self.assertEqual(locks.apply_prereg(W, dict(verdict=v)), W)
        self.assertEqual(locks.apply_prereg(W, None), W)
        self.assertEqual(locks.apply_prereg(None, dict(verdict="fine")), [])


class PreregPool(unittest.TestCase):
    P = [dict(league="ncaaf", t="teamunder", won=859, n=1111, said=82), dict(league="nfl", t="teamunder", won=1, n=2, said=80)]

    def test_fine_lifts_that_bet_type_only(self):
        self.assertEqual(locks.apply_prereg_pool(self.P, dict(verdict="fine"), locks.PREREG_NCAAF_TU), [self.P[1]])

    def test_waiting_or_band_tests_change_nothing(self):
        self.assertEqual(locks.apply_prereg_pool(self.P, dict(verdict="waiting"), locks.PREREG_NCAAF_TU), self.P)
        self.assertEqual(locks.apply_prereg_pool(self.P, dict(verdict="fine"), locks.PREREG), self.P)
        self.assertEqual(locks.apply_prereg(W, dict(verdict="fine"), locks.PREREG_NCAAF_TU), W)

    def test_registered(self):
        self.assertIn(locks.PREREG_NCAAF_TU, locks.PREREGS)
        self.assertEqual((locks.PREREG_NCAAF_TU["need"], locks.PREREG_NCAAF_TU["gap"], locks.PREREG_NCAAF_TU["since"]),
                         (150, 3.0, "2026-11-15"))


if __name__ == "__main__":
    unittest.main()
