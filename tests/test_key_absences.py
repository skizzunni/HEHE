import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import key_absences as K  # noqa: E402


class NameTest(unittest.TestCase):
    def test_report_order(self):
        self.assertEqual(K.report_name("Kawhi Leonard"), "Leonard, Kawhi")
        self.assertEqual(K.report_name("Jaren Jackson Jr."), "Jackson Jr., Jaren")
        self.assertEqual(K.report_name("Trey Murphy III"), "Murphy III, Trey")


class KeyMissingTest(unittest.TestCase):
    def test_top_minutes_only(self):
        mins = {"Kawhi Leonard": 34.0, "RJ Barrett": 33.0, "Scottie Barnes": 35.0, "Bench Guy": 8.0}
        st = {"Leonard, Kawhi": "Out", "Barrett, RJ": "Out", "Guy, Bench": "Out"}
        got = K.key_missing(mins, st, n=3)
        self.assertEqual([g[0] for g in got], ["Kawhi Leonard", "RJ Barrett"])
        self.assertEqual(K.key_missing(mins, {"Barnes, Scottie": "Questionable"}, n=3), [("Scottie Barnes", 35.0, "Questionable")])
        self.assertEqual(K.key_missing(mins, {"Barnes, Scottie": "Probable"}, n=3), [])


class RecentMinutesTest(unittest.TestCase):
    def test_average_over_completed_games(self):
        def ev(i, done=True, date="2026-11-2%d"):
            return {"id": str(i), "date": (date % i), "competitions": [{"status": {"type": {"completed": done}}}]}
        pages = {K.SCHED.format("tor"): {"events": [ev(1), ev(2), ev(3, done=False)]}}
        for i, m in ((1, "30"), (2, "20")):
            pages[K.SUMMARY.format(str(i))] = {"boxscore": {"players": [{"team": {"abbreviation": "TOR"}, "statistics": [
                {"labels": ["MIN"], "athletes": [{"athlete": {"displayName": "A B"}, "stats": [m]}]}]}]}}
        self.assertEqual(K.recent_minutes("TOR", "2026-11-24", get=pages.get), {"A B": 25.0})


if __name__ == "__main__":
    unittest.main()
