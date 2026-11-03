"""Ladder challenge: the day's 5 likeliest Locks as one parlay, bank rolled."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ladder                                             # noqa: E402


def leg(k, p, st, price="-200"):
    return k, dict(label=k, price=price, p=p, status=st)


def book(days):
    b = {"days": {}, "legs": {}}
    for d, legs in days.items():
        b["days"][d] = []
        for k, p, st in legs:
            kk, L = leg(f"{d}|{k}", p, st)
            b["legs"][kk] = L
            b["days"][d].append(kk)
    return b


W5 = [(c, 0.8, "won") for c in "abcde"]


class Ladder(unittest.TestCase):
    def test_top_five_roll_and_bust(self):
        b = book({"2026-11-03": W5 + [("f", 0.5, "lost")],            # f is 6th: not on the ticket
                  "2026-11-04": W5[:4] + [("e", 0.8, "lost")],
                  "2026-11-05": W5})
        runs = ladder.replay(b, start="2026-11-03")
        self.assertEqual([r["status"] for r in runs], ["lost", "live"])
        self.assertAlmostEqual(runs[0]["days"][1]["stake"], round(1.5 ** 5, 2))   # -200 x5 = 7.59x
        self.assertAlmostEqual(runs[1]["bank"], round(1.5 ** 5, 2))

    def test_void_leg_drops_out_and_open_day_stops(self):
        b = book({"2026-11-03": W5[:4] + [("e", 0.8, "void")], "2026-11-04": W5[:4] + [("e", 0.8, "open")]})
        runs = ladder.replay(b, start="2026-11-03")
        self.assertAlmostEqual(runs[0]["days"][1]["stake"], round(1.5 ** 4, 2))
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual(r["today"]["result"], "open")
        self.assertEqual(r["streak"], 1)

    def test_short_card_skipped(self):
        b = book({"2026-11-03": W5[:3]})
        self.assertEqual(ladder.replay(b, start="2026-11-03"), [])


if __name__ == "__main__":
    unittest.main()
