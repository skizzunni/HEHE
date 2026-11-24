import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import nba_injury_report as R  # noqa: E402

# the layout pdftotext -layout gives the official report (2026-11-23 1:30 PM, trimmed)
TEXT = """                                          Injury Report: 11/23/26 01:30 PM

Game Date    Game Time    Matchup   Team                           Player Name          Current Status   Reason

11/23/2026   07:00 (ET)   MEM@CHA   Memphis Grizzlies              Boozer, Cameron      Out              Injury/Illness - Right Ankle Sprain

                                                                   Grant, Jerami        Out              Injury/Illness - Left Calf Strain
                                                                                                         Injury/Illness - Left 5th Metatarsal
                                                                   Jackson, GG          Out
                                                                                                         Fracture
                                    Charlotte Hornets              Miller, Brandon      Probable
                          POR@PHI   Philadelphia 76ers             Embiid, Joel        Questionable   Injury/Illness - Illness
08:00 (ET)   OKC@IND   Indiana Pacers              Murphy III, Trey      Available
                          UTA@LAL   Utah Jazz                                                      NOT YET SUBMITTED
                                    Los Angeles Lakers         Reaves, Austin       Out
11/24/2026   07:00 (ET)   DET@ORL   Detroit Pistons                                                NOT YET SUBMITTED
"""


class ParseTest(unittest.TestCase):
    def test_rows_and_missing(self):
        r = R.parse(TEXT)
        self.assertEqual(r["asof"], "11/23/26 01:30 PM")
        got = {(x["team"], x["player"], x["status"]) for x in r["rows"]}
        for want in [("Memphis Grizzlies", "Boozer, Cameron", "Out"), ("Memphis Grizzlies", "Jackson, GG", "Out"),
                     ("Charlotte Hornets", "Miller, Brandon", "Probable"), ("Philadelphia 76ers", "Embiid, Joel", "Questionable"),
                     ("Indiana Pacers", "Murphy III, Trey", "Available"), ("Los Angeles Lakers", "Reaves, Austin", "Out")]:
            self.assertIn(want, got)
        reaves = [x for x in r["rows"] if x["player"] == "Reaves, Austin"][0]
        self.assertEqual((reaves["date"], reaves["matchup"]), ("11/23/2026", "UTA@LAL"))
        self.assertIn(("11/23/2026", "UTA@LAL", "Utah Jazz"), r["not_submitted"])
        self.assertIn(("11/24/2026", "DET@ORL", "Detroit Pistons"), r["not_submitted"])


class LatestTest(unittest.TestCase):
    def test_walks_back_to_newest_posted(self):
        asked = []

        def get(u):
            asked.append(u)
            return b"%PDF-fake" if u.endswith("01_30PM.pdf") else None
        keep, R._pdf_text = R._pdf_text, (lambda raw: "text")
        try:
            now = dt.datetime(2026, 11, 23, 14, 7, tzinfo=R.ET)
            u, t = R.latest(now=now, get=get)
        finally:
            R._pdf_text = keep
        self.assertTrue(u.endswith("Injury-Report_2026-11-23_01_30PM.pdf"))
        self.assertTrue(asked[0].endswith("02_00PM.pdf"))
        self.assertEqual(len(asked), 3)


class RealReportTest(unittest.TestCase):
    """The official 2026-11-23 6:30 PM report, as pdftotext -layout gives it."""
    def test_every_status_parsed_and_teams_right(self):
        import collections
        import re
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "nba_injury_2026-11-23_0630PM.txt")
        text = open(path).read()
        r = R.parse(text)
        statuses = sum(len(re.findall(r"\b(Out|Doubtful|Questionable|Probable|Available)\b", l)) for l in text.splitlines())
        self.assertEqual(len(r["rows"]), statuses)
        self.assertEqual(len(r["rows"]), 124)
        teams = collections.defaultdict(set)
        for x in r["rows"]:
            teams[(x["date"], x["matchup"])].add(x["team"])
        self.assertTrue(all(len(v) <= 2 and None not in v for v in teams.values()))
        got = {(x["player"], x["team"], x["status"]) for x in r["rows"]}
        self.assertIn(("Mobley, Evan", "Cleveland Cavaliers", "Out"), got)
        self.assertIn(("Embiid, Joel", "Philadelphia 76ers", "Out"), got)
        self.assertFalse(any(x["player"].startswith("Gilgeous-Alexander") for x in r["rows"]))


if __name__ == "__main__":
    unittest.main()
