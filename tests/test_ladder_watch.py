import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ladder_watch as w                                          # noqa: E402


class LadderWatch(unittest.TestCase):
    def test_snapshot_and_changes(self):
        r = dict(today=dict(legs=[dict(label="A", status="open"), dict(label="B", status="won", score="X 2 - Y 1")]))
        s = w.snapshot(r)
        self.assertEqual(s, {"A": "open", "B": "won | X 2 - Y 1"})
        self.assertEqual(w.changes({}, s), [])                        # first look: nothing to report
        s2 = dict(s, A="lost | X 0 - Y 3")
        self.assertEqual(w.changes(s, s2), ["CHANGE: A = lost | X 0 - Y 3"])
        self.assertEqual(w.changes(s2, s2), [])

    def test_settled(self):
        done = w.snapshot(dict(today=None, last=dict(day="2026-11-07", result="lost"), bank=1.0))
        self.assertEqual(done, {"SETTLED": "2026-11-07 lost bank 1.0"})
        self.assertEqual(w.changes({"A": "open"}, done), ["SETTLED: 2026-11-07 lost bank 1.0"])
        self.assertEqual(w.changes(done, done), [])


if __name__ == "__main__":
    unittest.main()
