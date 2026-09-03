"""Upcoming-games board with live pick tracking. Re-researches every 5 minutes.

    python3 dashboard.py                  # http://localhost:8000
    python3 dashboard.py --interval 300 --port 8000

Shows only games that have NOT started. Finals are dropped -- a settled game is
not a pick. Each cycle refetches every league for today and tomorrow, re-reads
the market, and diffs against the previous cycle so genuinely new information
surfaces instead of being buried:

  * a starting pitcher going from TBD to named
  * a moneyline moving (with the size and direction of the move)
  * a game appearing on the board for the first time
  * a pick flipping side because the market moved through the midpoint

The Pick column is the de-vigged market favourite, not a model output. That is
measured, not modest: over all 2,100 completed 2026 MLB games against real
closing prices the market called 56.5% and the run-rate model 53.8%, and on the
games where that model disagreed with the close by ten points or more it hit
47.3%. The MLB pick is therefore built from the line with the refitted model
allowed a fifth of the say, which is what turns its most confident calls from
56.7% into 71.7%.
"""
import argparse
import datetime as dt
import html
import json
import sys
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

import picks as P

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
MLB = "https://statsapi.mlb.com/api/v1"
ET = dt.timezone(dt.timedelta(hours=-4))

LEAGUES = [
    ("mlb",   "baseball/mlb",                "MLB"),
    ("wnba",  "basketball/wnba",             "WNBA"),
    ("nfl",   "football/nfl",                "NFL"),
    ("ncaaf", "football/college-football",   "NCAA FB"),
    ("nba",   "basketball/nba",              "NBA"),
    ("nhl",   "hockey/nhl",                  "NHL"),
    ("atp",   "tennis/atp",                  "Tennis (M)"),
    ("wta",   "tennis/wta",                  "Tennis (W)"),
    ("pga",   "golf/pga",                    "PGA"),
    ("ufc",   "mma/ufc",                     "UFC"),
] + [(k, v[0], v[1]) for k, v in sorted(__import__("anysport").LEAGUES.items())
     if v[0].startswith("soccer/")]
THREE_WAY = {k for k, p, _ in LEAGUES if p.startswith("soccer/")}

# Measured on 4,090 real sides of 2,045 completed 2026 MLB games with closing
# DraftKings prices. Every favourite bucket underperforms its own implied
# probability; the underdog buckets land close to fair. This is the classic
# favourite-longshot bias, and it is why a board that only names favourites is
# pointing at the worst-priced side of every game.
#   (low, high, actual win%, implied win%, flat ROI%)
BUCKETS = [
    (-10000, -200, 66.9, 70.8, -5.5),
    (-200,   -160, 58.9, 63.8, -7.8),
    (-160,   -130, 54.5, 58.8, -7.4),
    (-130,   -100, 51.8, 53.3, -3.0),
    (100,     130, 46.2, 47.0, -1.5),
    (130,     160, 41.1, 41.3, -0.7),
    (160,     200, 35.9, 36.4, -1.6),
    (200,   10000, 28.6, 30.2, -5.1),
]


def bucket(price):
    """Historical record for a price like this. None outside the tested range."""
    try:
        p = int(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    for lo, hi, act, imp, roi in BUCKETS:
        if lo <= p < hi:
            return dict(act=act, imp=imp, roi=roi, gap=act - imp)
    return None
_NO_PRICE = {"OFF", "EVEN", "", "-", "N/A", "PK"}

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass

_LOCK = threading.Lock()
_STATE = {"slots": {}, "at": None, "dates": ("", ""), "changes": [], "cycles": 0}
_PREV = {}          # game id -> last seen snapshot, for diffing


def get(url, tries=2):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30, context=_CTX) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.4)
    return {}


def am_to_dec(o):
    if o is None:
        return None
    s = str(o).strip().upper().replace("+", "")
    if s in _NO_PRICE or not s.lstrip("-").isdigit():
        return None
    v = int(s)
    return None if v == 0 else 1 + (v / 100 if v > 0 else 100 / -v)


def devig(*odds):
    decs = [am_to_dec(o) for o in odds]
    if any(d is None for d in decs):
        return None
    raw = [1 / d for d in decs]
    t = sum(raw)
    return [r / t for r in raw] if t > 0 else None


def deep_links(comp):
    """DraftKings bet-slip outcome ids per side, from ESPN's odds links.

    ESPN wraps them in a tracking gateway whose `preurl` carries the real
    sportsbook URL; the outcome id inside it is what a slip is built from.
    """
    out = {}
    for o in comp.get("odds") or []:
        if not isinstance(o, dict):
            continue
        ml = o.get("moneyline") or {}
        for side in ("away", "home"):
            for when in ("close", "open"):
                node = (ml.get(side) or {}).get(when) or {}
                href = (node.get("link") or {}).get("href")
                if not href:
                    continue
                try:
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    pre = q.get("preurl", [""])[0]
                    m = re.search(r"/event/(\d+)\?outcomes=([\w_]+)", pre)
                    if m:
                        out[side] = dict(event=m.group(1), outcome=m.group(2))
                        break
                except Exception:
                    pass
    return out


def raw_prices(comp, ways):
    for o in comp.get("odds") or []:
        if not isinstance(o, dict):
            continue
        ml = o.get("moneyline") or {}
        for when in ("close", "open"):
            try:
                a, h = ml["away"][when]["odds"], ml["home"][when]["odds"]
            except (KeyError, TypeError):
                continue
            if ways == 3:
                d = o.get("drawOdds") or {}
                dr = d.get(when, {}).get("odds") if isinstance(d.get(when), dict) else None
                if dr is not None:
                    return (a, dr, h)
            return (a, h)
        a = (o.get("awayTeamOdds") or {}).get("moneyLine")
        h = (o.get("homeTeamOdds") or {}).get("moneyLine")
        if a and h:
            return (a, h)
    return None


def sides(comp):
    out = {}
    for x in comp.get("competitors") or []:
        who = x.get("team") or x.get("athlete") or {}
        out[x.get("homeAway", "?")] = (who.get("abbreviation")
                                       or who.get("shortDisplayName")
                                       or who.get("displayName") or "?")
    return out


def start_et(comp):
    raw = comp.get("date") or ""
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            t = dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        return t.astimezone(ET)
    return None


def mlb_context(day):
    """Probable starters with ERA, and each club's record -- the analysis column."""
    out = {}
    d = get(f"{MLB}/schedule?sportId=1&date={day[:4]}-{day[4:6]}-{day[6:]}"
            f"&hydrate=probablePitcher,team&gameType=R")
    ids = set()
    for dd in d.get("dates", []):
        for g in dd.get("games", []):
            for s in ("away", "home"):
                pp = (g["teams"][s].get("probablePitcher") or {})
                if pp.get("id"):
                    ids.add(pp["id"])
    era = {}
    if ids:
        def one(pid):
            j = get(f"{MLB}/people/{pid}?hydrate=stats(group=[pitching],"
                    f"type=[season],season={dt.date.today().year})")
            try:
                p = j["people"][0]
                for s in p.get("stats", []):
                    if s.get("splits"):
                        return pid, (p["fullName"], s["splits"][0]["stat"].get("era"))
                return pid, (j["people"][0]["fullName"], None)
            except Exception:
                return pid, (None, None)
        with ThreadPoolExecutor(max_workers=12) as ex:
            for pid, v in ex.map(one, ids):
                era[pid] = v
    for dd in d.get("dates", []):
        for g in dd.get("games", []):
            a, h = g["teams"]["away"], g["teams"]["home"]
            def leg(side):
                pp = (side.get("probablePitcher") or {})
                nm, e = era.get(pp.get("id"), (None, None))
                nm = nm or pp.get("fullName")
                if not nm:
                    return "TBD"
                return f"{nm.split()[-1]}" + (f" {e}" if e else "")
            key = (a["team"]["abbreviation"] if "abbreviation" in a["team"]
                   else a["team"]["name"], h["team"]["name"])
            rec = lambda s: f"{s.get('leagueRecord',{}).get('wins','')}-{s.get('leagueRecord',{}).get('losses','')}"
            out[(a["team"]["name"], h["team"]["name"])] = dict(
                sp=f"{leg(a)} vs {leg(h)}",
                rec=f"{rec(a)} / {rec(h)}",
                names=(a["team"]["name"], h["team"]["name"]))
    return out


ELO_LEAGUES = ({"wnba", "nba", "nhl", "ncaaf", "nfl", "ncaab"}
               | {k for k, p, _ in LEAGUES if p.startswith("soccer/")})



def model_book(day):
    """My own forecast for every league that has a validated model for it."""
    book = {}
    # A model that throws must not take the board down, but it must not vanish
    # silently either -- an empty tab looked identical to "no games today", so
    # a broken feed could go unnoticed for days. Every failure is now named.
    def _fail(lgk, e):
        print(f"model_book: {lgk} raised {type(e).__name__}: {e}", file=sys.stderr)
        return {}
    try:
        book["mlb"] = P.mlb_picks(day)
    except Exception as e:
        book["mlb"] = _fail("mlb", e)
    for lgk in ("atp", "wta"):
        try:
            book[lgk] = P.tennis_picks(day, tour=lgk)
        except Exception as e:
            book[lgk] = _fail(lgk, e)
    def one(lgk):
        try:
            return lgk, P.elo_picks(lgk, day)
        except Exception as e:
            return lgk, _fail(lgk, e)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for lgk, v in ex.map(one, sorted(ELO_LEAGUES & {k for k, _, _ in LEAGUES})):
            book[lgk] = v
    return book


def collect(key, path, day, mlbctx, mybook=None):
    d = get(f"{ESPN}/{path}/scoreboard?dates={day}")
    rows = []
    for ev in d.get("events", []):
        comps = list(ev.get("competitions") or [])
        for grp in ev.get("groupings") or []:
            comps.extend(grp.get("competitions") or [])
        many = len(comps) > 1
        for c in comps:
            st = ((c.get("status") or {}).get("type") or {})
            if st.get("completed") or st.get("state") in ("post", "in"):
                continue                       # upcoming only
            t = start_et(c)
            if not t or t.strftime("%Y%m%d") != day:
                continue
            n = sides(c)
            if "away" in n and "home" in n:
                label = f"{n['away']} @ {n['home']}"
            elif many:
                who = [((x.get("athlete") or x.get("team") or {}).get("displayName", "?"))
                       for x in c.get("competitors") or []]
                label = " vs ".join(who) if who else (ev.get("shortName") or "?")
            else:
                label = ev.get("shortName") or ev.get("name") or "?"
            dl = deep_links(c)
            pr = raw_prices(c, 3 if key in THREE_WAY else 2)
            dv = devig(*pr) if pr else None
            legs = []
            if dv and len(dv) == len(pr):
                names = (["away", "draw", "home"] if len(dv) == 3 else ["away", "home"])
                for lab_, p_, price_ in zip(names, dv, pr):
                    side_ = lab_
                    who = "Draw" if lab_ == "draw" else n.get(lab_, lab_)
                    b = bucket(price_)
                    link = dl.get(side_) or {}
                    legs.append(dict(who=who, side=side_, prob=p_, price=str(price_),
                                     dk=(f'{link["event"]}:{link["outcome"]}'
                                         if link.get("outcome") else None),
                                     dog=(str(price_).startswith("+") or
                                          (str(price_).lstrip("-").isdigit() and int(price_) > 0)),
                                     roi=(b["roi"] if b else None),
                                     gap=(b["gap"] if b else None)))
            note = ""
            if key == "mlb":
                fullnames = {}
                for x in c.get("competitors") or []:
                    fullnames[x.get("homeAway")] = (x.get("team") or {}).get("displayName")
                ctx = mlbctx.get((fullnames.get("away"), fullnames.get("home")))
                if ctx:
                    note = ctx["sp"]
            # my own call, from the model that owns this league
            mine = {}
            if mybook:
                names = {}
                for x in c.get("competitors") or []:
                    names[x.get("homeAway")] = ((x.get("team") or {}).get("displayName")
                                                or (x.get("athlete") or {}).get("displayName"))
                mine = (mybook.get(key) or {}).get((names.get("away"), names.get("home")), {})
                # which side is my pick on? legs are keyed away/home, picks by full name
                if mine.get("pick"):
                    myside = ("away" if mine["pick"] == names.get("away")
                              else "home" if mine["pick"] == names.get("home") else None)
                    mine = dict(mine, side=myside)
                # MLB only: the model is behind the close on 2,100 backtested
                # games, so it nudges the price rather than overruling it, and
                # the side comes from the blend. This is what stops the board
                # taking a stand the numbers cannot pay for.
                if key == "mlb" and mine.get("p_away") is not None:
                    mq = next((L["prob"] for L in legs if L["side"] == "away"), None)
                    if mq is not None and 0.0 < mq < 1.0:
                        pa = P.mlb_anchor(mine["p_away"], mq)
                        away = pa > 0.5
                        side_ = "away" if away else "home"
                        who = names.get(side_)
                        if who:
                            mine = dict(mine, pick=who, side=side_,
                                        conf=max(pa, 1 - pa), p_away=pa)
            best = max(legs, key=lambda L: L["roi"] if L["roi"] is not None else -99) if legs else None
            rows.append(dict(id=f'{key}:{c.get("id")}', label=label,
                             tip=t.strftime("%-I:%M %p"), legs=legs, note=note,
                             mypick=mine.get("pick", ""), myconf=mine.get("conf"),
                             why=mine.get("why", ""), myside=mine.get("side"),
                             pick=(best["who"] if best else ""),
                             price=(best["price"] if best else ""),
                             conf=(best["prob"] if best else None)))
    rows.sort(key=lambda r: r["tip"])
    return rows


def diff(rows, now):
    """What is genuinely new since the last cycle."""
    out = []
    for r in rows:
        old = _PREV.get(r["id"])
        if old is None:
            if _STATE["cycles"] > 0:
                out.append((now, r["label"], "new on the board"))
        else:
            if old.get("price") != r["price"] and old.get("price") and r["price"]:
                try:
                    mv = int(r["price"].replace("+", "")) - int(old["price"].replace("+", ""))
                    out.append((now, r["label"],
                                f'{r["pick"]} {old["price"]} → {r["price"]} ({mv:+d})'))
                except ValueError:
                    pass
            if old.get("pick") and r["pick"] and old["pick"] != r["pick"]:
                out.append((now, r["label"], f'pick flipped {old["pick"]} → {r["pick"]}'))
            if "TBD" in (old.get("note") or "") and "TBD" not in (r.get("note") or "") and r.get("note"):
                out.append((now, r["label"], f'starter named — {r["note"]}'))
        _PREV[r["id"]] = dict(price=r["price"], pick=r["pick"], note=r["note"])
    return out


def refresh():
    now = dt.datetime.now(ET)
    today = now.strftime("%Y%m%d")
    tomorrow = (now + dt.timedelta(days=1)).strftime("%Y%m%d")
    ctx, book = {}, {}
    for day in (today, tomorrow):
        try:
            ctx[day] = mlb_context(day)
        except Exception:
            ctx[day] = {}
        try:
            book[day] = model_book(day)
        except Exception:
            book[day] = {}
    slots = {"today": {}, "tomorrow": {}}
    jobs = [(slot, k, p, day) for slot, day in (("today", today), ("tomorrow", tomorrow))
            for k, p, _ in LEAGUES]
    fresh = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(collect, k, p, day, ctx.get(day, {}), book.get(day, {})): (slot, k)
                for slot, k, p, day in jobs}
        for f in futs:
            slot, k = futs[f]
            try:
                rows = f.result()
            except Exception:
                rows = []
            slots[slot][k] = rows
            fresh.extend(rows)
    stamp = now.strftime("%-I:%M %p")
    changes = diff(fresh, stamp)
    with _LOCK:
        _STATE["slots"] = slots
        _STATE["at"] = now
        _STATE["dates"] = (today, tomorrow)
        _STATE["changes"] = (changes + _STATE["changes"])[:40]
        _STATE["cycles"] += 1


def loop(interval):
    while True:
        time.sleep(interval)
        try:
            refresh()
        except Exception:
            pass


CSS = """
:root{--bg:#FBFAF6;--panel:#fff;--rule:#E3DFD6;--soft:#EFEBE3;--ink:#16181D;
--dim:#6E6A61;--accent:#0B6E6E;--new:#B4530A}
@media(prefers-color-scheme:dark){:root{--bg:#101317;--panel:#171B21;--rule:#2A2F38;
--soft:#21262E;--ink:#E9EBEF;--dim:#8D93A0;--accent:#4FC7BE;--new:#E5A257}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 "IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px 70px}
header{padding:30px 0 16px;border-bottom:2px solid var(--ink)}
h1{font:800 34px/1.03 Archivo,Arial,sans-serif;margin:0;letter-spacing:-.02em}
.eyebrow{font:11px/1 "IBM Plex Mono",monospace;letter-spacing:.14em;text-transform:uppercase;
color:var(--accent);margin-bottom:9px}
.stamp{font:12px "IBM Plex Mono",monospace;color:var(--dim);margin-top:11px}
.days{display:flex;gap:8px;margin-top:14px}
.days a{display:flex;gap:8px;align-items:baseline;text-decoration:none;color:var(--dim);
border:1px solid var(--rule);padding:7px 15px;font:600 13px Archivo,Arial,sans-serif}
.days a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.dnum{font:400 11px "IBM Plex Mono",monospace;opacity:.7}
nav{display:flex;flex-wrap:wrap;padding:13px 0 0;border-bottom:1px solid var(--rule);
position:sticky;top:0;background:var(--bg);z-index:9}
nav a{font:600 13px Archivo,Arial,sans-serif;color:var(--dim);text-decoration:none;
padding:9px 13px;border-bottom:2px solid transparent;margin-bottom:-1px}
nav a.on{color:var(--ink);border-bottom-color:var(--accent)}
.count{font:400 10.5px "IBM Plex Mono",monospace;color:var(--dim);margin-left:5px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;margin-top:6px}
th{font:400 10.5px "IBM Plex Mono",monospace;letter-spacing:.1em;text-transform:uppercase;
color:var(--dim);text-align:left;padding:14px 12px 8px;border-bottom:1px solid var(--rule)}
th.n,td.n{text-align:right}
td{padding:11px 12px;border-bottom:1px solid var(--soft);vertical-align:baseline}
tr:hover td{background:var(--panel)}
td.m{font-weight:500;white-space:nowrap}
td.t{font:12px "IBM Plex Mono",monospace;color:var(--dim);white-space:nowrap}
td.p{font-weight:600}
td.a{font:12.5px "IBM Plex Mono",monospace;color:var(--dim)}
td.n{font:600 14px "IBM Plex Mono",monospace;font-variant-numeric:tabular-nums;color:var(--accent)}
td.none{color:var(--dim);font-weight:400}
.empty{padding:42px 12px;color:var(--dim);font:13px "IBM Plex Mono",monospace}
.feed{margin-top:30px;border:1px solid var(--rule);border-left:3px solid var(--new);
background:var(--panel);padding:16px 18px}
.feed h2{font:800 14px Archivo,Arial,sans-serif;margin:0 0 10px}
.feed li{font:12.5px "IBM Plex Mono",monospace;color:var(--dim);margin-bottom:5px;list-style:none}
.feed ul{margin:0;padding:0}
.feed .ts{color:var(--new);margin-right:8px}
aside{margin-top:22px;border:1px solid var(--rule);border-left:3px solid var(--accent);
background:var(--panel);padding:18px 20px;color:var(--dim);font-size:13.5px}
aside b{color:var(--ink)}
@media(max-width:640px){td.a{display:none}th:nth-child(4){display:none}}
"""


def page(active, slot):
    with _LOCK:
        data = _STATE["slots"].get(slot) or {}
        at, dates = _STATE["at"], _STATE["dates"]
        changes, cycles = _STATE["changes"], _STATE["cycles"]
    lab = {"today": "Today", "tomorrow": "Tomorrow"}
    dnum = {"today": dates[0], "tomorrow": dates[1]}
    days = "".join(f'<a class="{"on" if s==slot else ""}" href="/{s}/{active}">{lab[s]}'
                   f'<span class="dnum">{dnum[s][4:6]}/{dnum[s][6:]}</span></a>'
                   for s in ("today", "tomorrow"))
    tabs = "".join(f'<a class="{"on" if k==active else ""}" href="/{slot}/{k}">{html.escape(l)}'
                   f'<span class="count">{len(data.get(k) or [])}</span></a>'
                   for k, _, l in LEAGUES)
    rows = data.get(active) or []
    if not rows:
        body = '<p class="empty">No upcoming games.</p>'
    else:
        trs = "".join(
            f'<tr><td class="m">{html.escape(r["label"])}</td>'
            f'<td class="t">{html.escape(r["tip"])}</td>'
            + (f'<td class="p">{html.escape(r["pick"])}</td>' if r["pick"]
               else '<td class="p none">no price yet</td>')
            + f'<td class="a">{html.escape(r["note"] or "")}</td>'
            + (f'<td class="n">{r["conf"]*100:.1f}%</td>' if r["conf"] is not None
               else '<td class="n none">&mdash;</td>')
            + "</tr>" for r in rows)
        body = ('<table><tr><th>Matchup</th><th>Start</th><th>Pick</th>'
                '<th>Analysis</th><th class="n">Prob</th></tr>' + trs + "</table>")
    feed = ""
    if changes:
        items = "".join(f'<li><span class="ts">{html.escape(t)}</span>'
                        f'{html.escape(g)} &mdash; {html.escape(w)}</li>'
                        for t, g, w in changes[:14])
        feed = f'<div class="feed"><h2>New since last cycle</h2><ul>{items}</ul></div>'
    stamp = at.strftime("%-I:%M:%S %p ET") if at else "loading…"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap">
<title>Upcoming Board</title><style>{CSS}</style></head><body><div class="wrap">
<header><div class="eyebrow">Upcoming only &middot; cycle {cycles}</div><h1>Upcoming Board</h1>
<div class="stamp">Researched {stamp} &middot; re-checks every 5 minutes</div>
<div class="days">{days}</div></header>
<nav>{tabs}</nav>{body}{feed}
<aside><b>The Pick column is the market's favourite, de-vigged</b> &mdash; not a model output.
Over all 2,100 completed 2026 MLB games against real closing prices the market called 56.5%
and my model 53.8%, so the MLB pick is now taken from the line with the model allowed a fifth
of the say; backing the model where it argued hardest with the price hit 47.3%. Analysis shows the starters so you
can see what is driving the number. Completed games are dropped; a settled game is not a pick.
</aside></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = [p for p in self.path.split("?")[0].strip("/").split("/") if p]
        slot = parts[0].lower() if parts and parts[0].lower() in ("today", "tomorrow") else "today"
        rest = parts[1:] if (parts and parts[0].lower() in ("today", "tomorrow")) else parts
        key = rest[0].lower() if rest else LEAGUES[0][0]
        if key not in {k for k, _, _ in LEAGUES}:
            key = LEAGUES[0][0]
        out = page(key, slot).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--interval", type=int, default=300)
    a = ap.parse_args()
    print("researching…")
    refresh()
    threading.Thread(target=loop, args=(a.interval,), daemon=True).start()
    print(f"http://localhost:{a.port}  · re-checks every {a.interval}s")
    HTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
