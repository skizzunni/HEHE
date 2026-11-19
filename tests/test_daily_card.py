import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import daily_card                                                      # noqa: E402
import td_scorers                                                      # noqa: E402
import ten_leg                                                         # noqa: E402


class TenLeg(unittest.TestCase):
    def test_american_first_and_open_only(self):
        G = [dict(gid=f"g{i}", label=f"L{i}", price="-400", p=0.9 - i / 100, league="nba", status="open") for i in range(8)]
        G += [dict(gid="s1", label="Soccer", price="-900", p=0.95, league="epl", status="open"),
              dict(gid="s2", label="Soccer2", price="-900", p=0.94, league="ita", status="open"),
              dict(gid="s3", label="Soccer3", price="-900", p=0.93, league="esp", status="open"),
              dict(gid="x", label="Started", price="-900", p=0.99, league="nba", status="won")]
        T = ten_leg.build(G)
        self.assertEqual(T["n"], 10)
        self.assertEqual([g["label"] for g in T["legs"]][:8], [f"L{i}" for i in range(8)])   # every American game first
        self.assertEqual([g["label"] for g in T["legs"]][8:], ["Soccer", "Soccer2"])          # then the likeliest others
        self.assertFalse(T["us_only"])
        self.assertAlmostEqual(T["pays"], round(1.25 ** 8 * (1 + 100 / 900) ** 2, 2), places=2)
        self.assertNotIn("Started", [g["label"] for g in T["legs"]])
        self.assertIsNone(ten_leg.build([]))


class ToTarget(unittest.TestCase):
    def test_adds_safest_until_2x(self):
        G = [dict(gid=f"g{i}", label=f"L{i}", price="-400", p=0.9 - i / 100, league="nba", status="open") for i in range(6)]
        T = ten_leg.to_target(G, 2.0)
        self.assertEqual(T["n"], 4)                       # 1.25 ** 4 = 2.44, three legs only 1.95
        self.assertEqual([g["label"] for g in T["legs"]], ["L0", "L1", "L2", "L3"])
        self.assertIsNone(ten_leg.to_target(G[:2], 2.0))

    def test_review_line(self):
        import daily_review
        lad = {f"2026-11-{d:02d}": d % 3 == 0 for d in range(5, 13)}
        alt = {f"2026-11-{d:02d}": d % 2 == 0 for d in range(5, 14)}
        out = daily_review.ladder_alt_line(lad, alt)
        self.assertTrue(out.startswith("Ladder vs every-game ticket to 2x, same 8 days: ladder "), out)
        self.assertIsNone(daily_review.ladder_alt_line({"2026-11-05": True}, {"2026-11-05": True}))


class Sizes(unittest.TestCase):
    def test_sizes_skips_empty(self):
        import unittest.mock as m
        recs = {6: dict(days=13, cashed=12, pays=1.34), 8: dict(days=0)}
        with m.patch.object(ten_leg, "record", lambda path=None, led=None, n=10: recs.get(n, dict(days=0))):
            self.assertEqual(ten_leg.sizes(led={}, ns=(6, 8)), [dict(n=6, days=13, cashed=12, pays=1.34)])


class TdModel(unittest.TestCase):
    def test_two_plus_and_first(self):
        self.assertAlmostEqual(td_scorers.two_plus(0.6), 0.1219, places=4)
        self.assertAlmostEqual(td_scorers.first_td(0.6, 5.0), 0.6 / 5 * (1 - 2.718281828 ** -5), places=4)
        self.assertEqual(td_scorers.first_td(0.6, 0), 0.0)
        self.assertLess(td_scorers.two_plus(0.6), 1 - 2.718281828 ** -0.6)    # 2+ below anytime


class Card(unittest.TestCase):
    D = {"td": {"today": [{"lg": "NFL", "match": "BUF @ KC", "tip": "8:20 PM", "everyone": [
            dict(name="A", p=0.45, p2=0.12, pfirst=0.11, price="-110")]}]},
         "props": {"today": {"games": [{"id": "nba:1", "match": "X @ Y", "props": [
            dict(name="P1", label="P1: 10+ Points", price="-900", p=0.88, imp=0.9),
            dict(name="P1", label="P1: 5+ Points", price="-3000", p=0.88, imp=0.97),
            dict(name="P2", label="P2: 4+ Rebounds", price="-500", p=0.8, imp=0.83)]}]}},
         "markets": {"today": [{"lg": "NBA", "match": "X at Y", "m": [
            dict(g="Team total", l="Y over 110.5", p=0.52), dict(g="Team total", l="Y under 110.5", p=0.48),
            dict(g="Team total", l="Y over 100.5", p=0.8)]}]},
         "slots": {"today": {"nba": {"rows": [dict(mp="Y", mc=70)]}}},
         "every_game": {"today": [dict(gid="g", label="Y over 100.5 points", price="-400", p=0.8, league="nba", match="X @ Y", status="open")]}}

    def test_nfl_scorers_compact(self):
        E = [dict(name=f"P{i}", p=0.5 - i / 50, p2=0.1 + (i == 7) * 0.2, pfirst=0.12 - i / 100, price="+100") for i in range(10)]
        D = dict(self.D, td={"today": [{"lg": "NFL", "match": "BUF @ KC", "tip": "8:20 PM", "everyone": E}]})
        out = daily_card.scorer_lines(D)
        self.assertTrue(out[0].startswith("NFL touchdown scorers -- every player is on the page"))
        self.assertEqual(out[1], "  BUF @ KC 8:20 PM (10 players listed):")
        self.assertEqual(out[2].count(";"), 5)                                # top 6 anytime
        self.assertTrue(out[3].startswith("    2+ TDs: P7 30%"), out[3])      # sorted by its own chance
        self.assertTrue(out[4].startswith("    First TD: P0 12%; P1 11%; P2 10%"), out[4])

    def test_no_nfl_falls_back_to_props_one_per_player(self):
        D = dict(self.D, td={"today": []})
        out = daily_card.scorer_lines(D)
        self.assertEqual(out[0], "No NFL today -- player props instead, one per player (his best-paying line at 80%+):")
        self.assertEqual(sum("P1:" in l for l in out), 1)              # one prop per player
        self.assertTrue(any("P1: 10+ Points" in l for l in out))       # his longest price still 80%+
        self.assertTrue(any("P2: 4+ Rebounds" in l for l in out))

    def test_best_per_player_floor(self):
        P = [dict(name="A", p=0.88, imp=0.99), dict(name="A", p=0.82, imp=0.85), dict(name="A", p=0.6, imp=0.6),
             dict(name="B", p=0.7, imp=0.7)]
        self.assertEqual(daily_card.best_per_player(P), [dict(name="A", p=0.82, imp=0.85)])

    def test_ten_leg_sizes_line(self):
        D = dict(self.D, ten_leg={"sizes": [dict(n=6, days=13, cashed=12, pays=1.34), dict(n=10, days=13, cashed=11, pays=1.64)]})
        out = daily_card.ten_leg_lines(D)
        self.assertEqual(out[1], "  Other sizes, replayed: 6 legs cashed 12/13 at 1.34x; 10 legs cashed 11/13 at 1.64x"
                                 " -- fewer legs win more often, pay less.")
        self.assertFalse(any("Other sizes" in l for l in daily_card.ten_leg_lines(self.D)))

    def test_team_points_under_lean_and_even(self):
        D = {"markets": {"today": [{"lg": "NBA", "match": "X at Y", "m": [
            dict(g="Team total", l="Y over 110.5", p=0.46), dict(g="Team total", l="Y under 110.5", p=0.54),
            dict(g="Team total", l="Y over 104.5", p=0.71), dict(g="Team total", l="Y under 104.5", p=0.29),
            dict(g="Team total", l="X over 101.5", p=0.5), dict(g="Team total", l="X under 101.5", p=0.5)]},
            {"lg": "NHL", "match": "A at B", "m": [dict(g="Team total", l="B over 2.5", p=0.6)]}]}}
        self.assertEqual(daily_card.team_points_lines(D),
                         ["NBA team points (main team total, the side the price leans):",
                          "  X at Y: Y under 110.5 54%; X over 101.5 50%"])       # NHL left out
        self.assertEqual(daily_card.team_points_lines({}), [])

    def test_team_points_and_winners_and_ten_leg(self):
        self.assertEqual(daily_card.team_points_lines(self.D)[1], "  X at Y: Y over 110.5 52%")
        self.assertEqual(daily_card.winner_lines(self.D)[1], "  NBA (1): Y 70%")
        D = dict(self.D, slots={"today": {"soccer": {"rows": [dict(mp="Flamengo", mc=75), dict(mp="Santos or draw", mc=73)]}}})
        self.assertEqual(daily_card.winner_lines(D)[1:], ["  SOCCER (1): Flamengo 75%", "  SOCCER win or draw (1): Santos 73%"])
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].startswith("Daily 1-leg: all win 80%, pays 1.25x"))
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].endswith("(only 1 games priced so far; it fills to 10 at the 8 AM card)"))
        self.assertEqual(daily_card.ten_leg_lines(self.D)[2], "     Needs: Y must score 101 or more points")
        D = dict(self.D, every_game={"today": [dict(gid="g", label="Over 200.5 points", price="-2000", p=0.93,
                                                   league="nba", match="A @ B", status="open")]})
        self.assertEqual(daily_card.ten_leg_lines(D)[2], "     Needs: Both teams together: 201 or more points")


class ReviewLine(unittest.TestCase):
    def test_ten_leg_line(self):
        import daily_review
        self.assertEqual(daily_review.ten_leg_line(dict(days=13, cashed=11, stated=0.409, pays=1.64)),
                         "Daily 10-leg, replayed on every 8 AM card: cashed 11 of 13 days (85%) vs 41% stated, at about 1.64x.")
        self.assertIsNone(daily_review.ten_leg_line(dict(days=0)))

    def test_ticket_size_line(self):
        import daily_review
        recs = {10: dict(days=13, cashed=11, stated=0.41, pays=1.64), 6: dict(days=13, cashed=12, stated=0.6, pays=1.34),
                15: dict(days=0)}
        self.assertEqual(daily_review.ticket_size_line(recs),
                         "Ticket size, replayed on every 8 AM card: 6 legs 12/13 at 1.34x; 10 legs 11/13 at 1.64x.")
        self.assertIsNone(daily_review.ticket_size_line({8: dict(days=0)}))


class TdCalibration(unittest.TestCase):
    def test_line(self):
        import daily_review
        B = {f"k{i}": dict(status="won" if i % 4 == 0 else "lost", p=0.25, date=f"2026-11-{1 + i // 4:02d}") for i in range(40)}
        B["k0"]["tds"] = 2
        B["k4"]["tds"] = 1
        out = daily_review.td_calibration_line(B)
        self.assertTrue(out.startswith("Anytime touchdown chances, by half: 5/20 scored vs 5.0 stated (z +0.0) to 2026-11-05"), out)
        self.assertTrue(out.endswith("2+ touchdowns graded so far: 1 of 2 players."), out)
        self.assertIsNone(daily_review.td_calibration_line({}))


class EveryGameBands(unittest.TestCase):
    def test_line(self):
        import daily_review
        rows = [(f"2026-11-{1 + i // 5:02d}", dict(p=0.93 if i % 2 else 0.88, status="won" if i % 7 else "lost")) for i in range(30)]
        out = daily_review.every_game_band_line(rows)
        self.assertTrue(out.startswith("Every game's safest line by chance, halves split 2026-11-04: 92%+ "), out)
        self.assertIn("under 85% none then none", out)
        self.assertIsNone(daily_review.every_game_band_line([]))


class ValueBands(unittest.TestCase):
    def test_line(self):
        import daily_review
        F = {f"v{i}": dict(status="won" if i % 2 else "lost", fair=0.5, start=f"2026-11-{1 + i // 4:02d}T00:00Z", kind="value")
             for i in range(40)}
        F["parlay"] = dict(status="won", fair=0.5, start="2026-11-01T00:00Z", kind="parlay")
        out = daily_review.value_band_line(F)
        self.assertIn("45-60% 10/20 (z +0.0) then 10/20 (z +0.0)", out)
        self.assertIn("0-30% none then none", out)
        self.assertIsNone(daily_review.value_band_line({}))



class FrozenPool(unittest.TestCase):
    def test_either_date_form_finds_the_pool(self):
        import json
        import tempfile
        import locks
        self.assertEqual(locks.iso_day("20261118"), "2026-11-18")
        self.assertEqual(locks.iso_day("2026-11-18"), "2026-11-18")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "safe.json")
            with open(p, "w") as fh:
                json.dump({"pools": {"2026-11-18": {"legs": [{"gid": "g"}]}}}, fh)
            self.assertEqual(locks.frozen_pool("20261118", p), {"legs": [{"gid": "g"}]})   # the board's form
            self.assertEqual(locks.frozen_pool("2026-11-18", p), {"legs": [{"gid": "g"}]})
            self.assertIsNone(locks.frozen_pool("20261119", p))


if __name__ == "__main__":
    unittest.main()
