import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anysport  # noqa: E402


def board(gid, when):
    return {"events": [{"season": {"type": 2}, "competitions": [{
        "id": gid, "date": when, "status": {"type": {"completed": True}},
        "competitors": [{"homeAway": "home", "score": "100", "team": {"displayName": "H"}},
                        {"homeAway": "away", "score": "90", "team": {"displayName": "A"}}]}]}]}


class EveningGameCacheTest(unittest.TestCase):
    def test_refresh_keeps_last_nights_game(self):
        pages = {"20261001": board("1", "2026-10-02T00:00Z"),      # 8 PM ET Oct 1 = Oct 2 in UTC
                 "20261002": {}}                                   # first run: Oct 2's fetch fails
        get = lambda url: pages[url.split("dates=")[1]]
        league = next(iter(anysport.LEAGUES))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(anysport, "CACHE", d), \
                mock.patch.object(anysport, "get", get):
            g1 = anysport.fetch_games(league, ["20261001", "20261002"], workers=1, ttl=0)
            self.assertEqual([(g["id"], g["date"]) for g in g1], [("1", "2026-10-01")])
            pages["20261002"] = {"events": []}                     # second run refetches Oct 2 only
            g2 = anysport.fetch_games(league, ["20261001", "20261002"], workers=1, ttl=0)
            self.assertEqual([g["id"] for g in g2], ["1"])          # Oct 1's evening game is kept


if __name__ == "__main__":
    unittest.main()
