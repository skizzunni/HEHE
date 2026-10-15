#!/bin/bash
# One-time setup of the Kalshi bot on a Mac. Run from the repository:
#
#     bash bot/mac/install.sh
#
# It asks for the Kalshi key ID, the Kalshi private key file and a GitHub
# token, keeps all three in ~/.hehe-bot (readable by your user only), and
# schedules bot/mac/run.sh every 5 minutes with launchd. The bot starts in
# PRACTICE mode. Nothing here sends your keys anywhere but Kalshi and GitHub.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
H="$HOME/.hehe-bot"
LABEL="com.hehe.kalshibot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if ! xcrun --find python3 >/dev/null 2>&1 && ! [ -x /usr/bin/python3 ]; then
  echo "Python 3 is needed. Run:  xcode-select --install  then run this again."
  exit 1
fi
mkdir -p "$H"
chmod 700 "$H"

echo "1/4  Setting up Python (one minute)..."
/usr/bin/python3 -m venv "$H/venv"
"$H/venv/bin/pip" install -q --upgrade pip cryptography

echo "2/4  Kalshi key"
read -r -p "     Kalshi API key ID: " KID
read -r -p "     Drag the Kalshi private key file into this window, then press Enter: " KF
# a dragged path arrives with backslash-escaped spaces, sometimes quoted
KF="$(printf '%s' "$KF" | sed -e 's/\\ / /g' -e "s/^[[:space:]'\"]*//" -e "s/[[:space:]'\"]*$//")"
[ -f "$KF" ] || { echo "     No file at: $KF"; exit 1; }
install -m 600 "$KF" "$H/kalshi.key"
printf '%s\n' "$KID" > "$H/kalshi_key_id"
chmod 600 "$H/kalshi_key_id"
"$H/venv/bin/python" - "$H/kalshi.key" <<'PY'
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
k = serialization.load_pem_private_key(open(sys.argv[1], "rb").read(), password=None)
if not isinstance(k, rsa.RSAPrivateKey):
    sys.exit("     That is not an RSA key. Create the Kalshi key with type RSA.")
print("     key file OK (RSA)")
PY

echo "3/4  GitHub token (lets the bot post its report to your site)"
read -r -s -p "     Paste the token (it will not show), then press Enter: " GT
echo
printf '%s' "$GT" > "$H/github_token"
chmod 600 "$H/github_token"
S="$H/status"
rm -rf "$S"
mkdir -p "$S"
git -C "$S" init -q
git -C "$S" config user.name "hehe bot (mac)"
git -C "$S" config user.email "hehe-bot@users.noreply.github.com"
git -C "$S" remote add origin "https://x-access-token:${GT}@github.com/skizzunni/HEHE.git"
if ! git -C "$S" ls-remote -q origin >/dev/null 2>&1; then
  echo "     GitHub refused that token. Check it has Contents: Read and write on HEHE."
  exit 1
fi
echo "     token OK"

echo "4/4  Scheduling the bot every 5 minutes"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO/bot/mac/run.sh</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$H/bot.log</string>
  <key>StandardErrorPath</key><string>$H/bot.log</string>
</dict>
</plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "Done. The bot runs now and every 5 minutes, in PRACTICE mode."
echo "  Watch it:      tail -f ~/.hehe-bot/bot.log"
echo "  Go live:       touch ~/.hehe-bot/LIVE      (back to practice: rm ~/.hehe-bot/LIVE)"
echo "  Stop it:       launchctl bootout gui/\$(id -u)/$LABEL"
echo "Keep the Mac awake and online: it cannot run while asleep."
