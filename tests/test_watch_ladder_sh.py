"""tools/watch_ladder.sh end to end with a stand-in python: it builds the
worktree, resolves DAY 'auto' to the board day and hands ladder_watch.py the
state path, day and league."""
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SH = os.path.join(ROOT, "tools", "watch_ladder.sh")


class WatchLadderSh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        with open(os.path.join(self.bin, "python"), "w") as fh:          # prints its args instead of watching
            fh.write('#!/usr/bin/env bash\necho "ARGS $*"\n')
        os.chmod(os.path.join(self.bin, "python"), 0o755)
        self.work = os.path.join(self.tmp, "w")

    def tearDown(self):
        subprocess.run(["git", "-C", ROOT, "worktree", "remove", "--force", self.work], capture_output=True)
        subprocess.run(["git", "-C", ROOT, "worktree", "prune"], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        for f in (".state.json", ".state.json.ufc_picks.json", ".done", ".day"):
            if os.path.exists(self.work + f):
                os.remove(self.work + f)

    def run_sh(self, *args, tz_now=None):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["bash", SH, self.work, *args], capture_output=True, text=True, env=env, timeout=120)
        return r.returncode, r.stdout

    def test_auto_day_and_args(self):
        want = subprocess.run(["bash", "-c", "TZ=America/New_York date -d '3 hours ago' +%F"],
                              capture_output=True, text=True).stdout.strip()
        rc, out = self.run_sh("auto", "all")
        self.assertEqual(rc, 0)
        self.assertIn(f"ARGS -u tools/ladder_watch.py {self.work}.state.json {want} all --loop 120", out)
        self.assertTrue(os.path.isfile(os.path.join(self.work, "tools", "ladder_watch.py")))

    def test_explicit_day_kept(self):
        rc, out = self.run_sh("2026-11-13", "all")
        self.assertIn("tools/ladder_watch.py " + self.work + ".state.json 2026-11-13 all --loop 120", out)

    def test_cleans_up_after_done(self):
        with open(os.path.join(self.bin, "python"), "w") as fh:          # a watcher that settles at once
            fh.write('#!/usr/bin/env bash\necho "CHANGE: x"\necho "DONE: settled"\n')
        for f in (".state.json", ".state.json.ufc_picks.json"):
            open(self.work + f, "w").close()
        rc, out = self.run_sh("2026-11-13", "all")
        self.assertEqual(rc, 0)
        self.assertIn("DONE: settled", out)
        self.assertIn("CLEANED UP", out)
        for f in (".state.json", ".state.json.ufc_picks.json", ".done"):
            self.assertFalse(os.path.exists(self.work + f), f)
        self.assertFalse(os.path.exists(self.work))

    def test_no_cleanup_without_done(self):
        open(self.work + ".state.json", "w").close()
        with open(self.work + ".day", "w") as fh:                        # tonight's own state
            fh.write("2026-11-13\n")
        rc, out = self.run_sh("2026-11-13", "all")
        self.assertNotIn("CLEANED UP", out)
        self.assertTrue(os.path.exists(self.work + ".state.json"))
        self.assertTrue(os.path.isfile(os.path.join(self.work, "tools", "ladder_watch.py")))

    def test_state_from_another_day_dropped(self):
        for f in (".state.json", ".state.json.ufc_picks.json"):
            open(self.work + f, "w").close()
        with open(self.work + ".day", "w") as fh:
            fh.write("2026-11-14\n")
        rc, out = self.run_sh("2026-11-17", "all")
        self.assertIn("FRESH START: dropped a watch state left from 2026-11-14", out)
        self.assertFalse(os.path.exists(self.work + ".state.json"))
        with open(self.work + ".day") as fh:
            self.assertEqual(fh.read().strip(), "2026-11-17")

    def test_resume_says_where_it_stands(self):
        import json
        with open(self.work + ".state.json", "w") as fh:
            json.dump({"Duke Blue Devils to win": "open", "GAME nba A @ B": "board pick B (70%) = won | x",
                       "GAME nba C @ D": "board pick D (60%) = open", "TEN Over 200.5 points (A @ B)": "won | x",
                       "TEN Under 250.5 points (C @ D)": "open"}, fh)
        with open(self.work + ".day", "w") as fh:
            fh.write("2026-11-17\n")
        rc, out = self.run_sh("2026-11-17", "all")
        self.assertIn("RESUMED: Duke Blue Devils to win = open; 10-leg: 1 won, 0 lost, 1 open; "
                      "2 board games -- 1 won, 0 lost, 1 open", out)

    def test_same_day_state_kept(self):
        open(self.work + ".state.json", "w").close()
        with open(self.work + ".day", "w") as fh:
            fh.write("2026-11-17\n")
        rc, out = self.run_sh("2026-11-17", "all")
        self.assertNotIn("FRESH START", out)
        self.assertTrue(os.path.exists(self.work + ".state.json"))


if __name__ == "__main__":
    unittest.main()
