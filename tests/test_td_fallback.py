import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import td_fallback as T  # noqa: E402


class RowsTest(unittest.TestCase):
    def test_rows_from_scoreboard_and_summary(self):
        sb = {"events": [{"id": "9", "shortName": "CHI @ DET", "date": "2026-11-26T17:30Z", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": "Detroit Lions"}},
            {"homeAway": "away", "team": {"displayName": "Chicago Bears"}}]}]}]}
        sm = {"pickcenter": [{"overUnder": 55.5}]}
        got = T.rows("2026-11-26", get=lambda u: sb if "scoreboard" in u else sm)
        self.assertEqual(got, [dict(id="nfl:9", label="CHI @ DET", tip="2026-11-26T17:30Z",
                                    mkt=dict(away="Chicago Bears", home="Detroit Lions", total=55.5))])

    def test_text(self):
        g = [dict(match="CHI @ DET", total=55.5, basis="scaled", players=[
            dict(name="Jahmyr Gibbs", p=0.61, price="-290", p2=0.24, pfirst=0.16)])]
        self.assertEqual(T.text(g), "CHI @ DET (total 55.5; scaled)\n  Jahmyr Gibbs: anytime 61% (-290), 2+ 24%, first TD 16%")
        self.assertEqual(T.text([]), "No NFL anytime-TD market posted yet.")


if __name__ == "__main__":
    unittest.main()
