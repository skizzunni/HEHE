#!/usr/bin/env bash
# Live ladder tracking in one command, safe to re-run after a restart:
#   tools/watch_ladder.sh WORKDIR [DAY LEAGUE]
# Makes WORKDIR a detached worktree of this repo if it is not one yet, keeps
# its state in WORKDIR.state.json (so a restart reports what changed while it
# was down), and runs tools/ladder_watch.py --loop 120 there until the ticket
# and any watched games settle (prints DONE).
set -u
WORK=${1:?usage: tools/watch_ladder.sh WORKDIR [DAY LEAGUE]}
DAY=${2:-}
LG=${3:-}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ ! -f "$WORK/tools/ladder_watch.py" ]; then
  git -C "$ROOT" worktree prune
  rm -rf "$WORK"
  git -C "$ROOT" worktree add -q --detach "$WORK" HEAD || exit 1
fi
cd "$WORK" || exit 1
exec python -u tools/ladder_watch.py "$WORK.state.json" $DAY $LG --loop 120 2>&1
