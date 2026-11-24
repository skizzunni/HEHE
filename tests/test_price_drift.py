import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import price_drift as P  # noqa: E402


class DriftTest(unittest.TestCase):
    def test_groups_and_tally(self):
        log = [{"prices": {"H": "-1300", "T": "-1600", "R": "-1200"}}, {"prices": {"H": "-950", "T": "-2000", "R": "-1150"}}]
        self.assertEqual(P.group(log, "H"), "drifted")
        self.assertEqual(P.group(log, "T"), "firmed")
        self.assertEqual(P.group(log, "R"), "flat")
        self.assertIsNone(P.group(log[:1], "H"))
        self.assertAlmostEqual(P.implied("-1300"), 0.9286, places=4)
        self.assertEqual(P.tally([("drifted", "lost"), ("drifted", "won"), ("firmed", "won"), (None, "won"), ("flat", "open")]),
                         {"drifted": {"won": 1, "lost": 1, "push": 0}, "firmed": {"won": 1, "lost": 0, "push": 0}})

    def test_main_reads_slate_folders(self):
        root = tempfile.mkdtemp()
        d = os.path.join(root, "work", "slate_nov24")
        os.makedirs(d)
        json.dump([{"label": "H"}, {"label": "T"}], open(os.path.join(d, "ticket.json"), "w"))
        with open(os.path.join(d, "price_log.jsonl"), "w") as f:
            f.write(json.dumps({"prices": {"H": "-1300", "T": "-1600"}}) + "\n")
            f.write(json.dumps({"prices": {"H": "-950", "T": "-2000"}}) + "\n")
        out = P.main(root, grade_fn=lambda path: (json.load(open(path)), ["lost", "won"], {}))
        self.assertEqual(out, {"drifted": {"won": 0, "lost": 1, "push": 0}, "firmed": {"won": 1, "lost": 0, "push": 0}})


if __name__ == "__main__":
    unittest.main()
