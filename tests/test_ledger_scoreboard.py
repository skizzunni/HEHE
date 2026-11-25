import unittest
from unittest.mock import patch

import ledger

EV = {"events": [{"competitions": [{"id": "9", "date": "2026-11-17T00:00Z",
       "status": {"type": {"completed": True, "state": "post", "name": "STATUS_FINAL", "shortDetail": "Final"}},
       "competitors": [{"homeAway": "home", "winner": True, "score": "88", "team": {"displayName": "Kentucky Wildcats"}},
                       {"homeAway": "away", "score": "59", "team": {"displayName": "Grambling Tigers"}}]}]}]}


class CollegeScoreboard(unittest.TestCase):
    def test_ncaab_asks_for_every_division_one_game(self):
        """2026-11-16: the default scoreboard listed 1 of 33 games, so a final
        Kentucky win stayed open a week and was headed for a void."""
        urls = []

        def get(u, tries=2):
            urls.append(u)
            return EV if "groups=50" in u else {"events": []}
        with patch.object(ledger, "get", get):
            r = ledger._final("ncaab", "9", {"date": "2026-11-16"})
        self.assertEqual(r["winner"], "Kentucky Wildcats")
        self.assertTrue(all("groups=50" in u for u in urls))

    def test_other_leagues_unchanged(self):
        urls = []

        def get(u, tries=2):
            urls.append(u)
            return EV
        with patch.object(ledger, "get", get):
            ledger._final("nba", "9", {"date": "2026-11-16"})
        self.assertTrue(urls and not any("groups=" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
