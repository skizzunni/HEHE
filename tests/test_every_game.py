"""Every game: its single likeliest game line, graded off the picks ledger."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import locks                                              # noqa: E402


def leg(gid, label, p, spec, kind=None):
    return dict(gid=gid, label=label, p=p, price="-900", spec=spec, kind=kind, home="H", away="A", match="A at H")


class EveryGame(unittest.TestCase):
    POOL = [leg("nhl:1", "Under 9.5 goals", 0.90, dict(t="under", line=9.5)),
            leg("nhl:1", "H +3.5", 0.93, dict(t="spread", team="H", line=3.5)),
            leg("nhl:1", "Player 1+ shots", 0.99, None, kind="prop"),
            leg("nhl:2", "Over 0.5 goals", 0.91, dict(t="over", line=0.5))]

    def test_one_line_per_game_props_left_out(self):
        self.assertEqual([L["label"] for L in locks.best_per_game(self.POOL)], ["H +3.5", "Over 0.5 goals"])

    def test_graded_off_final_scores(self):
        led = {"nhl:1": dict(status="won", scores={"H": 1, "A": 6}), "nhl:2": dict(status="open")}
        got = {g["gid"]: (g["status"], g["score"]) for g in locks.every_game(self.POOL, led)}
        self.assertEqual(got, {"nhl:1": ("lost", "A 6 - H 1"), "nhl:2": ("open", None)})


if __name__ == "__main__":
    unittest.main()
