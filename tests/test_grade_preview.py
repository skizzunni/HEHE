import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import grade_preview as GP  # noqa: E402


class PreviewTest(unittest.TestCase):
    def test_nothing_is_saved(self):
        import ledger
        calls = []
        real = ledger.save
        try:
            ledger.save = lambda d: calls.append(d)

            def fake_grade():
                ledger.save({"x": 1})          # the grader saves at its end
                return [("nba:1", dict(status="lost", pick="Raptors", conf=79, price="-449", matchup="MIL @ TOR",
                                       scores={"TOR": 111, "MIL": 116}, diagnosis="upset · close game"))]
            out = GP.preview(fake_grade)
            self.assertEqual(calls, [])          # patched out during the preview
        finally:
            ledger.save = real
        self.assertEqual(GP.line(*out[0]),
                         "LOST nba Raptors at 79% (-449), MIL @ TOR TOR 111 - MIL 116 -- upset · close game")
        self.assertEqual(GP.summary(out + [("nhl:2", dict(status="won")), ("x:3", dict(status="void"))]),
                         "Would settle 3: 1 won, 1 lost, 1 void (preview only, nothing saved)")


class ReviewLineTest(unittest.TestCase):
    def test_preview_losses_line(self):
        import daily_review
        S = [("nba:1", dict(status="lost", pick="Raptors", conf=79, price="-449", matchup="MIL @ TOR",
                            scores={"TOR": 111, "MIL": 116}, diagnosis="upset")),
             ("nba:2", dict(status="won", pick="Lakers", conf=85, price="-800"))]
        line = daily_review.preview_losses_line(lambda: S)
        self.assertTrue(line.startswith("Not yet graded by the board, from ESPN: Would settle 2: 1 won, 1 lost"))
        self.assertIn("\n- LOST nba Raptors at 79% (-449)", line)
        self.assertIsNone(daily_review.preview_losses_line(lambda: []))


class HeavyPropsLineTest(unittest.TestCase):
    def test_line(self):
        import daily_review
        props = {f"k{i}": dict(price="-3000", p=0.87, status="won" if i % 10 else "lost", date=f"2026-11-{1 + i // 10:02d}")
                 for i in range(60)}
        props["light"] = dict(price="-1000", p=0.85, status="lost", date="2026-11-01")
        line = daily_review.heavy_props_line(props)
        self.assertTrue(line.startswith("Props priced -2500 or shorter, by half: 27/30 (90.0% vs 87.0% stated"))
        self.assertIsNone(daily_review.heavy_props_line({}))


if __name__ == "__main__":
    unittest.main()
