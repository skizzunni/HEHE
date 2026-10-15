#!/bin/bash
# One bot run on the Mac; launchd starts this every 5 minutes (install.sh).
# 1. update the code  2. download today's Kalshi-ready tickets from the site
# 3. run the bot with the key in ~/.hehe-bot  4. post its report for the Bot tab
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
H="$HOME/.hehe-bot"
SITE="https://skizzunni.github.io/HEHE"
BRANCH="claude/mlb-picks-review-jlx9w1"

# keep the log from growing without bound
if [ -f "$H/bot.log" ] && [ "$(wc -c < "$H/bot.log")" -gt 5000000 ]; then
  : > "$H/bot.log"
fi
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z')"

git -C "$REPO" pull -q --ff-only origin "$BRANCH" || echo "code update failed; using the copy on disk"

if curl -fsS -m 30 -o "$H/board.json.tmp" "$SITE/kalshi_stacks.json?$(date +%s)"; then
  mv "$H/board.json.tmp" "$H/board.json"
else
  echo "could not download today's tickets"
fi

export HEHE_BOT_STATE="$H" KALSHI_BOARD="$H/board.json"
export KALSHI_KEY_ID="$(cat "$H/kalshi_key_id")" KALSHI_PRIVATE_KEY_FILE="$H/kalshi.key"
# real money only while this file exists -- nothing remote can switch it on
if [ -f "$H/LIVE" ]; then export KALSHI_LIVE=yes; else export KALSHI_LIVE=no; fi

(cd "$REPO" && "$H/venv/bin/python" bot/kalshi_bot.py)

# the report goes to its own one-commit branch; the site build picks it up
S="$H/status"
cp "$H/bot_status.json" "$S/bot_status.json" 2>/dev/null || exit 0
[ -f "$H/bot_trades.json" ] && cp "$H/bot_trades.json" "$S/bot_trades.json"
git -C "$S" add -A
git -C "$S" commit -q --amend -m "bot status" 2>/dev/null || git -C "$S" commit -q -m "bot status"
git -C "$S" push -qf origin HEAD:refs/heads/bot-status || echo "could not post the report"
