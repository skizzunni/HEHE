import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rebuild_board as B                                         # noqa: E402


class FillParts(unittest.TestCase):
    def test_one_failure_keeps_the_rest(self):
        out = {}
        bad = lambda: 1 / 0
        skipped = B.fill_parts(out, [("a", lambda: 1), ("b", bad), ("c", lambda: [2])])
        self.assertEqual(out, {"a": 1, "c": [2]})
        self.assertEqual(skipped, ["b: ZeroDivisionError"])

    def test_empty(self):
        self.assertEqual(B.fill_parts({}, []), [])


if __name__ == "__main__":
    unittest.main()
