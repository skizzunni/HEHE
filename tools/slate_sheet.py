#!/usr/bin/env python3
"""A day's NBA / NHL / NFL games, our number first, the price second.

The user (2026-11-23): "do ur own research first and then look at lines, not
look at lines then do research". For each game this prints the price-blind
number from tools/blind_model.py (results only, no odds) before the DraftKings
line from ESPN's pickcenter, then the no-vig chance and the gap. Information
for research: the blind number lost to the market in every league tested
(README 2026-11-23), so a gap is a question to research, not a pick.

    python3 tools/slate_sheet.py 2026-11-24        # refreshes the results cache first
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blind_model as bm  # noqa: E402

SCORE = "https://site.api.espn.com/apis/site/v2/sports/{}/scoreboard?dates={}"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/{}/summary?event={}"
STARTS = {"nba": "2026-10-15", "nhl": "2026-10-01", "nfl": "2026-09-05"}
ALIAS = {"nhl": {"UTAH": "UTA"}}  # ESPN's NHL scoreboard and results disagree on Utah


def _get(url):
    try:
        return json.load(urllib.request.urlopen(url, timeout=30))
    except Exception:
        return None


def no_vig(home, away):
    try:
        h, a = bm._ip(home), bm._ip(away)
    except (TypeError, ValueError):
        return None
    return h / (h + a)


def row(lg, model, ev, summary):
    """One game: our numbers (from results only) and the market's, or None."""
    comp = ev["competitions"][0]
    t = {x["homeAway"]: x["team"]["abbreviation"] for x in comp["competitors"]}
    names = {x["homeAway"]: x["team"].get("displayName") for x in comp["competitors"]}
    h, a = t["home"], t["away"]
    al = ALIAS.get(lg, {})
    p = bm.predict(model, al.get(h, h), al.get(a, a), bool(comp.get("neutralSite"))) if model else None
    pc = ((summary or {}).get("pickcenter") or [{}])[0] if summary else {}
    hm, am = (pc.get("homeTeamOdds") or {}).get("moneyLine"), (pc.get("awayTeamOdds") or {}).get("moneyLine")
    return dict(lg=lg, game=f"{a} @ {h}", start=ev.get("date"), id=ev.get("id"), home=h, away=a,
                home_name=names.get("home"), away_name=names.get("away"),
                blind_home_margin=round(p[0], 1) if p else None, blind_total=round(p[1], 1) if p else None,
                blind_home=round(p[2], 3) if p else None,
                line=pc.get("details"), total=pc.get("overUnder"), home_ml=hm, away_ml=am,
                market_home=round(no_vig(hm, am), 3) if hm is not None and am is not None and no_vig(hm, am) else None)


def text(r):
    blind = ("blind: home margin %+.1f, total %.1f, home win %.0f%%" % (r["blind_home_margin"], r["blind_total"], 100 * r["blind_home"])
             if r["blind_home"] is not None else "blind: no number (team not in the results cache)")
    mkt = (f"then the line: {r['line']}, total {r['total']}, ML away {r['away_ml']} / home {r['home_ml']}"
           + (f", no-vig home {100 * r['market_home']:.0f}%" if r["market_home"] is not None else "")
           if r.get("line") or r.get("home_ml") is not None else "then the line: not posted")
    gap = (f" | gap {100 * (r['blind_home'] - r['market_home']):+.0f} pts" if r["blind_home"] is not None and r["market_home"] is not None else "")
    return f"{r['lg'].upper()} {r['game']}: {blind}; {mkt}{gap}"


def main(day):
    out = []
    for lg in ("nfl", "nba", "nhl"):
        try:
            games = bm.fetch(lg, STARTS[lg])
        except Exception:
            games = json.load(open(bm.cache_path(lg))) if os.path.exists(bm.cache_path(lg)) else []
        model = bm.fit(games, day, *bm.PARAMS[lg]) if games else None
        sb = _get(SCORE.format(bm.SPORT[lg], day.replace("-", ""))) or {}
        for ev in sb.get("events", []):
            out.append(row(lg, model, ev, _get(SUMMARY.format(bm.SPORT[lg], ev["id"]))))
    return out


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat()
    for r in main(day):
        print(text(r))
