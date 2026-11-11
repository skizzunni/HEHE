import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ladder_study as s                                          # noqa: E402


class SkipStudy(unittest.TestCase):
    def test_with_and_without_props(self):
        legs = {"a": dict(label="Over 200.5 points", p=0.8, price="-400", gid="g1", status="won"),
                "b": dict(label="Over 210.5 points", p=0.8, price="-400", gid="g2", status="won"),
                "c": dict(label="Over 220.5 points", p=0.8, price="-400", gid="g3", status="won"),
                "d": dict(label="P: 2+ Assists", kind="prop", p=0.9, price="-400", gid="g4", status="lost"),
                "e": dict(label="Over 230.5 points", p=0.78, price="-400", gid="g5", status="won")}
        book = dict(days={"2026-11-01": ["a", "b", "c", "d", "e"]}, legs=legs)
        out = s.skip_study(book)
        self.assertEqual(out[("all", "2nd")]["won"], 0)          # the prop leg is in the best combo and loses
        self.assertEqual(out[("no prop", "2nd")]["won"], 1)
        self.assertEqual(out[("no prop", "2nd")]["n"], 1)


if __name__ == "__main__":
    unittest.main()
