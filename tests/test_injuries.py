"""Injury reports: parsed, snapshotted only on change, read as of a start."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injuries                                           # noqa: E402

DOC = {"injuries": [{"displayName": "LA Clippers", "injuries": [
    {"athlete": {"displayName": "Brandon Ingram"}, "status": "Out"},
    {"athlete": {"displayName": "Someone"}, "status": "Active"}]}]}


class Injuries(unittest.TestCase):
    def test_parse_keeps_shown_statuses(self):
        self.assertEqual(injuries.parse(DOC), {"LA Clippers": [["Brandon Ingram", "Out"]]})

    def test_snapshot_on_change_and_as_of_start(self):
        with tempfile.TemporaryDirectory() as d:
            t0 = dt.datetime(2026, 11, 4, 15, tzinfo=dt.timezone.utc)
            injuries.snapshot({"nba": injuries.parse(DOC)}, t0, d)
            injuries.snapshot({"nba": injuries.parse(DOC)}, t0 + dt.timedelta(hours=1), d)    # unchanged
            later = {"nba": {"LA Clippers": [["Brandon Ingram", "Out"], ["Bradley Beal", "Out"]]}}
            injuries.snapshot(later, t0 + dt.timedelta(hours=5), d)
            import json
            with open(os.path.join(d, "2026-11-04.json")) as fh:
                self.assertEqual(len(json.load(fh)["snapshots"]), 2)
            self.assertEqual(injuries.before("2026-11-04", "2026-11-04T17:00Z", "nba", d),
                             {"LA Clippers": [["Brandon Ingram", "Out"]]})
            self.assertEqual(len(injuries.before("2026-11-04", "2026-11-05T01:00Z", "nba", d)["LA Clippers"]), 2)

    def test_note_by_team(self):
        n = injuries.note({"nba": injuries.parse(DOC)}, "nba", "LA Clippers", "Miami Heat")
        self.assertEqual(n, dict(home=["Brandon Ingram (Out)"], away=[]))


if __name__ == "__main__":
    unittest.main()
