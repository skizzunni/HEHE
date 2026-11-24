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
        pages = {K.SCHED.format("tor"): {"events": [ev(i) for i in range(1, 6)] + [ev(6, done=False)]}}
        # A B plays every game at 30; Hurt Guy plays 3 of 5 at 34 then sits (0) -- per game played he is 34, key
        for i in range(1, 6):
            hurt = "34" if i <= 3 else "0"
            pages[K.SUMMARY.format(str(i))] = {"boxscore": {"players": [{"team": {"abbreviation": "TOR"}, "statistics": [
                {"labels": ["MIN"], "athletes": [{"athlete": {"displayName": "A B"}, "stats": ["30"]},
                                                  {"athlete": {"displayName": "Hurt Guy"}, "stats": [hurt]},
                                                  {"athlete": {"displayName": "Cameo"}, "stats": ["40" if i == 1 else "0"]}]}]}]}}
        got = K.recent_minutes("TOR", "2026-11-24", get=pages.get)
        self.assertEqual(got, {"A B": 30.0, "Hurt Guy": 34.0})        # Cameo played 1 game: not counted


class BackToBackDayTest(unittest.TestCase):
    def test_played_day_before_in_et(self):
        pages = {K.SCHED.format("bos"): {"events": [{"date": "2026-11-24T03:30Z"}, {"date": "2026-11-25T00:00Z"}]}}
        # 03:30Z on Nov 24 is 10:30 PM ET on Nov 23 -- the night before Nov 24
        self.assertTrue(K.played_day_before("BOS", "2026-11-24", get=pages.get))
        self.assertFalse(K.played_day_before("BOS", "2026-11-26", get=pages.get))


if __name__ == "__main__":
    unittest.main()
