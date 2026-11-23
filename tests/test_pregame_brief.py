import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import pregame_brief as P  # noqa: E402


class BriefTest(unittest.TestCase):
    def test_sections_in_order_and_failure_isolated(self):
        def boom(day):
            raise RuntimeError("feed down")
        out = P.brief("2026-11-24", sections=(("Numbers", lambda d: "blind first"), ("Injuries", boom),
                                              ("Goalies", lambda d: "goalies " + d)))
        self.assertLess(out.index("## Numbers"), out.index("## Injuries"))
        self.assertIn("blind first", out)
        self.assertIn("unavailable (RuntimeError)", out)
        self.assertIn("goalies 2026-11-24", out)


    def test_save_names_file_by_time(self):
        import datetime as dt
        import tempfile
        d = tempfile.mkdtemp()
        p = P.save("hello", os.path.join(d, "x"), now=dt.datetime(2026, 11, 23, 18, 40, tzinfo=P.ET))
        self.assertTrue(p.endswith("brief_1840.txt"))
        self.assertEqual(open(p).read(), "hello\n")


if __name__ == "__main__":
    unittest.main()
