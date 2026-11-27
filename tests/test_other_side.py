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
        self.assertEqual(O.text([], rows=[dict(lg="nfl", game="DEN @ PIT", line="PIT -2.5"),
                                          dict(lg="nba", game="X @ Y", line="Y -3")]),
                         "Other side: no NFL underdog getting 7.5-14 today. NFL lines: DEN @ PIT PIT -2.5.")

class ForwardNoteTest(unittest.TestCase):
    def test_counts_cards_forward(self):
        import other_side as O
        base = O.note(forward=[])
        self.assertIn("56.3% covered on 112 games", base)
        self.assertIn("51.6% this season", base)
        one = O.note(forward=[("2026-11-26", "PHI +8.5", True)])
        self.assertIn("56.6% covered on 113 games", one)
        self.assertIn("53.1% this season, 1/1 on cards", one)
        self.assertIn("55.8% covered on 113", O.note(forward=[("d", "x", False)]))

class ForwardFromSlatesTest(unittest.TestCase):
    def test_reads_saved_cards(self):
        import json
        import tempfile
        import other_side as O
        root = tempfile.mkdtemp()
        for name in ("slate_nov23", "slate_nov26", "slate_nov30"):
            os.makedirs(os.path.join(root, "work", name))
            json.dump([{"label": name}], open(os.path.join(root, "work", name, "ticket_other.json"), "w"))
        res = {"slate_nov23": "won", "slate_nov26": "won", "slate_nov30": "open"}
        g = lambda f: ([{"label": os.path.basename(os.path.dirname(f))}],
                       [res[os.path.basename(os.path.dirname(f))]], {})
        fw = O.forward_from_slates(root, g)
        self.assertEqual([x[1] for x in fw], ["slate_nov26"])      # before Nov 24 and unsettled left out
        self.assertTrue(fw[0][2])
        self.assertIsNone(O.forward_from_slates(tempfile.mkdtemp(), g))
        self.assertIn("1/1 on cards", O.text([({"game": "PHI @ DAL"}, "PHI", 8.5)], fw))


if __name__ == "__main__":
    unittest.main()
