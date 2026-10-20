"""Item 6: strong-call cut-offs frozen for 14 days, earned only with 150+
graded picks in the prior window, a hit rate at the target, a Wilson lower
bound at target - 3 points, and a Holm correction across leagues."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import daily_review as R                                  # noqa: E402


def picks(n, conf, hit, lg="ncaaf", day0="2026-10-06", days=14):
    d0 = dt.date.fromisoformat(day0)
    return [dict(league=lg, conf=conf, price="-400", status="won" if (i * hit) % 1 + hit >= 1 else "lost",
                 date=(d0 + dt.timedelta(days=i % days)).isoformat()) for i in range(n)]


def exact(n, k, conf=85.0, lg="nhl"):
    """n picks, exactly k won."""
    return [dict(e, status="won" if i < k else "lost") for i, e in enumerate(picks(n, conf, 1.0, lg=lg))]


class Frozen(unittest.TestCase):
    def test_qualifies_only_with_150_and_the_wilson_bound(self):
        cuts, det = R.fit_frozen(picks(200, 85.0, 0.84), "2026-10-20")
        self.assertEqual(cuts, {"ncaaf": 0.55})
        self.assertEqual(det["ncaaf"]["window"], ["2026-10-06", "2026-10-19"])
        self.assertEqual(R.fit_frozen(picks(149, 85.0, 0.90), "2026-10-20")[0], {})     # N < 150
        cuts, det = R.fit_frozen(picks(200, 85.0, 0.76), "2026-10-20")                  # 76%, bound ~70%
        self.assertEqual(cuts, {})
        self.assertLess(det["ncaaf"].get("wilson95", [0])[0] if "wilson95" in det["ncaaf"] else 0, 72)

    def test_only_the_prior_window_counts(self):
        old = picks(300, 85.0, 0.95, day0="2026-09-01")               # before the 14 days
        self.assertEqual(R.fit_frozen(old, "2026-10-20")[0], {})

    def test_holm_across_leagues(self):
        # each league alone passes its Wilson bound; one marginal p-value
        # fails once three leagues share the family's alpha
        ent = (picks(400, 85.0, 0.90, lg="ncaaf") + exact(160, 127, lg="nhl")
               + picks(160, 60.0, 0.50, lg="nfl"))
        cuts, det = R.fit_frozen(ent, "2026-10-20")
        self.assertIn("ncaaf", cuts)
        self.assertNotIn("nhl", cuts)
        self.assertEqual(det["nhl"].get("note"), "failed the Holm-corrected test")

    def test_frozen_for_14_days(self):
        path = os.path.join(tempfile.mkdtemp(), "call_min.json")
        ent = picks(200, 85.0, 0.84)
        cfg = R.frozen_cutoffs(ent, dt.date(2026, 10, 20), path)
        self.assertEqual((cfg["frozen_from"], cfg["frozen_to"]), ("2026-10-20", "2026-11-02"))
        with open(path, "w") as fh:
            json.dump(cfg, fh)
        worse = picks(200, 85.0, 0.50, day0="2026-10-20")              # the record collapses
        kept = R.frozen_cutoffs(ent + worse, dt.date(2026, 11, 2), path)
        self.assertEqual(kept["cutoffs"], {"ncaaf": 0.55})            # no refit inside the window
        self.assertEqual(kept["holdout"]["window"], ["2026-10-20", "2026-11-02"])
        self.assertIsNotNone(kept["holdout"]["wilson95"])
        new = R.frozen_cutoffs(ent + worse, dt.date(2026, 11, 3), path)
        self.assertEqual(new["cutoffs"], {})                          # refrozen on the new window


if __name__ == "__main__":
    unittest.main()
