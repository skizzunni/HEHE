import datetime as dt
import os
import sys
import unittest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "tools"), os.path.join(os.path.dirname(__file__), "..")]
import prop_context as C  # noqa: E402


def fake_get(u):
    if "scoreboard" in u:
        day = u.rsplit("=", 1)[1]
        teams = {"20261101": ["BOS", "NYK"], "20261102": ["BOS", "MIA"]}.get(day, [])
        return {"events": [{"competitions": [{"competitors": [{"team": {"abbreviation": t}} for t in teams]}]}]}
    return {"boxscore": {"players": [
        {"team": {"abbreviation": "BOS"}, "statistics": [{"athletes": [{"athlete": {"displayName": "Jayson Tatum"}}]}]},
        {"team": {"abbreviation": "MIA"}, "statistics": [{"athletes": [{"athlete": {"displayName": "Bam Adebayo"}}]}]}]}}


class PropContextTest(unittest.TestCase):
    def test_schedule_team_map_and_tag(self):
        sched = C.schedule("nba", dt.date(2026, 11, 1), dt.date(2026, 11, 2), fake_get)
        self.assertEqual(sched["BOS"], {"2026-11-01", "2026-11-02"})
        self.assertEqual(C.team_map("nba", "9", fake_get), {"jayson tatum": "BOS", "bam adebayo": "MIA"})
        props = [dict(gid="nba:9", name="Jayson Tatum", date="2026-11-02", status="won", imp=0.9),
                 dict(gid="nba:9", name="Bam Adebayo", date="2026-11-02", status="lost", imp=0.9),
                 dict(gid="nba:9", name="Nobody", date="2026-11-02", status="won", imp=0.9)]
        rows = C.tag(props, {"9": C.team_map("nba", "9", fake_get)}, sched)
        self.assertEqual([(e["name"], b) for e, b in rows], [("Jayson Tatum", True), ("Bam Adebayo", False)])

    def test_compare_by_half(self):
        mk = lambda d, st, b: (dict(date=d, status=st, imp=0.8), b)
        rows = [mk("2026-11-01", "won", True), mk("2026-11-01", "lost", False),
                mk("2026-11-03", "won", True), mk("2026-11-03", "won", False)]
        out = C.compare(rows)
        self.assertEqual(len(out), 2)
        (a, r, z) = out[0]
        self.assertEqual((a[0], a[1], r[0], r[1]), (1, 1, 0, 1))
        self.assertGreater(z, 0)
        self.assertEqual(C.compare(rows[:2]), [])          # one date: no halves

    def test_chance_tag(self):
        maps = {"9": {"jayson tatum": "BOS", "bam adebayo": "MIA"}}
        games = {"9": {"home": "Boston Celtics", "away": "Miami Heat", "p": {"dk": 0.75}}}
        props = [dict(gid="nba:9", name="Jayson Tatum"), dict(gid="nba:9", name="Bam Adebayo")]
        # one game cannot tell the two names apart; with a second game it can
        maps["8"] = {"jayson tatum": "BOS", "x": "NYK"}
        games["8"] = {"home": "Boston Celtics", "away": "New York Knicks", "p": {"dk": 0.5}}
        maps["7"] = {"bam adebayo": "MIA", "y": "NYK"}
        games["7"] = {"home": "New York Knicks", "away": "Miami Heat", "p": {"dk": 0.5}}
        names = C.abbr_names(maps, games)
        self.assertEqual((names["BOS"], names["MIA"]), ("Boston Celtics", "Miami Heat"))
        rows = C.chance_tag(props, maps, games)
        self.assertEqual([(e["name"], dog) for e, dog in rows], [("Jayson Tatum", False), ("Bam Adebayo", True)])


if __name__ == "__main__":
    unittest.main()
