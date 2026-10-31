"""The lottery's leg pool leaves out the bet types locks.EXCLUDED names."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lottery                                            # noqa: E402
import locks                                              # noqa: E402
import stacks                                             # noqa: E402


class Excluded(unittest.TestCase):
    def test_college_unders_never_lottery_legs(self):
        box = {}

        def fd_specs(FD, refs):
            box["refs"] = refs
            return None

        legs = [dict(label="Under 50.5", spec=dict(t="under", line=50.5), p=0.6),
                dict(label="Over 40.5", spec=dict(t="over", line=40.5), p=0.6)]

        def candidates(rows, soccer_keys, labels, extra=None, band=None):
            for L in legs:
                box["refs"][("ncaaf:1", json.dumps(L["spec"], sort_keys=True))] = ("r", "-150", None)
            return [dict(gid="ncaaf:1", league="ncaaf", lg="NCAAF", match="A at B", home="B", away="A",
                         legs=legs)]

        with mock.patch.object(locks, "fd_specs", fd_specs), mock.patch.object(stacks, "candidates", candidates), \
                mock.patch.object(locks, "two_sided", lambda *a, **k: (0.6, "two-sided")):
            out = lottery._game_legs({"ncaaf": []}, set(), {}, {})
        self.assertEqual([L["spec"]["t"] for L in out], ["over"])


if __name__ == "__main__":
    unittest.main()
