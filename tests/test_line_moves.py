import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import line_moves as lm                                           # noqa: E402

PAGE = ('<script>\nconst D = {"at": "Nov 14", "slots": {"today": {"ufc": {"rows": ['
        '{"id": "1", "mp": "A", "mc": 60, "t": "9 PM"}, {"id": "2", "mp": "B", "mc": 70, "t": "9 PM"}]}}}};\n</script>')


class LineMoves(unittest.TestCase):
    def test_rows(self):
        D = lm.board("x", fetch=lambda u: PAGE)
        self.assertEqual(lm.rows(D, "ufc"), {"1": dict(pick="A", chance=60, time="9 PM"), "2": dict(pick="B", chance=70, time="9 PM")})

    def test_compare(self):
        before = {"1": dict(pick="A", chance=60), "2": dict(pick="B", chance=70), "3": dict(pick="C", chance=55),
                  "4": dict(pick="D", chance=58)}
        after = {"1": dict(pick="A", chance=56), "2": dict(pick="B", chance=71), "4": dict(pick="E", chance=52),
                 "5": dict(pick="F", chance=66)}
        self.assertEqual(lm.compare(before, after), [
            "DOWN A 60% -> 56% (-4): money moving to the other side",
            "GONE C (55%) -- no longer on the board (scratched or started)",
            "SIDE CHANGED D (58%) -> E (52%)", "NEW F (66%)"])
        self.assertEqual(lm.compare(before, before), [])


if __name__ == "__main__":
    unittest.main()
