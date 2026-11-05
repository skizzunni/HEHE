#!/usr/bin/env bash
# Everything a change must pass before it is committed. Exits non-zero on the
# first failure, so `tools/check.sh && git commit ...` cannot commit past a
# failing test (2026-11-05: a pipe into `tail` hid a failing unit test).
set -u
cd "$(dirname "$0")/.."
fail=0
out=$(python -m unittest discover -s tests -q 2>&1); rc=$?
echo "unit tests: $(printf '%s\n' "$out" | tail -1)"
[ $rc -eq 0 ] || { printf '%s\n' "$out" | grep -E -A12 "^(FAIL|ERROR):" | head -40; fail=1; }
ui=$(python tests/ui_check.py 2>&1); rc=$?
echo "page check: $(printf '%s\n' "$ui" | tail -1 | cut -c1-80)"
[ $rc -eq 0 ] || { printf '%s\n' "$ui" | grep "^FAIL" | head -10; fail=1; }
# the live data line in board.html is the bot's, never a hand commit's
n=$(git diff -- board.html | grep -c '^[-+]const D' || true)
n2=$(git diff --cached -- board.html | grep -c '^[-+]const D' || true)
if [ "$n" != "0" ] || [ "$n2" != "0" ]; then echo "board.html: the live 'const D' line is changed -- restore it"; fail=1; fi
# bot-owned data files are committed by the board job only
bot=$(git diff --cached --name-only | grep -E '^(ledger|locks|safe_locks|lottery|frontier|props|calls|value|sources|maker|stacks|prop_locks)\.json$|^review/' || true)
if [ -n "$bot" ]; then echo "staged bot data files (restore them): $bot"; fail=1; fi
[ $fail -eq 0 ] && echo "ALL CHECKS PASS" || echo "CHECKS FAILED"
exit $fail
