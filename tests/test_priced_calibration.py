import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ledger                                                    # noqa: E402

FP = dict(prices=dict(home="-200", draw="+300", away="+500"))


class Priced(unittest.TestCase):
    def test_groups_and_halves(self):
        B = {"z": dict(dc=True, league="epl")}
        for i in range(40):
            day = "2026-10-05" if i < 20 else "2026-11-05"
            B[f"w{i}"] = dict(league="epl", status="won" if i % 5 else "lost", conf=70, date=day, first=FP)
            B[f"d{i}"] = dict(league="epl", dc=True, status="won", conf=80, date=day, first=FP)
            B[f"n{i}"] = dict(league="nba", status="won", conf=60, date=day, first=FP)
            B[f"o{i}"] = dict(league="nba", status="lost", conf=60, date=day)              # older: out
            B[f"x{i}"] = dict(league="nba", status="lost", conf=60, date=day, first=FP, record_excluded=True)
        P = ledger.priced_calibration(B)
        self.assertEqual(P["mid"], "2026-11-05")
        g = {r["group"]: r["halves"] for r in P["rows"]}
        self.assertEqual(g["soccer win"], [[16, 20, 70.0], [16, 20, 70.0]])
        self.assertEqual(g["soccer or-draw"], [[20, 20, 80.0], [20, 20, 80.0]])
        self.assertEqual(g["nba"], [[20, 20, 60.0], [20, 20, 60.0]])

    def test_too_few(self):
        self.assertIsNone(ledger.priced_calibration({}))


if __name__ == "__main__":
    unittest.main()
