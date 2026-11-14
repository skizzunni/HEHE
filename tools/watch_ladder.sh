#!/usr/bin/env bash
# Live ladder tracking in one command, safe to re-run after a restart:
#   tools/watch_ladder.sh [WORKDIR] [DAY LEAGUE]
# Makes WORKDIR a detached worktree of this repo if it is not one yet, keeps
# its state in WORKDIR.state.json (so a restart reports what changed while it
# was down), and runs tools/ladder_watch.py --loop 120 there until the ticket
# and any watched games settle (prints DONE).
# WORKDIR defaults to ~/.cache/hehe-ladder-watch: a container restart can wipe
# /tmp (and the session scratchpad with it), which lost the state once.
# DAY "auto" (or empty with LEAGUE set) is the board day: the ET date three
# hours ago, so late West Coast games stay on the day they started.
set -u
WORK=${1:-$HOME/.cache/hehe-ladder-watch}
DAY=${2:-}
LG=${3:-}
if [ "$DAY" = "auto" ] || { [ -z "$DAY" ] && [ -n "$LG" ]; }; then
  DAY=$(TZ=America/New_York date -d '3 hours ago' +%F)
fi
ROOT=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$(dirname "$WORK")"
if [ ! -f "$WORK/tools/ladder_watch.py" ]; then
  git -C "$ROOT" worktree prune
  rm -rf "$WORK"
  git -C "$ROOT" worktree add -q --detach "$WORK" HEAD || exit 1
fi
cd "$WORK" || exit 1
exec python -u tools/ladder_watch.py "$WORK.state.json" $DAY $LG --loop 120 2>&1
