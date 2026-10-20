"""Player props from FanDuel (New York), for every league FanDuel lists.

ESPN's prop feed (player_props.py) only carries football, so hockey,
basketball and baseball games came up empty. FanDuel posts them all on each
game's own page, in tabs (probed 2026-10-16, round 19). Four shapes:

  over/under  market "Jayson Tatum - Pts + Reb + Ast", runners
              "Jayson Tatum Over" / "... Under", the line in `handicap`.
              Both sides priced, so the chance is de-vigged exactly.
  ladder      market "Nico Collins - Alt Receiving Yds", runners
              "Nico Collins 50+ Yards" -- one-sided milestones.
  milestone   market "To Score 25+ Points" / "3+ Made Threes", runners are
              player names -- one-sided.
  scorer      "Any Time Touchdown Scorer", "Anytime Goal Scorer" -- names.

One-sided prices are divided by the league's graded prop margin
(props_ledger.hold), the same rule the ESPN props use. Only full-game
markets whose stat the box score can settle are kept, so every prop shown
is graded (props_ledger) and goes through the daily review.
"""
import json
import os
import re
import time

import fanduel
import props_ledger

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "fd_props")
TTL = 600
# tabs worth opening, by words in their titles
TAB_WORDS = ("player", "passing", "receiving", "rushing", "td scorer", "touchdown",
             "goalscorer", "goal scorer", "shots", "points", "rebounds", "assists",
             "threes", "combos", "batter", "pitcher", "hits", "strikeouts", "props",
             "scoring")          # football: anytime TD scorers live under "Scoring"
SKIP_TAB = ("live", "quarter", "half", "period", "inning", "1st", "2nd", "3rd", "4th",
            "parlay", "same game", "team", "game props", "specials", "quick")
SKIP_MARKET = re.compile(r"quarter|half|period|inning|1st|2nd|3rd|4th|first|last|most |"
                         r"either player|longest|double double|triple double|"
                         r"team|alt total|specials|odd/even|correct score|single|double|"
                         r"triple|stolen|total bases|walk", re.I)

# words in a market name -> (canonical market per sport, as props_ledger knows it)
STATS = {
    "football": [(r"rushing \+ receiving", "Rushing + Receiving Yards"),
                 (r"passing (yds|yards)", "Passing Yards"),
                 (r"passing (tds|touchdowns)", "Passing Touchdowns"),
                 (r"receiving (yds|yards)", "Receiving Yards"),
                 (r"receptions", "Receptions"),
                 (r"rushing (yds|yards)", "Rushing Yards"),
                 (r"touchdown scorer|to score .*touchdown", "Anytime Touchdown Scorer")],
    "basketball": [(r"pts \+ reb \+ ast|points \+ rebounds \+ assists", "Pts + Reb + Ast"),
                   (r"pts \+ reb|points \+ rebounds", "Pts + Reb"),
                   (r"pts \+ ast|points \+ assists", "Pts + Ast"),
                   (r"reb \+ ast|rebounds \+ assists", "Reb + Ast"),
                   (r"threes|3 point", "Threes Made"),
                   (r"rebounds|\breb\b", "Rebounds"),
                   (r"assists|\bast\b", "Assists"),
                   (r"points|\bpts\b", "Points")],
    "hockey": [(r"shots on goal|\bshots\b", "Shots on Goal"),
               (r"goal ?scorer|to score .*goal", "Goals"),
               (r"saves", "Goalkeeper Saves"),
               (r"assists", "Assists"),
               (r"points", "Points")],
    "baseball": [(r"strikeouts", "Strikeouts Thrown"),
                 (r"home run", "Home Runs"),
                 (r"hits \+ runs \+ rbis", "Hits + Runs + RBIs"),
                 (r"\brbis?\b", "RBIs"),
                 (r"\bhits?\b", "Hits"),
                 (r"\bruns?\b", "Runs")],
}
SPORT = {"nfl": "football", "ncaaf": "football", "nba": "basketball", "wnba": "basketball",
         "ncaab": "basketball", "nhl": "hockey", "mlb": "baseball"}
NUM = re.compile(r"(\d+(?:\.\d+)?)\s*\+")


def _odds(r):
    o = ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")
    return o


def _imp(o):
    try:
        v = float(o)
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def _stat(sport, text):
    t = text.lower()
    for pat, name in STATS.get(sport, []):
        if re.search(pat, t):
            # a combined market ("Hits + Runs + RBIs") must never be read as
            # one of its parts: it would be graded on that part alone
            if " + " in t and "+" not in name:
                return None
            return name
    return None


def parse(markets, league, hold):
    """FanDuel markets of one game -> [prop dict] in player_props' shape."""
    sport = SPORT.get(league)
    out = []
    for m in (markets or {}).values():
        mn = m.get("marketName") or ""
        if SKIP_MARKET.search(mn) or SKIP_MARKET.search(m.get("marketType") or ""):
            continue
        runners = m.get("runners") or []
        mid = m.get("marketId")
        # over/under: "Player - Stat", runners "Player Over" / "Player Under"
        ou = {}
        for r in runners:
            nm = r.get("runnerName") or ""
            mo = re.match(r"^(.*)\s+(Over|Under)$", nm)
            if mo:
                ou[mo.group(2).lower()] = (mo.group(1), r)
        if ou and " - " in mn:
            stat = _stat(sport, mn.split(" - ", 1)[1])
            if not stat or "over" not in ou or "under" not in ou:
                continue
            (who, ro), (_, ru) = ou["over"], ou["under"]
            io, iu = _imp(_odds(ro)), _imp(_odds(ru))
            line = ro.get("handicap")
            if not io or not iu or line is None:
                continue
            import devig
            po = devig.fair_implied(io, iu)[0]
            for side, r, p, ln in (("Over", ro, po, f"{float(line):g}"),
                                   ("Under", ru, 1 - po, f"u{float(line):g}")):
                o = _odds(r)
                out.append(dict(name=who, market=stat, line=ln, price=f"+{o}" if o > 0 else str(o),
                                imp=round(_imp(o), 4), p=round(min(p, 0.99), 4), aid=None,
                                label=f"{who}: {side} {float(line):g} {stat}",
                                fd=f"{mid}:{r.get('selectionId')}",
                                where=f"{mn}: {r.get('runnerName')}"))
            continue
        # one-sided: ladders ("Player 50+ Yards"), milestones and scorers (names)
        stat = _stat(sport, mn)
        if not stat:
            continue
        need = NUM.search(mn)
        for r in runners:
            nm = (r.get("runnerName") or "").strip()
            o = _odds(r)
            i = _imp(o)
            if not nm or i is None:
                continue
            ln = None
            ml = re.match(r"^(.*?)\s+(\d+(?:\.\d+)?)\+\s+\S.*$", nm)       # ladder rung
            if ml and " - " in mn:
                who, ln = ml.group(1), f"{float(ml.group(2)):g}+"
            else:
                who = nm
                if need:
                    ln = f"{float(need.group(1)):g}+"
                elif re.search(r"scorer|to score|to (record|hit) an? ", mn, re.I):
                    ln = "1+"
            if not ln or " or " in who or who.lower().startswith("no "):
                continue
            out.append(dict(name=who, market=stat, line=ln, price=f"+{o}" if o > 0 else str(o),
                            imp=round(i, 4), p=round(min(i / props_ledger.hold(league, stat), 0.99), 4),
                            aid=None,
                            label=f"{who}: {ln} {stat}",
                            fd=f"{mid}:{r.get('selectionId')}", where=f"{mn}: {nm}"))
    consistency(out)
    # one entry per (player, market, line)
    seen, uniq = set(), []
    for o in sorted(out, key=lambda o: -o["p"]):
        k = (props_ledger.norm_name(o["name"]), o["market"], o["line"])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


# ------------------------------------------------------- ladder consistency
# FanDuel's main over/under for a player is two-sided and the most-bet line,
# so de-vigged it is the sharpest number on the page. The alternate rungs
# ("50+ Yards", "3+ Made Threes", "25+ Points") are priced on their own. From
# the main line the player's whole distribution follows -- Poisson for counts,
# a normal with the stat's usual spread for yards and points -- and every
# rung can be priced from it. Where a rung pays more than that, it is cheap.
# p_fair is recorded with each prop and graded, so the daily review measures
# whether it really wins more often than its price (it is NOT assumed to).
import math

COUNTS = {"Receptions", "Passing Touchdowns", "Anytime Touchdown Scorer", "Threes Made",
          "Assists", "Rebounds", "Goals", "Shots on Goal", "Hits", "Home Runs", "RBIs",
          "Runs", "Strikeouts Thrown", "Goalkeeper Saves"}
CV = {"Passing Yards": 0.30, "Rushing Yards": 0.55, "Receiving Yards": 0.70,
      "Rushing + Receiving Yards": 0.50, "Points": 0.32, "Pts + Reb + Ast": 0.25,
      "Pts + Reb": 0.28, "Pts + Ast": 0.28, "Reb + Ast": 0.35}


def _pois_ge(lam, k):
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    term, cdf = math.exp(-lam), 0.0
    for i in range(int(k)):
        cdf += term
        term *= lam / (i + 1)
    return max(0.0, 1 - cdf)


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _solve(f, target, lo, hi):
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fair_at_least(stat, line, p_over, k):
    """Chance of k or more, given P(stat > line) = p_over from the main line."""
    if stat in COUNTS:
        lam = _solve(lambda l: _pois_ge(l, math.floor(line) + 1), p_over, 1e-4, 60)
        return _pois_ge(lam, k)
    cv = CV.get(stat)
    if not cv:
        return None
    # mean m with sd = cv*m such that P(X > line) = p_over
    m = _solve(lambda m: 1 - _ncdf((line - m) / max(cv * m, 1e-6)), p_over, 0.01, line * 4 + 10)
    return 1 - _ncdf((k - 0.5 - m) / max(cv * m, 1e-6))


def consistency(props):
    """Give every rung that shares a player and stat with a main over/under
    its fair chance from that line (p_fair) and the edge at its price."""
    main = {}
    for o in props:
        ln = str(o["line"])
        if not ln.endswith("+") and not ln.startswith("u"):
            try:
                main[(props_ledger.norm_name(o["name"]), o["market"])] = (float(ln), o["p"])
            except ValueError:
                pass
    for o in props:
        ln = str(o["line"])
        if not ln.endswith("+"):
            continue
        m = main.get((props_ledger.norm_name(o["name"]), o["market"]))
        if not m:
            continue
        try:
            k = float(ln[:-1])
        except ValueError:
            continue
        f = fair_at_least(o["market"], m[0], m[1], k)
        if f is None or not 0.01 < f < 0.995:
            continue
        o["p_fair"] = round(f, 4)
        o["edge"] = round(100 * (f / o["imp"] - 1), 1) if o.get("imp") else None


def for_game(g, league):
    """Props for one FanDuel game, cached TTL seconds."""
    if not g or not g.get("id") or league not in SPORT:
        return []
    f = os.path.join(CACHE, f'{league}-{g["id"]}.json')
    try:
        if time.time() - os.path.getmtime(f) < TTL:
            with open(f) as fh:
                return _stamped(json.load(fh), f)
    except (OSError, ValueError):
        pass
    base = (f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={g['id']}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    d = fanduel._get(base)
    tabs = ((d or {}).get("layout") or {}).get("tabs") or {}
    titles = [t.get("title") or "" for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
    markets = {}
    for t in titles:
        tl = t.lower()
        if any(w in tl for w in SKIP_TAB) or not any(w in tl for w in TAB_WORDS):
            continue
        p = fanduel._get(base + "&tab=" + tl.replace(" ", "-"))
        markets.update(((p or {}).get("attachments") or {}).get("markets") or {})
    props = parse(markets, league, props_ledger.hold(league))
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(f, "w") as fh:
            json.dump(props, fh)
    except OSError:
        pass
    return _stamped(props, f)


def _stamped(props, f):
    """Each prop with the time FanDuel's page was read (the cache file's)."""
    import datetime as dt
    try:
        q = dt.datetime.fromtimestamp(os.path.getmtime(f), dt.timezone.utc).isoformat(timespec="seconds")
    except OSError:
        q = None
    return [dict(p, quoted=q) for p in props]
