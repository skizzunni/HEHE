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
         "every_game": {"today": [dict(gid="g", label="Y over 100.5", price="-400", p=0.8, league="nba", match="X @ Y", status="open")]}}

    def test_nfl_scorers_every_player(self):
        out = daily_card.scorer_lines(self.D)
        self.assertEqual(out[0], "NFL touchdown scorers (anytime / 2+ / first TD):")
        self.assertIn("    A: 45% / 12% / 11% (-110)", out)

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

    def test_team_points_and_winners_and_ten_leg(self):
        self.assertEqual(daily_card.team_points_lines(self.D)[1], "  X at Y: Y over 110.5 52%")
        self.assertEqual(daily_card.winner_lines(self.D)[1], "  NBA (1): Y 70%")
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].startswith("Daily 1-leg: all win 80%, pays 1.25x"))
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].endswith("(only 1 games priced so far; it fills to 10 at the 8 AM card)"))


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


if __name__ == "__main__":
    unittest.main()
