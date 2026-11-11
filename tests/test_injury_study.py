import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import injury_study as s                                          # noqa: E402


class InjuryStudy(unittest.TestCase):
    def test_rows_and_table(self):
        led = {"a": dict(league="nba", status="won", date="2026-11-05", tip="7:00 PM", pick="A", conf=70,
                         scores={"A": 100, "B": 90}),
               "b": dict(league="nba", status="lost", date="2026-11-06", tip="7:00 PM", pick="A", conf=60,
                         scores={"A": 80, "B": 90}),
               "c": dict(league="mlb", status="won", date="2026-11-05", tip="7:00 PM", pick="A", scores={"A": 1, "B": 0}),
               "d": dict(league="nba", status="won", date="2026-11-01", tip="7:00 PM", pick="A", scores={"A": 1, "B": 0})}
        reports = {"2026-11-05": {"B": [["x", "Out"], ["y", "Out"]]}, "2026-11-06": {"A": [["z", "Out"]], "B": [["w", "Day-To-Day"]]}}
        R = s.rows(led, {"2026-11-05", "2026-11-06"}, before=lambda day, iso, lg: reports.get(day, {}))
        self.assertEqual(sorted((r["date"], r["mine"], r["theirs"], r["won"]) for r in R),
                         [("2026-11-05", 0, 2, True), ("2026-11-06", 1, 0, False)])
        T = s.table(R)
        self.assertIn("2nd 0/1 0% vs 60%", T[0])                    # my side more out
        self.assertIn("1st 1/1 100% vs 70%", T[2])                  # their side more out


if __name__ == "__main__":
    unittest.main()
