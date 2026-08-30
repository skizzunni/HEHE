"""Universal slate fetcher: any sport, any date, with de-vigged market prices.

    python3 slate.py mlb
    python3 slate.py ufc                 # full fight card, not just the main event
    python3 slate.py epl                 # 3-way market, draw included
    python3 slate.py nfl --date 20260906
    python3 slate.py --all               # every league that has something on

Pulls ESPN's public scoreboard feed (no key). Where a book has posted a price,
the de-vigged probability is shown. That number is the sharpest public forecast
available for most events -- it is the baseline a model has to beat, not a
starting point to argue with.

Times are US Eastern, as ESPN returns them.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request

BASE = "https://site.api.espn.com/apis/site/v2/sports"

LEAGUES = {
    "mlb":    ("baseball/mlb", "MLB", 2),
    "nfl":    ("football/nfl", "NFL", 2),
    "ncaaf":  ("football/college-football", "NCAA Football", 2),
    "nba":    ("basketball/nba", "NBA", 2),
    "wnba":   ("basketball/wnba", "WNBA", 2),
    "ncaab":  ("basketball/mens-college-basketball", "NCAA Basketball", 2),
    "nhl":    ("hockey/nhl", "NHL", 2),
    "pga":    ("golf/pga", "PGA Tour", 0),
    "lpga":   ("golf/lpga", "LPGA", 0),
    "ufc":    ("mma/ufc", "UFC", 2),
    "epl":    ("soccer/eng.1", "Premier League", 3),
    "mls":    ("soccer/usa.1", "MLS", 3),
    "laliga": ("soccer/esp.1", "La Liga", 3),
    "ucl":    ("soccer/uefa.champions", "Champions League", 3),
    "atp":    ("tennis/atp", "ATP Tennis", 2),
    "wta":    ("tennis/wta", "WTA Tennis", 2),
}

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass

# ESPN posts these strings when a market is suspended or not yet open.
_NO_PRICE = {"OFF", "EVEN", "-", "", "N/A", "PK"}


def fetch(path, date=None):
    url = f"{BASE}/{path}/scoreboard"
    if date:
        url += f"?dates={date}"
    try:
        with urllib.request.urlopen(url, timeout=45, context=_CTX) as r:
            return json.load(r)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        raise RuntimeError(f"ESPN unreachable for '{path}' ({e})") from e


def am_to_dec(o):
    """American odds -> decimal. Returns None for non-numeric ESPN placeholders."""
    if o is None:
        return None
    s = str(o).strip().upper().replace("+", "")
    if s in _NO_PRICE or not s.lstrip("-").isdigit():
        return None
    v = int(s)
    if v == 0:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def devig(*odds):
    """Proportional de-vig of an N-way market -> ([probs], hold). None if unusable."""
    decs = [am_to_dec(o) for o in odds]
    if any(d is None for d in decs):
        return None
    raw = [1 / d for d in decs]
    t = sum(raw)
    if t <= 0:
        return None
    return [r / t for r in raw], t - 1


def pull_prices(comp, ways):
    """Return (labels, odds_tuple, book) or None. ESPN nests these inconsistently
    and sometimes puts a literal null in the odds list -- both are handled."""
    for o in comp.get("odds") or []:
        if not isinstance(o, dict):
            continue                      # ESPN emits null entries; skip them
        book = (o.get("provider") or {}).get("name", "?")
        ml = o.get("moneyline") or {}
        for when in ("close", "open"):
            try:
                a = ml["away"][when]["odds"]
                h = ml["home"][when]["odds"]
            except (KeyError, TypeError):
                continue
            if ways == 3:
                d = o.get("drawOdds") or {}
                dr = d.get(when, {}).get("odds") if isinstance(d.get(when), dict) else d.get("moneyLine")
                if dr is not None:
                    return ("away", "draw", "home"), (a, dr, h), book
            return ("away", "home"), (a, h), book
        a = (o.get("awayTeamOdds") or {}).get("moneyLine")
        h = (o.get("homeTeamOdds") or {}).get("moneyLine")
        dr = (o.get("drawOdds") or {}).get("moneyLine")
        if a and h:
            if ways == 3 and dr:
                return ("away", "draw", "home"), (a, dr, h), book
            return ("away", "home"), (a, h), book
    return None


def side_names(comp):
    out = {}
    for x in comp.get("competitors") or []:
        who = x.get("team") or x.get("athlete") or {}
        nm = (who.get("abbreviation") or who.get("shortDisplayName")
              or who.get("displayName") or "?")
        out[x.get("homeAway", "?")] = nm
    return out


def label_for(comp, ev, many):
    n = side_names(comp)
    if "away" in n and "home" in n:
        return f"{n['away']} @ {n['home']}"
    if many:
        who = [((x.get("athlete") or x.get("team") or {}).get("displayName", "?"))
               for x in comp.get("competitors") or []]
        if who:
            return " vs ".join(who)
    return ev.get("shortName") or ev.get("name") or "?"


def show(sport, date=None):
    path, label, ways = LEAGUES[sport]
    data = fetch(path, date)
    events = data.get("events") or []
    day = (data.get("day") or {}).get("date") or date or "today"
    rows = []
    for ev in events:
        comps = ev.get("competitions") or []
        many = len(comps) > 1              # UFC card / golf field / tennis draw
        for c in comps:
            rows.append((label_for(c, ev, many), c))
    print(f"\n{label} -- {day}   ({len(rows)} matchups, times ET)")
    if not rows:
        print("  nothing scheduled.")
        return
    print(f"  {'MATCHUP':<44} {'STATUS':<14} {'MARKET (de-vigged)':<34} HOLD")
    print("  " + "-" * 100)
    for name, c in rows:
        status = ((c.get("status") or {}).get("type") or {}).get("shortDetail", "")[:14]
        line = f"  {name[:44]:<44} {status:<14} "
        pr = pull_prices(c, ways)
        if not pr:
            line += "no posted price"
        else:
            labs, odds, book = pr
            dv = devig(*odds)
            if dv is None:
                line += "market off"
            else:
                probs, hold = dv
                n = side_names(c)
                parts = []
                for lab_, p in zip(labs, probs):
                    who = "Draw" if lab_ == "draw" else n.get(lab_, lab_.upper())
                    parts.append(f"{who} {p*100:.1f}%")
                line += " / ".join(parts).ljust(34) + f" {hold*100:.1f}%"
        print(line)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sport", nargs="?")
    ap.add_argument("--date", help="YYYYMMDD")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.list or (not a.sport and not a.all):
        print("Supported leagues:")
        for k, (_, lab, w) in LEAGUES.items():
            print(f"  {k:<8} {lab:<22} {w}-way" if w else f"  {k:<8} {lab:<22} field")
        print("\n  python3 slate.py mlb")
        print("  python3 slate.py ufc")
        return
    keys = list(LEAGUES) if a.all else [a.sport]
    if not a.all and a.sport not in LEAGUES:
        sys.exit(f"Unknown league '{a.sport}'. Run --list.")
    for k in keys:
        try:
            show(k, a.date)
        except RuntimeError as e:
            print(f"\n{LEAGUES[k][1]}: {e}")


if __name__ == "__main__":
    main()
