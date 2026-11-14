import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ufc_card_research as u                                     # noqa: E402

PROFILE = {"athlete": {"displayName": "A Fighter", "age": 30, "displayReach": "74\"",
                       "statsSummary": {"statistics": [{"name": "wins-losses-draws", "displayValue": "10-2-0"},
                                                       {"name": "tkos-tkoLosses", "displayValue": "6-1"},
                                                       {"name": "submissions-submissionLosses", "displayValue": "2-0"}]}},
           "eventsMap": {"x": {"gameDate": "2026-09-14T00:00Z", "gameResult": "W"},
                         "y": {"gameDate": "2026-03-01T00:00Z", "gameResult": "L"}}}
STATS = {"categories": [
    {"labels": ["SSL", "SSA", "KD"], "statistics": [{"eventId": "1", "stats": ["40", "80", "1"]},
                                                    {"eventId": "2", "stats": ["20", "40", "0"]}]},
    {"labels": ["TDL", "TDA"], "statistics": [{"eventId": "1", "stats": ["2", "4"]}, {"eventId": "2", "stats": ["0", "2"]}]}]}


class Research(unittest.TestCase):
    def test_summarize(self):
        s = u.summarize(PROFILE, STATS, today=dt.date(2026, 11, 14))
        self.assertEqual((s["rec"], s["ko"], s["sub"], s["n"]), ("10-2-0", "6-1", "2-0", 2))
        self.assertEqual((s["ssl"], s["acc"], s["td"], s["tda"], s["kd"], s["days_off"]), (30.0, 50.0, 1.0, 3.0, 1.0, 61))
        self.assertIn("30 sig strikes/fight at 50%, takedowns 1.0/3.0, knockdowns 1 | 61 days since last fight", u.line(s))

    def test_card(self):
        sb = {"events": [{"competitions": [{"type": {"abbreviation": "Heavyweight"}, "competitors": [
            {"id": "1", "athlete": {"displayName": "X"}}, {"id": "2", "athlete": {"displayName": "Y"}}]}]}]}
        self.assertEqual(u.card("20261114", fetch=lambda url: sb), [("X", "1", "Y", "2", "Heavyweight")])


class BoardPick(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(u.board_pick("Josh Hokit", "Ciryl Gane", {"Ciryl Gane": 67}), ("Ciryl Gane", 67))
        self.assertIsNone(u.board_pick("A", "B", {"C": 60}))


class Flags(unittest.TestCase):
    def test_flags(self):
        me = dict(days_off=487, results=["L", "L", "L", "W", "L"], age=43, reach='72"')
        opp = dict(results=["W", "W", "W", "W", "L"], reach='76"')
        self.assertEqual(u.flags(me, opp), ["487 days since last fight", "lost last fight", "lost 4 of last 5", "age 43",
                                             "opponent on 4-fight win streak", 'gives up 4" of reach'])
        self.assertEqual(u.flags(dict(days_off=60, results=["W", "W"], age=30, reach='75"'), dict(results=["L"], reach='74"')), [])

    def test_results_newest_first(self):
        s = u.summarize(PROFILE, STATS, today=dt.date(2026, 11, 14))
        self.assertEqual(s["results"], ["W", "L"])


if __name__ == "__main__":
    unittest.main()
