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


if __name__ == "__main__":
    unittest.main()
