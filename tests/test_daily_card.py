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
        self.assertEqual(out[0], "No NFL today -- likeliest player props instead:")
        self.assertEqual(sum("P1:" in l for l in out), 1)              # one prop per player
        self.assertTrue(any("P1: 5+ Points" in l for l in out))        # the surest of P1's (ties by price)
        self.assertTrue(any("P2: 4+ Rebounds" in l for l in out))

    def test_team_points_and_winners_and_ten_leg(self):
        self.assertEqual(daily_card.team_points_lines(self.D)[1], "  X at Y: Y over 110.5 52%")
        self.assertEqual(daily_card.winner_lines(self.D)[1], "  NBA (1): Y 70%")
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].startswith("Daily 1-leg: all win 80%, pays 1.25x"))


if __name__ == "__main__":
    unittest.main()
