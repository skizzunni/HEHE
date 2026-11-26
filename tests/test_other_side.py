import os
import sys
import unittest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "tools")]
import other_side as O  # noqa: E402

ROWS = [{"lg": "nfl", "game": "PHI @ DAL", "home": "DAL", "away": "PHI", "line": "DAL -8.5", "id": "1"},
        {"lg": "nfl", "game": "KC @ BUF", "home": "BUF", "away": "KC", "line": "BUF -3", "id": "2"},
        {"lg": "nfl", "game": "A @ B", "home": "B", "away": "A", "line": "A -14.5", "id": "3"},
        {"lg": "nba", "game": "X @ Y", "home": "Y", "away": "X", "line": "Y -9.5", "id": "4"}]


class OtherSide(unittest.TestCase):
    def test_only_nfl_dogs_getting_7_5_to_14(self):
        self.assertEqual([(d, p) for _, d, p in O.dogs(ROWS)], [("PHI", 8.5)])

    def test_legs_grade_as_spreads(self):
        import grade_picks as G
        L = O.legs(O.dogs(ROWS))[0]
        self.assertEqual((L["kind"], L["team"], L["line"]), ("spread", "PHI", 8.5))
        self.assertEqual(G.grade(L, {"PHI": 20, "DAL": 27}, True, {}), "won")      # lost by 7, +8.5 covers
        self.assertEqual(G.grade(L, {"PHI": 10, "DAL": 27}, True, {}), "lost")

    def test_text(self):
        self.assertIn("PHI +8.5 -- PHI @ DAL", O.text(O.dogs(ROWS)))
        self.assertEqual(O.text([]), "Other side: no NFL underdog getting 7.5-14 today.")


if __name__ == "__main__":
    unittest.main()
