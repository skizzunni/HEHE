"""Browser checks of the published page, run in headless Chrome.

    python3 tests/ui_check.py            # CHROME=/path/to/chrome to override

board.html is filled with fixed data (a Safe Locks card shaped like a real
one), loaded in a real browser, clicked through, and the rendered text is
read back. Checks:

  1. a copy 20+ minutes old shows the stale banner on every tab;
  2. a fresh copy shows no banner;
  3. Locks -> Safe Locks renders the card, the Winners parlay (top N at 80%+)
     and the Best play (50%+), with the numbers the card's own sizes imply;
  4. the record lists the Winners parlay's own hit rate and each day's result;
  5. a price older than 15 minutes on the viewer's clock reads stale.
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
    extra = dict(legs[0], label="Same-game idea", extra=True, gid="ncaaf:0")
    return dict(today=dict(locks=legs, available=11, prob=round(P, 4), sizes=sizes, preview=True,
                           extras=[extra]),
                tomorrow=dict(locks=[]))


RECORD = dict(legs=11, won=11, said=94.0, plays=dict(winners=dict(days=3, hit=3, said=81.0),
                                                     best=dict(days=3, hit=2, said=55.0)),
              days=[dict(day="2026-10-17", n=11, won=11, lost=0, void=0, open=0, all_hit=True,
                         plays=dict(winners=dict(n=4, prob=0.81, result="won")))])

PAIRED = dict(run="2026-10-19", rule="promote only if the 95% range is above zero", studies=[dict(
    name="Model weight off (market-only) vs the published picks", baseline="published", proposal="market",
    same="one pick per game", promoted=[], result=dict(all=dict(picks=476, old_won=305, new_won=320, diff=15,
    ci95_diff=[-6, 42], new_won_old_missed=53, old_won_new_missed=38, promote=False)))])

def frontier_fixture():
    def leg(i, p, price):
        return dict(gid=f"nfl:{i}", label=f"Under {40 + i}.5 points", p=p, price=price,
                    match=f"Game {i}", lg="NFL", league="nfl", kind="game", spec=dict(t="under"))
    rows = [dict(target=2.0, standard=0.80, legs=[leg(1, 0.84, "-300"), leg(2, 0.82, "-260"), leg(3, 0.81, "-250")],
                 prob=0.558, total=2.04, n=3, ev=-0.06, exact=True, payout_basis="estimated: product"),
            dict(target=3.0, standard=0.80, legs=[leg(i, 0.81, "-250") for i in range(4, 9)],
                 prob=0.349, total=3.05, n=5, ev=-0.07, exact=True, payout_basis="estimated: product"),
            dict(target=5.0, standard=0.80, legs=None, ceiling=2.74, exact=True),
            dict(target=5.0, standard=0.75, legs=[leg(i, 0.76, "-320") for i in range(9, 15)],
                 prob=0.19, total=5.02, n=6, ev=-0.05, exact=True)]
    ev = dict(sources=[dict(name="Kalshi mid-prices", rows=[dict(band="80-85%", n=1151, games=237, said=82.5,
              hit=83.3, ci95=[80.9, 85.8], first="2026-08-29", last="2026-10-18", verdict="supported")])])
    return dict(today={"0": dict(rows=rows, candidates=120, games=30, excluded=4, excluded_why={"game has started": 4},
                                 settlement="full game", max_legs=6, kind_cap=3)},
                evidence=ev, record=[], backtest=None)


def call_targets_fixture(ms):
    import datetime as dt
    at=dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc)
    legs=[dict(id=f"nhl:{i}",pick=f"Team {i}",price=price,conf=conf,price_at=at.isoformat(),
               prob_at=at.isoformat(),start=(at+dt.timedelta(hours=2)).isoformat(),
               gate=dict(ok=True,what="both goalies confirmed"))
          for i,price,conf in ((1,"-250",84),(2,"-200",82))]
    return dict(as_of=at.isoformat(),standard=.75,max_legs=3,excluded=[],targets=[dict(target=2.,
                ticket=dict(legs=legs,book="DraftKings",joint=.6764016,payout=2.1,value=.42044))])


PROBE = """<script>setTimeout(function(){
  var out = {banner: !!document.getElementById("stalebar")};
  var iso = function(m){ return new Date(Date.now() - m * 60000).toISOString(); };
  out.staleNow = [staleNow({pa: iso(20)}), staleNow({pa: iso(5)}), staleNow({st: true}), staleNow({})];
  out.moreHidden = [].slice.call(document.querySelectorAll("#days .more")).filter(function(x){return !x.hidden}).length;
  var mt = document.getElementById("moreToggle"); if (mt) mt.click();
  out.moreShown = [].slice.call(document.querySelectorAll("#days .more")).filter(function(x){return !x.hidden}).length;
  if (mt) mt.click();
  out.odds = callOdds([{conf: 80}, {conf: 80}]);
  var b = [].slice.call(document.querySelectorAll("button")).filter(function(x){return /^Locks/.test(x.textContent)})[0];
  if (b) b.click();
  setTimeout(function(){
    var s = document.querySelector('[data-lkmode="safe"]'); if (s) s.click();
    setTimeout(function(){
      out.bannerOnLocks = !!document.getElementById("stalebar");
      out.betFirst = /Ticket to bet: doubles your stake/.test((document.getElementById("panel") || {}).textContent || "");
      out.heading = (document.querySelector(".parlays h3") || {}).textContent || "";
      out.legs = ((document.querySelector(".parlays ul.legs") || {}).children || []).length;
      out.record = [].slice.call(document.querySelectorAll(".parlays details")).map(function(e){return e.textContent}).join(" | ");
      out.bars = [].slice.call(document.querySelectorAll(".coinbar")).map(function(e){return e.textContent});
      var r = [].slice.call(document.querySelectorAll("button")).filter(function(x){return /^Results/.test(x.textContent)})[0];
      if (r) r.click();
      setTimeout(function(){
        out.health = ((document.getElementById("health") || {}).textContent || "");
        out.results = ((document.getElementById("panel") || {}).textContent || "");
        var tg = [].slice.call(document.querySelectorAll("button")).filter(function(x){return /^Targets/.test(x.textContent)})[0];
        if (tg) tg.click();
        setTimeout(function(){
          var st = document.querySelector('[data-tgstd="0.8"]'); if (st) st.click();
          setTimeout(function(){
            out.targets = ((document.getElementById("panel") || {}).textContent || "");
            out.current = liveCallTargets(D.call_targets);
            var oldNow = Date.now;
            Date.now = function(){ return oldNow() + 20*60000; };
            out.expiredCurrent = liveCallTargets(D.call_targets);
            Date.now = oldNow;
            document.title = "UICHECK " + JSON.stringify(out);
          }, 300);
        }, 300);
      }, 300);
    }, 300);
  }, 300);
}, 500);</script>"""


def render(captured_ms, health=None):
    s = open(os.path.join(ROOT, "board.html")).read()
    s = re.sub(r'"captured":\d+', f'"captured":{captured_ms}', s, count=1)
    s = s.replace("const D = {", 'const D = {"safe_locks":' + json.dumps(safe_card())
                  + ',"safe_locks_record":' + json.dumps(RECORD) + ',"paired":' + json.dumps(PAIRED) + ',"frontier":' + json.dumps(frontier_fixture()) + ',"call_targets":' + json.dumps(call_targets_fixture(captured_ms)) + ',"health":' + json.dumps(health) + ',', 1)
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
                integrity=[["D.locks.today.locks[0].p", "chance outside 0-1", "1.3"]],
                stale_inputs=[["football/nfl", 95]])
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
    if "Winners parlay: the top 4 legs" not in bars or "est. 80% to all hit" not in bars:
        fails.append("Winners parlay line missing or wrong: " + bars)
    if "Best play: the top 10 legs" not in bars or "est. 54% to all hit" not in bars:
        fails.append("Best play line missing or wrong: " + bars)
    if "Winners parlay hit 3 of 3 days (81% promised)" not in new["record"] \
            or "top 4 (81%): hit" not in new["record"]:
        fails.append("Safe Locks record must show the Winners parlay's own record: " + new["record"][-300:])
    if "Same-game ideas (1)" not in new["record"] or new["legs"] != 11:
        fails.append("same-game ideas must be listed apart from the card's 11 legs: " + new["record"][:200])
    if "4 problems found" not in old["health"] or "Old input: football/nfl" not in old["health"] or "props uel Shots" not in old["health"] \
            or "Never settled" not in old["health"] or "Bad data: chance outside 0-1" not in old["health"]:
        fails.append("health box must list the trailing split and the stuck record: " + old["health"])
    if "Changes tested" not in new["results"] or "New right, old wrong" not in new["results"] \
            or "-6 to 42" not in new["results"]:
        fails.append("Results must list each tested change with both directions: " + new["results"][-300:])
    tg = new["targets"]
    for want in ("cash chance (est.)", "55.8%", "Unavailable at 80%+ legs", "most a ticket of those legs can pay today is 2.74x",
                 "at a lower standard (75%+ legs)", "What 80%+ legs have done", "1151", "supported"):
        if want not in tg:
            fails.append("Targets tab missing: " + want + " | " + tg[:300])
            break
    if (new.get("moreHidden"), new.get("moreShown")) != (0, 6):
        fails.append(f"secondary sections must sit behind More: {new.get('moreHidden')} shown, {new.get('moreShown')} after opening")
    if "64%" not in (new.get("odds") or "") or "1.6 of 2" not in (new.get("odds") or ""):
        fails.append("outcome odds: two 80% calls must read 64% all win, 1.6 expected: " + (new.get("odds") or "")[:200])
    if not new.get("betFirst"):
        fails.append("Locks must lead with the likeliest 2x ticket (betFirst)")
    if new.get("staleNow") != [True, False, True, False]:
        fails.append(f"a price 20 minutes old at viewing time must read stale: {new.get('staleNow')}")
    if "All checks passing" not in new["health"]:
        fails.append("clean review must read 'All checks passing': " + new["health"])
    if not all(x in new.get("current", "") for x in ("Current parlay choices", "67.6%", "2.10x", "DraftKings")):
        fails.append("Current calls must show the same-book payout-target ticket")
    if "quote expired" not in new.get("expiredCurrent", "") or "67.6%" in new.get("expiredCurrent", ""):
        fails.append("Expired call-ticket quotes must not remain actionable")
    for f in fails:
        print("FAIL:", f)
    print("OK" if not fails else f"{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
