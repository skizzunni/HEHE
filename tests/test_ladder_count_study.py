import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ladder_count_study as s                                   # noqa: E402


class Counts(unittest.TestCase):
    def test_reach(self):
        self.assertEqual(s.reach(0.5, 2.42), (11, 0.5 ** 11))
        self.assertEqual(s.reach(1, 10, 100), (2, 1.0))
        self.assertIsNone(s.reach(0, 2))
        self.assertIsNone(s.reach(0.5, 1))

    def test_halves(self):
        rows = {2: [("2026-10-01", True, 1.5), ("2026-10-02", False, 1.6),
                    ("2026-10-03", True, 1.5), ("2026-10-04", True, 1.5)]}
        h = s.halves(rows)[2]
        self.assertEqual(h[0][:3], (1, 2, 1.55))
        self.assertEqual(h[1][:3], (2, 2, 1.5))
        self.assertEqual(h[1][3], (23, 1.0))           # 1.5^23 > 10,000; every card cashed
        self.assertEqual(s.halves({}), {})


if __name__ == "__main__":
    unittest.main()
