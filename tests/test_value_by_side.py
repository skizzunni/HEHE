import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import value_bets as V                                            # noqa: E402


def f(i, side, day, won, fair=0.4, dec=2.6):
    return dict(kind="value", side=side, seen=f"{day}T12:00:00", start=f"{day}T20:00Z", status="won" if won else "lost",
                fair=fair, dec=dec, ev=0.02, id=f"x:{i}")


class BySide(unittest.TestCase):
    def test_split(self):
        finds = {}
        for i in range(8):
            day = "2026-10-01" if i < 4 else "2026-10-10"
            finds[f"h{i}"] = f(i, "home", day, i % 2 == 0)           # 2/4 each half
            finds[f"a{i}"] = f(i, "away", day, i % 4 == 0)           # 1/4 each half
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"finds": finds}, fh)
        try:
            r = V.report(fh.name)
        finally:
            os.unlink(fh.name)
        bs = {b["side"]: b["halves"] for b in r["by_side"]}
        self.assertEqual([(h["won"], h["n"], h["fair"]) for h in bs["home"]], [(2, 4, 40.0), (2, 4, 40.0)])
        self.assertEqual([(h["won"], h["n"]) for h in bs["away"]], [(1, 4), (1, 4)])
        self.assertEqual(bs["home"][0]["roi"], 30.0)                  # (1.6 + 1.6 - 1 - 1) / 4


if __name__ == "__main__":
    unittest.main()


class PreregHome(unittest.TestCase):
    def test_counts_only_home_finds_from_the_start(self):
        fs = [f(i, "home", "2026-11-15", i < 30, fair=0.5) for i in range(60)]          # 30/60 vs 50%: fine
        fs += [f(99, "home", "2026-11-14", False), f(98, "away", "2026-11-16", False)]   # before start / other side: out
        st = V.prereg_status(finds=fs)
        self.assertEqual((st["won"], st["n"], st["fair"], st["verdict"]), (30, 60, 50.0, "fine"))
        short = [f(i, "home", "2026-11-16", i < 20, fair=0.5) for i in range(60)]        # 33% vs 50%: short
        self.assertEqual(V.prereg_status(finds=short)["verdict"], "short")
        self.assertEqual(V.prereg_status(finds=short[:10])["verdict"], "waiting")

