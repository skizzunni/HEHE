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
  5. a price older than 15 minutes on the viewer's clock reads stale;
  6. the Safe Locks 7-day tile totals the record's graded days;
  7. the ladder tile shows the bank and streak, and the Locks tab's ladder
     card shows today's 5 legs, the stake, the wins needed and the odds.
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
  var cl = [].slice.call(document.querySelectorAll("#panel button.copylegs"));
  out.copyCalls = cl.length;
  if (cl[0]) { var t = COPIES[+cl[0].getAttribute("data-copyid")] || ""; out.copyText = t.split("\\n").length; }
  var iso = function(m){ return new Date(Date.now() - m * 60000).toISOString(); };
  out.staleNow = [staleNow({pa: iso(20)}), staleNow({pa: iso(5)}), staleNow({st: true}), staleNow({})];
  out.moreHidden = [].slice.call(document.querySelectorAll("#days .more")).filter(function(x){return !x.hidden}).length;
  var mt = document.getElementById("moreToggle"); if (mt) mt.click();
  out.moreShown = [].slice.call(document.querySelectorAll("#days .more")).filter(function(x){return !x.hidden}).length;
  if (mt) mt.click();
  out.odds = callOdds([{conf: 80}, {conf: 80}]);
  out.band = [bandNote({bv: {band: "50-60", roi: -6.24, roi95: [-9.15, -3.23], n: 3153, skip: true}}),
              bandNote({bv: {band: "90-100", roi: 0.49, roi95: [-1.01, 1.88], n: 485, skip: false}}), bandNote({})];
  var sk = {band: "50-60", roi: -6.24, roi95: [-9.15, -3.23], n: 3153, skip: true};
  out.skipBar = [skipBar([{bv: sk, p: "-120"}, {bv: sk, p: "-118"}, {bv: {band: "90-100", roi: 0.49, n: 485, skip: false}, p: "-900"}]),
                 skipBar([{p: "-900"}])];
  out.venue = [venueNote({p: "-160", vn: [{venue: "FanDuel", price: "-140", dec: 1.7143}, {venue: "DraftKings", price: "-160", dec: 1.625}]}),
               venueNote({p: "-160", vn: [{venue: "DraftKings", price: "-160", dec: 1.625}, {venue: "Kalshi", price: "62\u00a2", dec: 1.6}]}),
               venueNote({p: "-160", vn: []})];
  out.be = [breakEvenBoost(0.08, 10), breakEvenBoost(0.12, 10), breakEvenBoost(0, 10)];
  out.ladderTile = [].slice.call(document.querySelectorAll('#glance [data-goto="locks"]')).map(function(e){return e.textContent})
    .filter(function(t){return /Ladder/.test(t)}).join("");
  out.sweepTile = [].slice.call(document.querySelectorAll('#glance [data-goto="results"]')).map(function(e){return e.textContent}).join("|");
  out.oneIn = [oneIn(0.71), oneIn(4.22e-8)];
  out.own = ownHTML({n: 382, own: 232, market: 260, since: "2026-10-05", today: [{league: "nba", match: "MIA @ LAC", own: "LAC", own_p: 60, market: "MIA", market_p: 65}]});
  out.inj = [injNote({inj: {mine: ["Giannis Antetokounmpo (Day-To-Day)"], opp: ["Brandon Ingram (Out)", "Bradley Beal (Out)", "A (Out)", "B (Out)", "C (Out)"]}}), injNote({}), injNote({inj: {mine: [], opp: []}})];
  out.mv = [moveNote({mv: 5}), moveNote({mv: -4}), moveNote({mv: null}), moveNote({})];
  out.yday = [yesterdayHTML({day: "2026-11-03", won: 34, lost: 1, losses: [{league: "efl1", pick: "Charlton Athletic", conf: 70, price: "-310", score: {"Bolton Wanderers": 1, "Charlton Athletic": 0}, tags: ["favourite lost", "close game"], why: "margin 1 · favourite lost · close game"}]}), yesterdayHTML({day: "x", won: 0, lost: 0})];
  out.ownTile = [].slice.call(document.querySelectorAll('#glance .k')).map(function(e){return e.textContent}).filter(function(t){return /vs market/.test(t)}).join("|");
  out.kind = [kindLine([{kind: "player props", won: 33, n: 41, said: 79.1}, {kind: "game lines", won: 136, n: 165, said: 77.3}]), kindLine([])];
  out.nextTile = [].slice.call(document.querySelectorAll('#glance .k')).map(function(e){return e.textContent}).filter(function(t){return /Next up/i.test(t)}).join("|");
  var plSave = D.prop_locks;
  D.prop_locks = {standard: 0.7, hour: 12, record: {n: 0}, today: {legs: [{label: "Luka Doncic: 6+ Assists", price: "-400", p: 0.79, match: "LAL @ SAC", status: "open", live: "3rd 4:10", live_score: "LAL 88 - SAC 80"}]}};
  try { out.plLive = propLocksHTML(); } catch(e) { out.plLive = "ERR " + e; }
  D.prop_locks = plSave;
  out.ladderFirst = [ladderFirst([{tip: "9:30 PM"}, {tip: "7:00 PM"}, {tip: "12:45 PM"}, {tip: "10:00 PM"}]), ladderFirst([{}, {}])];
  out.reasons = [reasonsHTML({since: "2026-10-21", n: 237, tags: [{tag: "favourite lost", n: 130}, {tag: "close game", n: 110}]}), reasonsHTML({n: 0, tags: []})];
  var lrSave = D.locks_record; D.locks_record = Object.assign({}, lrSave, {watch: [{league: "nba", t: "over", won: 10, n: 18, said: 75}]});
  out.watch = [watchNote({league: "nba", spec: {t: "over"}}), watchNote({league: "nba", t: "under"}), watchNote({league: "nba", kind: "prop", t: "over"})];
  D.locks_record = lrSave;
  out.pace = [paceNote({label: "Over 205.5 points", league: "nba", live: "9:23 - 2nd", live_score: "Detroit Pistons 25 - Philadelphia 76ers 33"}),
              paceNote({label: "Under 5.5 goals", league: "nhl", live: "End of 2nd", live_score: "A 1 - B 2"}),
              paceNote({label: "Luka Doncic: 6+ Assists", league: "nba", live: "1st", live_score: "A 1 - B 2"}),
              paceNote({label: "Over 205.5 points", league: "nba", live: "20.2 - 4th", live_score: "Detroit Pistons 104 - Philadelphia 76ers 109"}),
              paceNote({label: "Over 220.5 points", league: "nba", live: "30.5 - 4th", live_score: "A 100 - B 100"})];
  out.soFar = [soFar({so_far: 2, line: "4+", market: "Assists"}), soFar({so_far: 3, line: "2+", market: "Assists"}), soFar({line: "2+"})];
  out.safe = [safeNote({mc: 54, safe: {label: "Ottawa Senators under 5.5 goals", price: "-1450", p: 0.89}}), safeNote({mc: 80, safe: {label: "Over 204.5 points", price: "-2000", p: 0.9}}), safeNote({mc: 54})];
  out.upset = upsetHTML({min: 40, record: {n: 797, won: 295, said: 45.4, beating: false, halves: [{n: 685, won: 252, said: 45.5}, {n: 112, won: 43, said: 45.1}]},
                         today: [{league: "nhl", match: "OTT @ BUF", favourite: "Buffalo Sabres", dog: "OTT", chance: 46, tip: "7:30 PM", signals: ["my model picks them", "price moving their way"]}]});
  out.tileGoto = [].slice.call(document.querySelectorAll('#glance .k')).map(function(e){return e.getAttribute("data-goto") || ""});
  out.tiles7 = [].slice.call(document.querySelectorAll("#glance .k")).map(function(e){return e.textContent})
    .filter(function(t){return /7 days/.test(t)});
  var b = [].slice.call(document.querySelectorAll("button")).filter(function(x){return /^Locks/.test(x.textContent)})[0];
  if (b) b.click();
  setTimeout(function(){
    var s = document.querySelector('[data-lkmode="safe"]'); if (s) s.click();
    setTimeout(function(){
      out.bannerOnLocks = !!document.getElementById("stalebar");
      out.everyGame = [].slice.call(document.querySelectorAll("#panel .sweep")).map(function(e){return e.textContent}).filter(function(t){return /Every game/.test(t)}).join(" | ");
      out.ladderCard = [].slice.call(document.querySelectorAll("#panel .sweep")).map(function(e){return e.textContent})
        .filter(function(t){return /Ladder challenge/.test(t)}).join(" | ");
      try { out.ladderLast = ladderLast({day: "2026-11-03", result: "lost", stake: 3.07, after: 0, legs: [{label: "Leg X", status: "lost", score: "A 1 - B 2"}]}, function(v){return "$" + v.toFixed(2)}); } catch(e) { out.ladderLast = "ERR " + e; }
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


EVERY = dict(preview=False, record=dict(n=427, won=386, hit=90.4, stated=88.5, roi=-3.0, days=14, since="2026-10-21", swept=0,
                                             by_league=[dict(league="NCAAF", won=86, n=91), dict(league="NBA", won=82, n=89)]),
             today=[dict(gid="nhl:1", label="Winnipeg Jets +4.5", price="-2000", p=0.917, match="WPG at MTL", league="nhl",
                         tip="7:00 PM", status="won", score="WPG 5 - MTL 4"),
                    dict(gid="nba:2", label="Over 200.5 points", price="-900", p=0.9, match="A at B", league="nba",
                         tip="7:30 PM", status="open", score=None, alt=dict(venue="Kalshi", ask=0.88, dec=1.125, american="-800", gain=0.0125)),
                    dict(gid="nhl:3", label="Under 9.5 goals", price="-1500", p=0.9, match="C at D", league="nhl",
                         tip="7:00 PM", status="open", score=None, live="2nd 5:12", live_score="C 1 - D 1")])
LADDER = dict(start="2026-11-03", target=10000.0, bank=3.05, runs=1, streak=1, best=3.05, wins_needed=8,
              log=[dict(day="2026-11-02", stake=1.0, result="won", pays=3.05)],
              chance_to_target=0.0000656, history=[],
              today=dict(stake=3.05, pays=3.06, prob=0.30, result="open",
                         legs=[dict(label=f"Ladder leg {i + 1}", price="-300", p=0.79, match=f"Game {i + 1}",
                                    status="won" if i == 0 else "open", score="A 3 - B 2" if i == 0 else None,
                                    tip="7:30 PM", lg="NHL", **(dict(live="2nd 10:00", live_score="A 1 - B 0") if i == 1 else {}))
                               for i in range(5)]))


def render(captured_ms, health=None):
    s = open(os.path.join(ROOT, "board.html")).read()
    s = re.sub(r'"captured":\d+', f'"captured":{captured_ms}', s, count=1)
    s = s.replace("const D = {", 'const D = {"safe_locks":' + json.dumps(safe_card())
                  + ',"safe_locks_record":' + json.dumps(RECORD) + ',"paired":' + json.dumps(PAIRED) + ',"frontier":' + json.dumps(frontier_fixture()) + ',"call_targets":' + json.dumps(call_targets_fixture(captured_ms)) + ',"health":' + json.dumps(health) + ',"ladder":' + json.dumps(LADDER) + ',"every_game":' + json.dumps(EVERY) + ',', 1)
    s = s.replace('"live":[],"feed":', '"live":[{"pick":"X","winning":false},{"pick":"Y","winning":true}],"feed":', 1)
    s = s.replace('"results":{', '"results":{"own":{"n":382,"own":232,"market":260,"today":[{},{}]},"next_up":[{"tip":"12:45 PM","league":"ucl","match":"RMA @ AEK","conf":78,"pick":"Real Madrid","price":"-450"}],', 1)
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
                 "at a lower standard (75%+ legs)", "What 80%+ legs have done", "1151", "supported",
                 "Bankroll challenge", "wins in a row", "chance of losing"):
        if want not in tg:
            fails.append("Targets tab missing: " + want + " | " + tg[:300])
            break
    if not new.get("copyCalls") or new.get("copyText", 0) < 2:
        fails.append(f"Calls must have a Copy legs button holding the legs: {new.get('copyCalls')} buttons, {new.get('copyText')} lines")
    if (new.get("moreHidden"), new.get("moreShown")) != (0, 8):
        fails.append(f"secondary sections must sit behind More: {new.get('moreHidden')} shown, {new.get('moreShown')} after opening")
    if "64%" not in (new.get("odds") or "") or "1.6 of 2" not in (new.get("odds") or ""):
        fails.append("outcome odds: two 80% calls must read 64% all win, 1.6 expected: " + (new.get("odds") or "")[:200])
    be = new.get("be") or []
    if len(be) != 3 or abs(be[0] - (1 / 0.08 - 1) / 9 + 1) > 1e-9 or be[1] != 0 or be[2] is not None:
        fails.append(f"break-even boost: 8% at 10x needs +27.8%, 12% needs none: {be}")
    vn = new.get("venue") or ["", "", "x"]
    if "FanDuel -140" not in vn[0] or "+5.5%" not in vn[0] or "best price here" not in vn[1] or vn[2] != "":
        fails.append(f"venue note must name the better venue and its gain: {vn}")
    if new.get("oneIn") != ["71%", "1 in 23,696,682"]:
        fails.append("oneIn wrong: " + repr(new.get("oneIn")))
    eg = new.get("everyGame", "")
    if not all(x in eg for x in ("Every game: its safest bet (3 games, 1–0 so far)", "Live: 2nd 5:12 · C 1 - D 1", "Pays more at Kalshi: 88¢ (-800 after fee), $10 wins $1.25 vs $1.11 at FanDuel", "386 of 427", "90.4%",
                                   "Winnipeg Jets +4.5", "WPG 5 - MTL 4", "By league: NCAAF 86/91, NBA 82/89", "Sweep odds: all 3 win 74%; the top 3 win 74%. The whole list has swept on 0 of 14 days.", "$10 on each (3 bets, $30 staked): +$2.28 if every one wins; expected −$0.77 from the stated chances.", "set at 8 AM")):
        fails.append("every game section wrong: " + eg)
    ow = new.get("own", "")
    if not all(x in ow for x in ("mine 232 right (60.7%)", "260 (68.1%)", "The market is ahead", "I take LAC</b> (60%)")):
        fails.append("own picks section wrong: " + ow)
    ij = new.get("inj") or ["", "x", "x"]
    if not ("my side: Giannis Antetokounmpo (Day-To-Day)" in ij[0] and "their side: Brandon Ingram (Out), Bradley Beal (Out), A (Out), B (Out) +1" in ij[0]) or ij[1] or ij[2]:
        fails.append("injury note wrong: " + repr(ij))
    mv = new.get("mv") or ["", "", "x", "x"]
    if not ("Money moving my way</b> (+5 pts" in mv[0] and "Price moved against it</b> (-4 pts" in mv[1]) or mv[2] or mv[3]:
        fails.append("move note wrong: " + repr(mv))
    yd = new.get("yday") or ["", "x"]
    if not all(x in yd[0] for x in ("Yesterday (2026-11-03): 34&ndash;1", "EFL1 Charlton Athletic at 70% (-310)",
                                    "Bolton Wanderers 1 &ndash; Charlton Athletic 0", "favourite lost, close game", "margin 1")) or yd[1]:
        fails.append("yesterday section wrong: " + repr(yd))
    if "margin 1 · favourite lost" in (yd[0] if yd else ""):
        fails.append("yesterday section repeats its tags: " + yd[0])
    ot = new.get("ownTile", "")
    if not ("My picks vs market" in ot and "232–260" in ot and "same 382 games, prices hidden · 2 splits today" in ot):
        fails.append("own tile wrong: " + ot)
    kd = new.get("kind") or ["", "x"]
    if "By type: player props 33 of 41 (80% vs 79.1% stated) &middot; game lines 136 of 165 (82% vs 77.3% stated)." not in kd[0] or kd[1]:
        fails.append("kind line wrong: " + repr(kd))
    nt = new.get("nextTile", "")
    if not ("12:45 PM" in nt and "Real Madrid 78% (-450) · RMA @ AEK" in nt):
        fails.append("next tile wrong: " + nt)
    pl = new.get("plLive", "")
    if "<b>Live:</b> 3rd 4:10 &middot; LAL 88 - SAC 80" not in pl:
        fails.append("prop locks live line wrong: " + pl[-400:])
    if new.get("ladderFirst") != ["4 to play, first at 12:45 PM", "2 to play"]:
        fails.append("ladder first-leg line wrong: " + repr(new.get("ladderFirst")))
    rz = new.get("reasons") or ["", "x"]
    if not ("Why picks lost, last 14 days</b> (237 losses)" in rz[0] and "favourite lost</td><td class=\"num\">130" in rz[0] and "width:85%" in rz[0]) or rz[1]:
        fails.append("loss reasons wrong: " + repr(rz)[:300])
    wn = new.get("watch") or ["", "x", "x"]
    if "Caution:</b> NBA overs on Locks have won 10 of 18 against 75% stated" not in wn[0] or wn[1] or wn[2]:
        fails.append("watch note wrong: " + repr(wn))
    pc = new.get("pace") or ["", "", "x", "", ""]
    if not ("On pace for <b>190</b> (58 so far, line 205.5) &middot; behind the pace it needs" in pc[0]
            and "On pace for <b>5</b> (3 so far, line 5.5) &middot; on track" in pc[1]
            and "Already over</b> (213, line 205.5)" in pc[3] and "On pace for <b>202</b>" in pc[4]) or pc[2]:
        fails.append("pace note wrong: " + repr(pc))
    sf = new.get("soFar") or ["", "", "x"]
    if not ("Assists so far: 2</b>, needs 4 (2 to go)" in sf[0] and "Assists so far: 3</b>, needs 2 &middot; already there" in sf[1]) or sf[2]:
        fails.append("so-far line wrong: " + repr(sf))
    sn = new.get("safe") or ["", "", "x"]
    if not ("Safest bet in this game:</b> Ottawa Senators under 5.5 goals -1450 (89%) &mdash; for a sweep" in sn[0]
            and "Over 204.5 points -2000 (90%)</div>" in sn[1]) or sn[2]:
        fails.append("safe note wrong: " + repr(sn))
    up = new.get("upset", "")
    if not all(x in up for x in ("Upset watch", "won <b>37.0% of 797 (price said 45.4%)</b>", "first half 36.8% of 685",
                                 "Under their price", "<b>OTT</b> 46% &middot; NHL OTT @ BUF", "my model picks them &middot; price moving their way")):
        fails.append("upset watch wrong: " + up[:400])
    st = new.get("sweepTile", "")
    if not ("Board sweep" in st and "5–2" in st and "sweep broken, 17 to go (2 live, 1 not winning now)" in st):
        fails.append("board sweep tile wrong: " + st)
    sb = new.get("skipBar") or ["", "x"]
    if not ("2 of 3 picks here are marked" in sb[0] and "50-60%: -6.2% per $1 over 3,153 games" in sb[0]
            and "Bet the day" in sb[0]) or sb[1]:
        fails.append("skip bar wrong: " + repr(sb))
    bn = new.get("band") or ["", "", "x"]
    if "-6.2% per $1" not in bn[0] or "skip" not in bn[0] or "+0.5%" not in bn[1] or "skip" in bn[1] or bn[2] != "":
        fails.append(f"band note must state the band's historical return and mark skips: {bn}")
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
    if (new.get("tileGoto") or [""])[0] != "calls" or "" in (new.get("tileGoto") or [""]):
        fails.append(f"every summary tile must open its section: {new.get('tileGoto')}")
    t7 = " | ".join(new.get("tiles7") or [])
    if "Safe Locks, 7 days11 of 11100.0% hit, 1 cards" not in t7:
        fails.append("Safe Locks 7-day tile must total the record's graded days: " + t7)
    lt, lc = new.get("ladderTile", ""), new.get("ladderCard", "")
    ll = new.get("ladderLast", "")
    if not all(x in ll for x in ("Last ticket (2026-11-03): LOST", "$3.07 lost", "Lost on Leg X (A 1 - B 2)")):
        fails.append("ladder last ticket wrong: " + ll)
    if "$3.05" not in lt or "1 of 5 won today, 1 live" not in lt:
        fails.append("ladder tile must show the bank and streak: " + lt)
    if not all(x in lc for x in ("Ladder challenge: $1", "Ladder leg 5", "NHL · 7:30 PM", "1 of 5 won, 4 to play (1 live now)", "Live: 2nd 10:00 · A 1 - B 0", "A 3 - B 2", "stake $3.05", "8 straight wins", "1 in 15,244", "This run, day by day (1)", "would take 37 wins in a row")):
        fails.append("ladder card must show today's 5 legs, stake, wins needed and odds: " + lc[:300])
    for f in fails:
        print("FAIL:", f)
    print("OK" if not fails else f"{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
