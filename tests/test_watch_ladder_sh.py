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


if __name__ == "__main__":
    unittest.main()
