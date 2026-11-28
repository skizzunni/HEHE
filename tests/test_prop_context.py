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


    def test_early_tag(self):
        games = {"1": {"start": "2026-11-29T18:00Z"}, "2": {"start": "2026-11-29T21:25Z"}}
        rows = C.early_tag([dict(gid="nfl:1"), dict(gid="nfl:2"), dict(gid="nfl:3")], games)
        self.assertEqual([b for _, b in rows], [True, False])          # 1 PM ET early, 4:25 PM not; no start skipped

    def test_weekend_tag(self):
        rows = C.weekend_tag([dict(date="2026-11-28"), dict(date="2026-11-27")])     # Sat, Fri
        self.assertEqual([b for _, b in rows], [True, False])

    def test_nhl_box_position_and_icetime(self):
        def get(u):
            eid = u.rsplit("=", 1)[1]
            toi = {"1": "15:00", "2": "16:00", "3": "17:00", "4": "22:00"}[eid]
            return {"boxscore": {"players": [{"statistics": [{"keys": ["shotsTotal", "timeOnIce"], "athletes": [
                {"athlete": {"displayName": "Steven Stamkos", "position": {"abbreviation": "C"}}, "stats": ["0", toi]},
                {"athlete": {"displayName": "Roman Josi", "position": {"abbreviation": "D"}}, "stats": ["2", "24:30"]},
                {"athlete": {"displayName": "Juuse Saros", "position": {"abbreviation": "G"}}, "stats": ["", "--"]}]}]}]}}
        boxes = {e: C.nhl_box(e, get) for e in "1234"}
        self.assertEqual(boxes["1"]["steven stamkos"], ("C", 15.0))
        self.assertEqual(boxes["1"]["juuse saros"], ("G", None))
        props = [dict(gid=f"nhl:{e}", name=n, date=f"2026-11-0{e}") for e in "1234"
                 for n in ("Steven Stamkos", "Roman Josi", "Juuse Saros")]
        pos = C.position_tag(props, boxes)
        self.assertEqual({(e["name"], d) for e, d in pos}, {("Steven Stamkos", False), ("Roman Josi", True)})
        ice = C.icetime_tag(props, boxes)          # only game 4 has 3 earlier box scores
        self.assertEqual([(e["name"], u) for e, u in ice], [("Steven Stamkos", True), ("Roman Josi", False)])

    def test_nhl_team_box_and_shots_tag(self):
        def get(u):
            eid = int(u.rsplit("=", 1)[1])
            a, b = ("BOS", "TOR") if eid % 2 else ("BOS", "MTL")
            return {"boxscore": {
                "teams": [{"team": {"abbreviation": a}, "statistics": [{"name": "shotsTotal", "displayValue": "30"}]},
                          {"team": {"abbreviation": b}, "statistics": [{"name": "shotsTotal",
                                                                         "displayValue": str(10 + eid)}]}],
                "players": [{"team": {"abbreviation": a}, "statistics": [{"athletes": [
                    {"athlete": {"displayName": "David Pastrnak"}}]}]}]}}
        teams = {str(i): C.nhl_team_box(str(i), get) for i in range(1, 7)}
        self.assertEqual(teams["1"]["shots"], {"BOS": 30.0, "TOR": 11.0})
        self.assertEqual(teams["1"]["players"], {"david pastrnak": "BOS"})
        props = [dict(gid=f"nhl:{i}", name="David Pastrnak", date=f"2026-11-0{i}") for i in range(1, 7)]
        rows = C.shots_tag(props, teams, "team")            # only game 5 and 6 have 4 earlier BOS games
        self.assertEqual([e["gid"] for e, _ in rows], ["nhl:5", "nhl:6"])
        self.assertEqual(C.shots_tag(props, teams, "opp"), [])   # opponents never reach 4 earlier games

    def test_game_total_and_total_tag(self):
        get = lambda u: {"pickcenter": [{"provider": "x"}, {"overUnder": 231.5}]}
        self.assertEqual(C.game_total("nba", "1", get), 231.5)
        self.assertIsNone(C.game_total("nba", "1", lambda u: {}))
        totals = {"1": 220.0, "2": 228.0, "3": 236.0, "4": None}
        props = [dict(gid=f"nba:{i}") for i in "1234"]
        self.assertEqual([b for _, b in C.total_tag(props, totals, "high")], [False, False, True])
        self.assertEqual([b for _, b in C.total_tag(props, totals, "low")], [True, False, False])
        self.assertEqual(C.total_tag(props, {}), [])

    def test_band_halves(self):
        props = [dict(price="-2000", date="2026-11-01", status="won"), dict(price="-2000", date="2026-11-02", status="lost"),
                 dict(price="-1200", date="2026-11-01", status="won"), dict(price="-1200", date="2026-11-03", status="won"),
                 dict(price="+100", date="2026-11-01", status="won")]
        rows = {(b, h): (w, n) for b, h, w, n, ex, z in C.band_halves(props)}
        self.assertEqual(rows[("-1500 or shorter", "first")], (1, 1))
        self.assertEqual(rows[("-1500 or shorter", "second")], (0, 1))
        self.assertEqual(rows[("-1000 to -1499", "second")], (1, 1))
        self.assertNotIn(("-500 to -999", "first"), rows)


if __name__ == "__main__":
    unittest.main()
