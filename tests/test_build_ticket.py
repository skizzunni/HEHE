import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import build_ticket as B  # noqa: E402


def row(team, mc, gid="nba:1", price="-400"):
    return dict(mp=team, mc=mc, id=gid, p=price, abbr=team[:3].upper(), match="A @ B")


class JudgeWinnerTest(unittest.TestCase):
    def test_nov23_mistakes_are_left_off(self):
        # Thunder: 63%
        self.assertFalse(B.judge_winner(row("Thunder", 63), [], 0.6)[0])
        # Raptors: key players out -- a caution, not a cut (priced in on the record)
        ok, why = B.judge_winner(row("Raptors", 79), [("Kawhi Leonard", 33.0, "Out")], 0.75)
        self.assertTrue(ok)
        self.assertIn("caution: Kawhi Leonard (Out)", why)
        # Cavaliers-like: our number on the other side
        ok, why = B.judge_winner(row("Cavaliers", 76), [], 0.38)
        self.assertFalse(ok)
        self.assertIn("other side", why)
        self.assertIn("Star (Questionable)", B.judge_winner(row("X", 80), [("Star", 34.0, "Questionable")], 0.7)[1])
        # clean favourite passes
        self.assertEqual(B.judge_winner(row("Lakers", 85), [], 0.72), (True, ""))
        self.assertTrue(B.judge_winner(row("Lakers", 85), [], None)[0])


class BuildTest(unittest.TestCase):
    def test_layout_left_off_and_props(self):
        rows = {"nba": [row("Lakers", 85, "nba:1"), row("Raptors", 79, "nba:2")]}
        props = [{"id": "nba:1", "match": "UTAH @ LAL", "props": [
            dict(name="Good Player", label="Good Player: 10+ Points", p=0.87, imp=0.9, price="-900", market="Points", line="10+"),
            dict(name="Hurt Player", label="Hurt Player: 5+ Points", p=0.87, imp=0.95, price="-1900", market="Points", line="5+")]}]
        t = B.build(rows, props,
                    key_out_fn=lambda r: [("Kawhi Leonard", 33.0, "Out")] if r["mp"] == "Raptors" else [],
                    blind_fn=lambda r: 0.7,
                    status_fn=lambda n: "Questionable" if n == "Hurt Player" else None,
                    fav_fn=lambda gid: 85)
        legs = [L for g in t["games"].values() for L in g]
        self.assertEqual([L["kind"] for L in legs], ["ml", "ml", "prop"])
        self.assertIn("caution: Kawhi Leonard (Out)", legs[1]["label"])
        self.assertEqual(legs[2]["stat"], "PTS")
        self.assertEqual(legs[2]["line"], 10.0)
        self.assertIn("blowout", legs[2]["label"])
        reasons = dict(t["left_off"])
        self.assertTrue(any("Questionable" in v for v in reasons.values()))
        out = B.text(t)
        self.assertIn("3 legs", out)
        self.assertIn("Left off, and why:", out)


    def test_prop_locks_go_first_and_are_labelled(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name=f"P{i}", label=f"P{i}: 5+ Points", p=0.87, imp=0.9 - i / 100, price="-900", market="Points", line="5+")
            for i in range(5)]}]
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda gid: 0, prop_locks={"P4"})
        legs = [L for g in t["games"].values() for L in g]
        self.assertEqual(legs[0]["player"], "P4")
        self.assertIn("Prop Lock", legs[0]["label"])
        self.assertEqual(len(legs), B.PER_GAME)
        self.assertNotIn("Prop Lock", legs[1]["label"])


class BoardSlotTest(unittest.TestCase):
    def test_slot_by_date_and_stale(self):
        D = {"dates": {"today": "20261123", "tomorrow": "20261124"}}
        self.assertEqual(B.board_slot(D, "2026-11-23"), "today")
        self.assertEqual(B.board_slot(D, "2026-11-24"), "tomorrow")
        with self.assertRaises(B.StaleBoard):
            B.board_slot(D, "2026-11-25")


class FallbackTest(unittest.TestCase):
    def test_winners_from_prices(self):
        rows = [dict(lg="nba", game="DAL @ DEN", id="9", home="DEN", away="DAL", home_ml=-322, away_ml=260,
                     market_home=0.73, blind_home=0.59),
                dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453,
                     market_home=0.21, blind_home=0.28),
                dict(lg="nhl", game="X @ Y", id="7", home="Y", away="X", home_ml=-400, away_ml=300,
                     market_home=0.78, blind_home=0.40)]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda rows: [])
        legs = [L for g in t["games"].values() for L in g]
        self.assertEqual([(L["team"], L["price"]) for L in legs], [("BOS", "-453")])
        reasons = dict(t["left_off"])
        self.assertTrue(any("under 75%" in v for v in reasons.values()))         # Denver 73%
        self.assertTrue(any("other side" in v for v in reasons.values()))       # Y: our number 40%
        self.assertIn("NOTE: The board has not rebuilt", B.text(t))


class BackToBackTest(unittest.TestCase):
    def test_caution_on_board_and_fallback_legs(self):
        t = B.build({"nba": [row("Celtics", 80, "nba:1")]}, [], key_out_fn=lambda r: [], blind_fn=lambda r: 0.7,
                    status_fn=lambda n: None, fav_fn=lambda g: 0, b2b_fn=lambda r: True)
        legs = [L for g in t["games"].values() for L in g]
        self.assertIn("back-to-back", legs[0]["label"])
        rows = [dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453,
                     market_home=0.21, blind_home=0.28)]
        f = B.fallback("2026-11-24", rows, b2b_fn=lambda team, day: team == "BOS", props_fn=lambda rows: [])
        self.assertIn("back-to-back", [L for g in f["games"].values() for L in g][0]["label"])


class FallbackPropsTest(unittest.TestCase):
    def test_fanduel_props_join_the_ticket(self):
        rows = [dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=500, away_ml=-700,
                     market_home=0.15, blind_home=0.28)]
        pg = [{"id": "nba:8", "match": "BOS @ WSH", "props": [
            dict(name="Jaylen Brown", label="Jaylen Brown: 15+ Points", p=0.87, imp=0.9, price="-900", market="Points", line="15+"),
            dict(name="Hurt Guy", label="Hurt Guy: 5+ Points", p=0.87, imp=0.95, price="-2000", market="Points", line="5+")]}]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda r: pg,
                       status_fn=lambda n: "Out" if n == "Hurt Guy" else None, minutes_fn=lambda g, n: {})
        legs = t["games"]["BOS @ WSH"]
        self.assertEqual([L["kind"] for L in legs], ["ml", "prop"])
        self.assertEqual(legs[1]["player"], "Jaylen Brown")
        self.assertIn("big favourite", legs[1]["label"])          # 85% favourite: blowout flag
        self.assertTrue(any("Out on the official injury report" in why for _, why in t["left_off"]))

    def test_fanduel_down_still_gives_winners(self):
        def boom(rows):
            raise OSError("down")
        rows = [dict(lg="nba", game="BOS @ WSH", id="8", home="WSH", away="BOS", home_ml=351, away_ml=-453,
                     market_home=0.21, blind_home=0.28)]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=boom)
        self.assertIn("no props (FanDuel unreachable)", t["note"])
        self.assertEqual(len(t["games"]["BOS @ WSH"]), 1)


class MinutesCautionTest(unittest.TestCase):
    def test_low_minutes_props_carry_the_card_caution(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name="Bench Guy", label="Bench Guy: 4+ Rebounds", p=0.87, imp=0.9, price="-1200", market="Rebounds", line="4+"),
            dict(name="Starter", label="Starter: 15+ Points", p=0.87, imp=0.9, price="-1000", market="Points", line="15+")]}]
        seen = []
        def mins(gid, names):
            seen.append((gid, names))
            return {"Bench Guy": 14.2, "Starter": 33.0}
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda g: 0, minutes_fn=mins)
        legs = {L["player"]: L["label"] for L in t["games"]["A @ B"]}
        self.assertIn("caution: 14.2 min a game over his last 5", legs["Bench Guy"])
        self.assertNotIn("caution", legs["Starter"])
        self.assertEqual(seen, [("nba:1", ["Bench Guy", "Starter"])])     # one lookup per game
        self.assertEqual(len(t["games"]["A @ B"]), 2)                      # a caution, not a cut

    def test_minutes_failure_leaves_ticket_alone(self):
        props = [{"id": "nba:1", "match": "A @ B", "props": [
            dict(name="X", label="X: 4+ Rebounds", p=0.87, imp=0.9, price="-1200", market="Rebounds", line="4+")]}]
        def boom(g, n):
            raise OSError("down")
        t = B.build({}, props, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=lambda n: None,
                    fav_fn=lambda g: 0, minutes_fn=boom)
        self.assertEqual(t["games"]["A @ B"][0]["label"], "X: 4+ Rebounds -1200 (87%)")


class LadderFallbackTest(unittest.TestCase):
    def test_one_leg_per_game_in_band(self):
        t = {"games": {f"G{i}": [dict(label=f"leg{i}", price="-400", chance=0.80, lg="nba", id=str(i), gid=f"nba:{i}"),
                                  dict(label=f"leg{i}b", price="-400", chance=0.79, lg="nba", id=str(i), gid=f"nba:{i}")]
                       for i in range(8)}, "left_off": []}
        combo = B.ladder_fallback(t)
        self.assertTrue(combo)
        self.assertEqual(len({L["gid"] for L in combo}), len(combo))      # one per game
        pays = 1
        for L in combo:
            pays *= B._dec(L["price"])
        self.assertTrue(2.0 <= pays <= 5.0)
        self.assertIn("Ladder stand-in", B.ladder_text(combo))
        self.assertIn("nothing", B.ladder_text([]))


class SaveThenGradeTest(unittest.TestCase):
    def test_saved_ticket_grades(self):
        import grade_picks as G
        rows = [dict(lg="nhl", game="VGK @ EDM", id="5", home="EDM", away="VGK", home_ml=-500, away_ml=380,
                     market_home=0.82, blind_home=0.7)]
        pg = [{"id": "nhl:5", "match": "VGK @ EDM", "props": [
            dict(name="Matt Boldy", label="Matt Boldy: 2+ Shots on Goal", p=0.87, imp=0.9, price="-900",
                 market="Shots on Goal", line="2+")]}]
        t = B.fallback("2026-11-24", rows, b2b_fn=lambda *a: False, props_fn=lambda r: pg, status_fn=lambda n: None)
        legs = B.ticket_legs(t)
        self.assertEqual([L["kind"] for L in legs], ["ml", "prop"])
        self.assertTrue(all("chance" not in L and "gid" not in L for L in legs))
        box = {"header": {"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
                   {"team": {"abbreviation": "EDM"}, "score": "4"}, {"team": {"abbreviation": "VGK"}, "score": "2"}]}]},
               "boxscore": {"players": [{"team": {"abbreviation": "EDM"}, "statistics": [
                   {"name": "forwards", "keys": ["shotsTotal"], "labels": ["S"],
                    "athletes": [{"athlete": {"id": "9", "displayName": "Matt Boldy"}, "stats": ["3"]}]}]}]}}
        got = [G.grade(L, {"EDM": 4.0, "VGK": 2.0}, True, box) for L in legs]
        self.assertEqual(got, ["won", "won"])


if __name__ == "__main__":
    unittest.main()
