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


if __name__ == "__main__":
    unittest.main()
