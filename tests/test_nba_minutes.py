import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import nba_minutes as M  # noqa: E402
import daily_card  # noqa: E402


def gamelog(mins_by_date):
    ev = {f"e{i}": {"gameDate": d} for i, (d, _) in enumerate(mins_by_date)}
    rows = [{"eventId": f"e{i}", "stats": [str(m), "1-2"]} for i, (_, m) in enumerate(mins_by_date)]
    return {"labels": ["MIN", "FG"], "events": ev,
            "seasonTypes": [{"displayName": "2026-27 Regular Season", "categories": [{"events": rows}]}]}


class NameKeyTest(unittest.TestCase):
    def test_fanduel_and_espn_names_meet(self):
        self.assertEqual(M.name_key("Jabari Smith Jr."), M.name_key("Jabari Smith"))
        self.assertEqual(M.name_key("Luka Dončić"), M.name_key("Luka Doncic"))
        self.assertEqual(M.name_key("Gary Payton II"), M.name_key("Gary Payton"))
        self.assertEqual(M.name_key("De'Aaron Fox"), M.name_key("De'Aaron Fox"))
        self.assertNotEqual(M.name_key("Jalen Williams"), M.name_key("Jaylin Williams"))

    def test_roster_lookup_uses_it(self):
        rosters = {"1": {"athletes": [{"displayName": "Jabari Smith Jr.", "id": "77"}]}, "2": {"athletes": []}}
        comps = [{"team": {"id": "1"}}, {"team": {"id": "2"}}]
        get = lambda u: rosters["1"] if "/teams/1/" in u else rosters["2"]
        self.assertEqual(M._ids(get, comps, ["Jabari Smith"]), {"Jabari Smith": "77"})


class Last5Test(unittest.TestCase):
    def test_newest_five_played_games(self):
        g = gamelog([("2026-11-0%d" % d, m) for d, m in ((1, 40), (2, 10), (3, 0), (4, 12), (5, 14), (6, 16), (7, 18))])
        self.assertEqual(M.last5(g), round((10 + 12 + 14 + 16 + 18) / 5, 1))   # skips the 0, drops the oldest
        self.assertIsNone(M.last5({}))
        self.assertIsNone(M.last5(gamelog([("2026-11-01", 0)])))

    def test_mpg_lookup_by_roster_name(self):
        pages = {
            M.SUMMARY.format("9"): {"header": {"competitions": [{"competitors": [{"team": {"id": "1"}}, {"team": {"id": "2"}}]}]}},
            M.ROSTER.format("1"): {"athletes": [{"id": "11", "displayName": "Bench Guy"}]},
            M.ROSTER.format("2"): {"athletes": [{"id": "22", "displayName": "Star Player"}]},
            M.GAMELOG.format("11"): gamelog([("2026-11-0%d" % d, 12) for d in range(1, 6)]),
            M.GAMELOG.format("22"): gamelog([("2026-11-0%d" % d, 36) for d in range(1, 6)]),
        }
        out = M.mpg_last5("nba:9", ["Bench Guy", "Star Player", "Not Listed"], get=pages.get)
        self.assertEqual(out, {"Bench Guy": 12.0, "Star Player": 36.0})


class CardCautionTest(unittest.TestCase):
    def test_low_minutes_flagged_only_for_nba(self):
        D = {"props": {"today": {"games": [
            {"id": "nba:9", "match": "A @ B", "props": [
                dict(name="Bench Guy", label="Bench Guy: 5+ Points", p=0.87, price="-900", gid="nba:9", market="Points", line="5+"),
                dict(name="Star Player", label="Star Player: 20+ Points", p=0.86, price="-700", gid="nba:9", market="Points", line="20+")]},
        ]}}}
        lines = daily_card.prop_lines(D, minutes_fn=lambda gid, names: {"Bench Guy": 12.0, "Star Player": 36.0})
        bench = [l for l in lines if "Bench Guy" in l][0]
        star = [l for l in lines if "Star Player" in l][0]
        self.assertIn("12 min a game over his last 5", bench)
        self.assertNotIn("min a game", star)
        plain = daily_card.prop_lines(D)
        self.assertFalse(any("min a game" in l for l in plain))

    def test_lookup_failure_is_silent(self):
        D = {"props": {"today": {"games": [{"id": "nba:9", "match": "A @ B", "props": [
            dict(name="X", label="X: 5+ Points", p=0.87, price="-900", gid="nba:9", market="Points", line="5+")]}]}}}

        def boom(gid, names):
            raise RuntimeError("offline")
        self.assertTrue(any("X: 5+ Points" in l for l in daily_card.prop_lines(D, minutes_fn=boom)))


class LadderCautionTest(unittest.TestCase):
    def R(self, leg):
        return {"runs": 3, "today": {"stake": 1.0, "pays": 2.0, "prob": 0.5,
                                     "legs": [dict(dict(label="Bench Guy: 5+ Points", price="-500", p=0.83, match="A @ B",
                                                        lg="NBA", tip="7:00 PM", league="nba", kind="prop",
                                                        name="Bench Guy", gid="nba:9"), **leg)]}}

    def test_nba_prop_leg_flagged(self):
        import ladder_ticket
        out = ladder_ticket.lines(self.R({}), minutes_fn=lambda gid, names: {"Bench Guy": 14.2})
        self.assertIn("Caution: 14.2 min a game over his last 5", out[1])

    def test_other_legs_untouched(self):
        import ladder_ticket
        fn = lambda gid, names: {"Bench Guy": 14.2}
        self.assertNotIn("Caution", ladder_ticket.lines(self.R(dict(league="nfl")), minutes_fn=fn)[1])
        self.assertNotIn("Caution", ladder_ticket.lines(self.R(dict(kind="total")), minutes_fn=fn)[1])
        self.assertNotIn("Caution", ladder_ticket.lines(self.R({}))[1])
        self.assertNotIn("Caution", ladder_ticket.lines(self.R({}), minutes_fn=lambda g, n: {"Bench Guy": 31.0})[1])


if __name__ == "__main__":
    unittest.main()
