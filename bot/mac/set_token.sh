#!/bin/bash
# (Re)enter the GitHub token the Mac bot uses to post its report:
#     bash ~/hehe-bot/bot/mac/set_token.sh
# The token must be able to WRITE to skizzunni/HEHE; this checks that with
# GitHub's API before saving it (reading works without any token, so a read
# test proves nothing).
set -euo pipefail
H="$HOME/.hehe-bot"
OWNER="skizzunni"
read -r -s -p "     Paste the GitHub token (it will not show), then press Enter: " GT
echo
GT="$(printf '%s' "$GT" | tr -d '[:space:]')"
PUSH="$(curl -fsS -m 20 -H "Authorization: Bearer $GT" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/$OWNER/HEHE 2>/dev/null \
  | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("permissions",{}).get("push"))' 2>/dev/null || true)"
if [ "$PUSH" != "True" ]; then
  echo "     GitHub did not accept that token for writing to HEHE."
  echo "     Make a fine-grained token: Repository access = Only HEHE,"
  echo "     Permissions > Contents = Read and write. Then run this again."
  exit 1
fi
printf '%s' "$GT" > "$H/github_token"
chmod 600 "$H/github_token"
S="$H/status"
mkdir -p "$S"
[ -d "$S/.git" ] || git -C "$S" init -q
git -C "$S" config user.name "hehe bot (mac)"
git -C "$S" config user.email "hehe-bot@users.noreply.github.com"
git -C "$S" remote remove origin 2>/dev/null || true
git -C "$S" remote add origin "https://${OWNER}:${GT}@github.com/${OWNER}/HEHE.git"
echo "     token OK (can write to HEHE)"
