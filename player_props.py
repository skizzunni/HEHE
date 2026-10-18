"""Player and team props from DraftKings, via ESPN's odds feed.

    python3 player_props.py nfl 401872995     # one event, printed

WHAT THE FEED CARRIES (probed 2026-10-15)

  * NFL: ~1,650 prop prices a game -- receiving / rushing / passing yards
    milestones ("50+"), receptions, anytime and 2+ touchdown scorer, etc.
    Plain over/under player lines come with the LINE ONLY, no price, so they
    cannot be priced and are skipped.
  * NHL: team totals (excl. OT), both teams to score, period lines. No player
    props yet, and the team totals carry no over/under marker, so they are not
    used (the Markets tab prices team totals from the game model instead).
  * Soccer: anytime goalscorer, shots / shots on target milestones, cards.
  * NBA, college football: none posted yet (the endpoint 404s); picked up
    automatically when they appear.

HOW A PROP IS PRICED

Milestone and scorer props are one-sided -- the book prices "yes" only -- so
there is no second side to de-vig against. The implied probability is divided
by an ASSUMED 7% margin. That figure is a typical one-sided hold, not
something measured here, and props have no backtest: ESPN keeps closing game
lines for finished games but not prop prices. So prop probabilities are the
book's opinion, lightly adjusted, and are labelled unvalidated on the page.
"""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import props_ledger

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "props")
NAMES = os.path.join(HERE, ".cache", "athletes.json")
CORE = "https://sports.core.api.espn.com/v2/sports"
TTL = 1800                   # props move slowly; refetch each half hour
ONE_SIDED_HOLD = 1.07        # assumed, see the docstring
SKIP = ("Quarter", "Half", "Period", "First ", "Last ", "Longest", "Will There",
        "Moneyline", "Spread", "Corner", "Left Foot", "Right Foot", "Header",
        "Red Card", "Offsides", "Fouls")

# board league key -> (ESPN sport, ESPN league)
LEAGUES = {
    "nfl": ("football", "nfl"), "ncaaf": ("football", "college-football"),
    "nba": ("basketball", "nba"), "ncaab": ("basketball", "mens-college-basketball"),
    "wnba": ("basketball", "wnba"), "nhl": ("hockey", "nhl"),
    "mlb": ("baseball", "mlb"),
    "epl": ("soccer", "eng.1"), "esp": ("soccer", "esp.1"), "ger": ("soccer", "ger.1"),
    "ita": ("soccer", "ita.1"), "fra": ("soccer", "fra.1"), "mls": ("soccer", "usa.1"),
    "ucl": ("soccer", "uefa.champions"), "uel": ("soccer", "uefa.europa"),
}


def get(url):
    for _ in range(2):
        try:
            with urllib.request.urlopen(url.replace("http://", "https://"), timeout=25) as r:
                return json.load(r)
        except Exception:
            continue
    return None


_names = None


def names():
    global _names
    if _names is None:
        try:
            with open(NAMES) as fh:
                _names = json.load(fh)
        except (OSError, ValueError):
            _names = {}
    return _names


def save_names():
    if _names is not None:
        os.makedirs(os.path.dirname(NAMES), exist_ok=True)
        with open(NAMES, "w") as fh:
            json.dump(_names, fh)


def resolve(refs):
    """$ref URL -> display name, fetched once and kept forever."""
    nm = names()
    todo = [r for r in set(refs) if r and r.split("?")[0] not in nm]
    def one(r):
        d = get(r) or {}
        return r.split("?")[0], d.get("displayName") or d.get("shortDisplayName")
    with ThreadPoolExecutor(max_workers=16) as ex:
        for k, v in ex.map(one, todo):
            if v:
                nm[k] = v
    return lambda r: nm.get((r or "").split("?")[0])


def raw_items(league, eid):
    """Every prop item for an event, cached for TTL seconds."""
    if league not in LEAGUES:
        return []
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f"{league}-{eid}.json")
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < TTL:
        with open(f) as fh:
            return json.load(fh)
    sport, lg = LEAGUES[league]
    base = (f"{CORE}/{sport}/leagues/{lg}/events/{eid}/competitions/{eid}"
            f"/odds/100/propBets")
    # limit=1000 returns a whole NFL game (~1,650 items) in two pages; asking
    # for more than 1000 silently falls back to pages of 25
    first = get(f"{base}?limit=1000&page=1")
    if not first:
        items = []
    else:
        items = list(first.get("items") or [])
        pages = int(first.get("pageCount") or 1)
        with ThreadPoolExecutor(max_workers=16) as ex:
            for d in ex.map(lambda p: get(f"{base}?limit=1000&page={p}"),
                            range(2, pages + 1)):
                items.extend((d or {}).get("items") or [])
    with open(f, "w") as fh:
        json.dump(items, fh)
    return items


def american_prob(a):
    if str(a).strip().upper() == "EVEN":
        a = "+100"
    try:
        v = float(str(a).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def parse(items, who, hold=ONE_SIDED_HOLD, league=None):
    """Priced, full-game props -> [dict(name, market, line, price, p)]."""
    out = []
    for x in items:
        t = (x.get("type") or {}).get("name") or ""
        if any(s in t for s in SKIP):
            continue
        cur = x.get("current") or {}
        # Only prices that name their side. Team-total items carry a bare
        # price with no over/under marker; guessing the side could put the
        # wrong bet on a ticket, so they are left out.
        price = (cur.get("over") or {}).get("american")
        imp = american_prob(price)
        if imp is None:
            continue                            # line only, no price
        target = cur.get("target") or {}
        line = target.get("displayValue") or (str(target.get("value"))
                                              if target.get("value") is not None else "")
        ref = (x.get("athlete") or x.get("team") or {}).get("$ref")
        name = who(ref) if ref else None
        aid = re.search(r"/athletes/(\d+)", ref or "")
        if not name:
            continue
        market = t.replace(" (incl. overtime)", "").replace(" Milestones", "")
        label = f"{name}: {line} {market}".replace("  ", " ") if line else f"{name}: {market}"
        # the margin is re-fitted per league from graded props (props_ledger)
        out.append(dict(name=name, market=market, line=line, price=str(price),
                        imp=round(imp, 4), aid=aid.group(1) if aid else None,
                        p=round(min(imp / (props_ledger.hold(league, market) if league else hold),
                                    0.99), 4), label=label.strip()))
    # one entry per (player, market, line): the feed repeats some
    seen, uniq = set(), []
    for o in out:
        k = (o["name"], o["market"], o["line"])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    uniq.sort(key=lambda o: -o["p"])
    return uniq


def for_slot(board_slot, labels=None, max_games=40):
    """Props for every game on a board slot that has them."""
    jobs = []
    for league, rows in (board_slot or {}).items():
        if league not in LEAGUES:
            continue
        for row in rows:
            eid = row["id"].split(":", 1)[1]
            jobs.append((league, eid, row))
    jobs = jobs[:max_games]
    with ThreadPoolExecutor(max_workers=6) as ex:
        raws = list(ex.map(lambda j: raw_items(j[0], j[1]), jobs))
    refs = [((x.get("athlete") or x.get("team") or {}).get("$ref"))
            for items in raws for x in items]
    who = resolve(refs)
    save_names()
    # FanDuel's own player props, for every league it lists (fd_props.py);
    # ESPN's feed only carries football
    import fanduel
    import fd_props
    try:
        FD = fanduel.load()
    except Exception:
        FD = {}
    fd_jobs = []
    for league, rows in (board_slot or {}).items():
        if league not in fd_props.SPORT:
            continue
        for row in rows:
            m = row.get("mkt") or {}
            g = fanduel.find(FD, league, m.get("away"), m.get("home"))
            if g:
                fd_jobs.append((league, row, g))
    fd_jobs = fd_jobs[:max_games]
    with ThreadPoolExecutor(max_workers=6) as ex:
        fd_raw = list(ex.map(lambda j: fd_props.for_game(j[2], j[0]), fd_jobs))
    fd_by_row = {row["id"]: props for (league, row, g), props in zip(fd_jobs, fd_raw)}
    for league, row, g in fd_jobs:
        if row["id"] not in {r["id"] for _, _, r in jobs}:
            jobs.append((league, row["id"].split(":", 1)[1], row))
            raws.append([])
    out = []
    for (league, eid, row), items in zip(jobs, raws):
        # keep the page small: the 60 likeliest props worth stacking per game
        merged, seen = [], set()
        # FanDuel first: the same book the locks and lottery use
        for p in list(fd_by_row.get(row["id"]) or []) + parse(items, who, props_ledger.hold(league), league):
            k = (props_ledger.norm_name(p["name"]), p["market"], str(p["line"]))
            if k in seen:
                continue
            seen.add(k)
            merged.append(p)
        merged.sort(key=lambda o: -o["p"])
        props = [dict(p, gid=row["id"]) for p in merged
                 if 0.30 <= p["p"] <= 0.97 and props_ledger.offered(league, p["market"])][:60]
        if props:
            out.append(dict(id=row["id"], lg=(labels or {}).get(league, league),
                            match=row.get("label", ""), tip=row.get("tip"),
                            props=props))
    return out


def prop_tickets(games, tiers=(2, 3, 4, 6, 8), lo=0.75, hi=0.93, variants=3):
    """Prop-only stacks: one prop per game, so legs come from different games
    and are independent. Props near 85% preferred."""
    pool = []
    for g in games:
        # only props the box score can settle: an ungradable leg leaves the
        # ticket open forever and its market's margin is never re-fitted
        lg = g["id"].split(":", 1)[0]
        best = [p for p in g["props"] if lo <= p["p"] <= hi and props_ledger.gradable(lg, p["market"])]
        best.sort(key=lambda p: abs(p["p"] - 0.85))
        if best:
            pool.append((g, best))
    out = {}
    for n in tiers:
        made, used = [], {}
        for v in range(variants):
            order = sorted(pool, key=lambda gb: (used.get(gb[0]["id"], 0),
                                                 abs(gb[1][0]["p"] - 0.85)))
            if len(order) < n:
                break
            legs, prob = [], 1.0
            for g, best in order[:n]:
                pick = best[min(used.get(g["id"], 0), len(best) - 1)]
                legs.append(dict(pick, match=g["match"], lg=g["lg"]))
                prob *= pick["p"]
                used[g["id"]] = used.get(g["id"], 0) + 1
            sig = tuple(sorted(L["label"] for L in legs))
            if any(t["sig"] == sig for t in made):
                continue
            made.append(dict(sig=sig, n=n, prob=round(prob, 4),
                             fair=round(1 / prob, 2), legs=legs))
        for t in made:
            t.pop("sig")
        out[n] = made
    return out


def _dec(price):
    try:
        v = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


FILL_PER_GAME = 4


def mega_ticket(games, n=25, dec_lo=1.25, dec_hi=1.834, per_game=2):
    """The 25 likeliest FanDuel player props of the day, every sport together.

    Same rule as the locks: normal odds only (-400 to -120), likeliest first
    (a ladder rung's main-line fair chance where it beats the price), one
    prop per player, at most `per_game` from any game (FanDuel takes the
    same-game ones as SGP+). Recorded and graded like every prop."""
    pool = []
    for g in games or []:
        for P in g.get("props") or []:
            d = _dec(P.get("price"))
            if not P.get("fd") or not d or not dec_lo <= d <= dec_hi:
                continue
            if not props_ledger.gradable(g["id"].split(":", 1)[0], P["market"]):
                continue
            p = P["p"]                     # the price, not the ladder model (see locks.py)
            pool.append(dict(P, p=round(p, 4), dec=d, match=g["match"], lg=g["lg"],
                             tip=g.get("tip"), gid=g["id"]))
    pool.sort(key=lambda P: -P["p"])
    legs, players, per = [], set(), {}
    # per_game first; on a light slate (FanDuel posting props for only a few
    # games) a second pass lets a game give up to FILL_PER_GAME players
    for cap in (per_game, FILL_PER_GAME):
        for P in pool:
            if len(legs) >= n:
                break
            who = props_ledger.norm_name(P["name"])
            if who in players or per.get(P["gid"], 0) >= cap:
                continue
            legs.append(P)
            players.add(who)
            per[P["gid"]] = per.get(P["gid"], 0) + 1
    if not legs:
        return None
    prob, pay = 1.0, 1.0
    for L in legs:
        prob *= L["p"]
        pay *= L["dec"]
    return dict(n=len(legs), prob=round(prob, 6), fair=round(1 / prob, 2), pays=round(pay, 1),
                legs=legs)


if __name__ == "__main__":
    lg, eid = sys.argv[1], sys.argv[2]
    items = raw_items(lg, eid)
    who = resolve([((x.get("athlete") or x.get("team") or {}).get("$ref")) for x in items])
    save_names()
    for p in parse(items, who)[:60]:
        print(f'{100*p["p"]:5.1f}%  {p["price"]:>6}  {p["label"]}')
