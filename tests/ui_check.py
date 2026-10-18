"""Browser checks of the published page, run in headless Chrome.

    python3 tests/ui_check.py            # CHROME=/path/to/chrome to override

board.html is filled with fixed data (a Safe Locks card shaped like a real
one), loaded in a real browser, clicked through, and the rendered text is
read back. Checks:

  1. a copy 20+ minutes old shows the stale banner on every tab;
  2. a fresh copy shows no banner;
  3. Locks -> Safe Locks renders the card, the Winners parlay (top N at 80%+)
     and the Best play (50%+), with the numbers the card's own sizes imply.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [os.environ.get("CHROME"), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")]


def chrome():
    for c in CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("no Chrome/Chromium found; set CHROME")


def safe_card():
    p = [.952, .952, .94, .94, .94, .94, .94, .935, .935, .935, .915]
    pr = ["-2000"] * 7 + ["-1800"] * 3 + ["-1500"]
    legs = [dict(gid=f"ncaaf:{i}", label=f"Leg {i + 1}", match=f"Game {i + 1}", lg="NCAA FB",
                 league="ncaaf", p=p[i], price=pr[i], status="open", spec=dict(t="under", line=60.5))
            for i in range(11)]
    sizes, P, D = [], 1.0, 1.0
    for i, L in enumerate(legs, 1):
        P *= L["p"]
        D *= 1 + 100 / -int(L["price"])
        if i >= 2:
            sizes.append(dict(n=i, pays=round(D, 2), prob=round(P, 4), american=f"+{round((D - 1) * 100)}"))
    return dict(today=dict(locks=legs, available=11, prob=round(P, 4), sizes=sizes, preview=True),
                tomorrow=dict(locks=[]))


PROBE = """<script>setTimeout(function(){
  var out = {banner: !!document.getElementById("stalebar")};
  var b = [].slice.call(document.querySelectorAll("button")).filter(function(x){return /^Locks/.test(x.textContent)})[0];
  if (b) b.click();
  setTimeout(function(){
    var s = document.querySelector('[data-lkmode="safe"]'); if (s) s.click();
    setTimeout(function(){
      out.bannerOnLocks = !!document.getElementById("stalebar");
      out.heading = (document.querySelector(".parlays h3") || {}).textContent || "";
      out.legs = document.querySelectorAll(".parlays .legs li").length;
      out.bars = [].slice.call(document.querySelectorAll(".coinbar")).map(function(e){return e.textContent});
      var r = [].slice.call(document.querySelectorAll("button")).filter(function(x){return /^Results/.test(x.textContent)})[0];
      if (r) r.click();
      setTimeout(function(){
        out.health = ((document.getElementById("health") || {}).textContent || "");
        document.title = "UICHECK " + JSON.stringify(out);
      }, 300);
    }, 300);
  }, 300);
}, 500);</script>"""


def render(captured_ms, health=None):
    s = open(os.path.join(ROOT, "board.html")).read()
    s = re.sub(r'"captured":\d+', f'"captured":{captured_ms}', s, count=1)
    s = s.replace("const D = {", 'const D = {"safe_locks":' + json.dumps(safe_card())
                  + ',"safe_locks_record":{},"health":' + json.dumps(health) + ',', 1)
    i = s.rfind("</body>")
    s = s[:i] + PROBE + s[i:]
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
        fh.write(s)
    dom = subprocess.run([chrome(), "--headless=new", "--no-sandbox", "--disable-gpu",
                          "--window-size=485,1000", "--virtual-time-budget=5000", "--dump-dom",
                          "file://" + fh.name], capture_output=True, text=True, timeout=60).stdout
    os.unlink(fh.name)
    m = re.search(r"<title>UICHECK (.*?)</title>", dom)
    if not m:
        sys.exit("page did not finish rendering (no UICHECK title)")
    import html
    return json.loads(html.unescape(m.group(1)))


def main():
    fails = []
    now = int(time.time() * 1000)
    sick = dict(day="2026-10-18", checked=5, stuck=["props mlb:1|x|RBIs|1+"],
                trailing=[dict(name="props uel Shots", hit=40.0, said=84.3, n=20, flag=True)],
                integrity=[["D.locks.today.locks[0].p", "chance outside 0-1", "1.3"]])
    old = render(now - 45 * 60000, sick)
    new = render(now, dict(day="2026-10-18", checked=5, stuck=[], trailing=[]))
    print("stale copy:", old)
    print("fresh copy:", new)
    if not (old["banner"] and old["bannerOnLocks"]):
        fails.append("stale copy must show the banner on every tab")
    if new["banner"] or new["bannerOnLocks"]:
        fails.append("fresh copy must not show the banner")
    if new["heading"].strip() != "Safe Locks" or new["legs"] != 11:
        fails.append(f"Safe Locks card not rendered: {new['heading']!r}, {new['legs']} legs")
    bars = " | ".join(new["bars"])
    if "Winners parlay: the top 4 legs" not in bars or "80% to all hit" not in bars:
        fails.append("Winners parlay line missing or wrong: " + bars)
    if "Best play: the top 10 legs" not in bars or "54% to all hit" not in bars:
        fails.append("Best play line missing or wrong: " + bars)
    if "3 problems found" not in old["health"] or "props uel Shots" not in old["health"] \
            or "Never settled" not in old["health"] or "Bad data: chance outside 0-1" not in old["health"]:
        fails.append("health box must list the trailing split and the stuck record: " + old["health"])
    if "All checks passing" not in new["health"]:
        fails.append("clean review must read 'All checks passing': " + new["health"])
    for f in fails:
        print("FAIL:", f)
    print("OK" if not fails else f"{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
