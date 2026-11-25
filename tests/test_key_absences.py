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


class StatusOfTest(unittest.TestCase):
    def test_nicknames(self):
        st = {"Johnson, Cameron": "Questionable", "Lively II, Dereck": "Out", "Jones, Isaac": "Out", "Jones, Tre": "Probable"}
        self.assertEqual(K.status_of("Cam Johnson", st), "Questionable")
        self.assertEqual(K.status_of("Dereck Lively II", st), "Out")
        self.assertEqual(K.status_of("Luka Doncic", {"Dončić, Luka": "Out"}), "Out")          # accents
        # suffixes: the report's 'Butler III, Jimmy' (Out) must meet FanDuel's 'Jimmy Butler'
        self.assertEqual(K.status_of("Jimmy Butler", {"Butler III, Jimmy": "Out"}), "Out")
        self.assertEqual(K.status_of("Jabari Smith", {"Smith Jr., Jabari": "Questionable"}), "Questionable")
        self.assertEqual(K.status_of("Jaren Jackson Jr.", {"Jackson Jr., Jaren": "Out"}), "Out")
        self.assertIsNone(K.status_of("Jalen Williams", {"Williams, Jaylin": "Out"}))
        self.assertEqual(K.status_of("Luka Dončić", {"Doncic, Luka": "Questionable"}), "Questionable")
        self.assertEqual(K.status_of("Tre Jones", st), "Probable")
        self.assertIsNone(K.status_of("Tyus Jones", st))
        self.assertIsNone(K.status_of("Nobody", st))
        self.assertIsNone(K.status_of("I Jones", {"Jones, Isaac": "Out", "Jones, Ian": "Out"}))   # ambiguous


class LastNightCountsTest(unittest.TestCase):
    def test_last_nights_game_is_before_today(self):
        # a 7 PM ET Nov 23 game is 2026-11-24T00:00Z: it is before Nov 24 in ET
        sched = {"events": [{"id": "9", "date": "2026-11-24T00:00Z",
                             "competitions": [{"status": {"type": {"completed": True}}}]}]}
        box = {"boxscore": {"players": [{"team": {"abbreviation": "BOS"}, "statistics": [
            {"labels": ["MIN"], "athletes": [{"athlete": {"displayName": "A B"}, "stats": ["33"]}]}]}]}}
        pages = {K.SCHED.format("bos"): sched, K.SUMMARY.format("9"): box}
        old_min = K.MIN_PLAYED
        try:
            K.MIN_PLAYED = 1
            self.assertEqual(K.recent_minutes("BOS", "2026-11-24", get=pages.get), {"A B": 33.0})
        finally:
            K.MIN_PLAYED = old_min
        self.assertEqual(K._et_day("2026-11-24T00:00Z"), "2026-11-23")
        self.assertEqual(K._et_day("2026-11-24"), "2026-11-24")


class BackToBackDayTest(unittest.TestCase):
    def test_played_day_before_in_et(self):
        pages = {K.SCHED.format("bos"): {"events": [{"date": "2026-11-24T03:30Z"}, {"date": "2026-11-25T00:00Z"}]}}
        # 03:30Z on Nov 24 is 10:30 PM ET on Nov 23 -- the night before Nov 24
        self.assertTrue(K.played_day_before("BOS", "2026-11-24", get=pages.get))
        self.assertFalse(K.played_day_before("BOS", "2026-11-26", get=pages.get))


class TeamNameGuardTest(unittest.TestCase):
    def test_report_team_names_are_espn_display_names(self):
        """main() joins the report to ESPN by team display name; a name that
        differs would read 'no key player out' in silence (all 30 matched on
        2026-11-25). The report's spellings the parser knows must stay ESPN's."""
        import nba_injury_report as R
        names = getattr(R, "TEAMS", None)
        if not names:
            self.skipTest("parser keeps no team list")
        espn = set(['Atlanta Hawks', 'Boston Celtics', 'Brooklyn Nets', 'Charlotte Hornets', 'Chicago Bulls', 'Cleveland Cavaliers', 'Dallas Mavericks', 'Denver Nuggets', 'Detroit Pistons', 'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers', 'LA Clippers', 'Los Angeles Lakers', 'Memphis Grizzlies', 'Miami Heat', 'Milwaukee Bucks', 'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks', 'Oklahoma City Thunder', 'Orlando Magic', 'Philadelphia 76ers', 'Phoenix Suns', 'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Toronto Raptors', 'Utah Jazz', 'Washington Wizards'])  # ESPN team displayName, 2026-11-25
        self.assertEqual(sorted(set(names) - espn), [])


if __name__ == "__main__":
    unittest.main()
