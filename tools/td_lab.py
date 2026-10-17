"""Touchdown lab: how accurate are anytime-TD chances, and can anything beat them?

    python3 tools/td_lab.py      # on GitHub's runners

For every finished NFL game in the backtest windows: DraftKings' anytime-TD
price for each listed player (ESPN keeps them after the game), the game's
closing total, and whether the player scored (box score). Older half fits,
newer half scores, nothing tuned on the games it is judged on.

Methods compared on the newer half:
  raw       the price's implied chance, margin and all
  hold      implied / one factor fitted on the older half
  scaled    the board's method: expected touchdowns from the total, never
            above the hold factor (td_scorers.py)
  form      scaled, plus the player's own touchdown rate over his previous
            games in the data (logistic, fitted on the older half)

Also: how often the board's published picks -- the top two per game -- scored.
Data: data/td_history.json, the board's own log (ESPN keeps no past prices).
Writes data/td_lab.json.
"""
import datetime as dt
import json
import math
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import backtest as B                                          # noqa: E402
import edge_lab as E                                          # noqa: E402
import player_props as PP                                     # noqa: E402
import props_ledger as PL                                     # noqa: E402

OUT = os.path.join(ROOT, "data", "td_lab.json")
TD_PER_POINT, NON_OFFENSE = 0.105, 0.04
MARKET = "Anytime Touchdown Scorer"


def game_rows(g):
    d, eid, home, away, hs, as_ = g
    items = PP.raw_items("nfl", eid)
    px = {}
    for x in items:
        t = ((x.get("type") or {}).get("name") or "").replace(" (incl. overtime)", "")
        if t != MARKET:
            continue
        imp = PP.american_prob(((x.get("current") or {}).get("over") or {}).get("american"))
        m = re.search(r"/athletes/(\d+)", ((x.get("athlete") or {}).get("$ref")) or "")
        if imp is None or not m:
            continue
        px.setdefault(m.group(1), imp)
    if len(px) < 8:
        return []
    sm = PL.summary("nfl", eid)
    if not sm or not sm.get("completed"):
        return []
    stats = PL.box_stats(sm)
    fn = PL.MARKETS["nfl"][MARKET]
    o = B.closing("nfl", "football", "nfl", eid) or {}
    try:
        total = float(o.get("total"))
    except (TypeError, ValueError):
        total = None
    rows = []
    for aid, imp in px.items():
        st = stats.get(aid)
        if st is None:
            continue                     # did not play: the bet voids
        v = fn(st)
        if v is None:
            continue
        rows.append(dict(date=d.isoformat(), eid=str(eid), aid=aid, imp=imp, total=total,
                         td=int(v >= 1)))
    return rows


def ll(ps, ys):
    return round(-sum(math.log(max(1e-4, p if y else 1 - p)) for p, y in zip(ps, ys)) / len(ps), 4)


def bands(ps, ys):
    out = []
    for lo, hi in ((0, .15), (.15, .25), (.25, .35), (.35, .45), (.45, .55), (.55, 1.01)):
        b = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi]
        if b:
            out.append(dict(band=f"{int(lo*100)}-{min(int(hi*100), 100)}", n=len(b),
                            said=round(100 * sum(p for p, _ in b) / len(b), 1),
                            scored=round(100 * sum(y for _, y in b) / len(b), 1)))
    return out


def main():
    # ESPN wipes prop prices once a game is over, so the data is the board's
    # own log (td_scorers.log): every listed player's last pre-game price
    with open(os.path.join(ROOT, "data", "td_history.json")) as fh:
        book = json.load(fh)
    rows = []
    for e in book.values():
        if e.get("status") not in ("won", "lost"):
            continue
        rows.append(dict(date=e["date"], eid=e["gid"], aid=e["name"], imp=e["imp"],
                         total=e.get("total"), td=int(e["status"] == "won")))
    if len({r["eid"] for r in rows}) < 20:
        print("not enough graded games yet:", len({r["eid"] for r in rows}))
        return
    rows.sort(key=lambda r: (r["date"], r["eid"]))
    print("player-games", len(rows), "games", len({r['eid'] for r in rows}), flush=True)
    # each player's touchdown rate over his earlier games in the data
    hist = defaultdict(list)
    for r in rows:
        h = hist[r["aid"]]
        r["form"] = (sum(h) + 0.3 * 3) / (len(h) + 3)          # shrunk toward a typical 30%
        r["n_prev"] = len(h)
        h.append(r["td"])
    eids = sorted({r["eid"] for r in rows}, key=lambda e: next(r["date"] for r in rows if r["eid"] == e))
    cut = eids[len(eids) // 2]
    first = {e: i for i, e in enumerate(eids)}
    fit = [r for r in rows if first[r["eid"]] < first[cut]]
    test = [r for r in rows if first[r["eid"]] >= first[cut]]
    # one hold factor from the older half: implied sum vs scored
    hold = sum(r["imp"] for r in fit) / max(1, sum(r["td"] for r in fit))
    by_game = defaultdict(list)
    for r in rows:
        by_game[r["eid"]].append(r)

    def scaled(r):
        g = by_game[r["eid"]]
        lam = -math.log(max(1e-6, 1 - min(r["imp"], 0.95)))
        k = 1 / hold
        if r["total"]:
            tot = sum(-math.log(max(1e-6, 1 - min(x["imp"], 0.95))) for x in g)
            target = TD_PER_POINT * r["total"] * (1 - NON_OFFENSE)
            k = min(k, target / tot)
        return 1 - math.exp(-lam * k)

    for r in rows:
        r["p_raw"] = r["imp"]
        r["p_hold"] = min(r["imp"] / hold, 0.99)
        r["p_scaled"] = scaled(r)
    X = lambda r: [1.0, E.lg(r["p_scaled"]), E.lg(r["form"]) if r["n_prev"] >= 3 else 0.0]
    w = E.fit_logit([X(r) for r in fit], [r["td"] for r in fit])
    for r in rows:
        r["p_form"] = 1 / (1 + math.exp(-sum(a * b for a, b in zip(w, X(r)))))
    ys = [r["td"] for r in test]
    rep = dict(run=dt.date.today().isoformat(), player_games=len(rows), games=len(eids),
               test_games=len({r["eid"] for r in test}), hold=round(hold, 4),
               form_weights=[round(x, 3) for x in w], methods={})
    for m in ("p_raw", "p_hold", "p_scaled", "p_form"):
        ps = [r[m] for r in test]
        # the board's published picks: the top two per game by this method
        top = []
        for e in {r["eid"] for r in test}:
            g = sorted((r for r in by_game[e]), key=lambda r: -r[m])[:2]
            top += g
        rep["methods"][m] = dict(logloss=ll(ps, ys), bands=bands(ps, ys),
                                 top2=dict(n=len(top), scored=round(100 * sum(r["td"] for r in top) / len(top), 1),
                                           said=round(100 * sum(r[m] for r in top) / len(top), 1)))
        print(m, json.dumps(rep["methods"][m]), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()
