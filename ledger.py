"""Pick ledger: record every call, grade it, diagnose the losses, learn slowly.

    python3 ledger.py record      # snapshot today's picks (idempotent)
    python3 ledger.py grade       # settle finished games, diagnose losses
    python3 ledger.py report      # record, calibration, loss patterns
    python3 ledger.py cycle       # record + grade + report, for the hourly job

WHY IT DOES NOT AUTO-RETUNE ON LOSSES

A bad night and a bad model are indistinguishable at small n. A 57% process over
14 games has a standard deviation of 1.9 games, so 6 and 10 wins are both
ordinary. Earlier in this project a calibration curve fitted to a handful of
in-sample results *degraded* held-out Brier (0.2449 -> 0.2455). Retuning on the
last few losses is how a model gets worse while looking responsive.

So the ledger separates two things:

  * DIAGNOSIS runs on every loss immediately -- was the market on my side, was
    it a blowout or a coin flip, which confidence band, was a starter unknown.
    That is description, and description is safe at any n.

  * RETUNING is gated. `report` only recommends a parameter change when a
    pattern clears a significance bar (>=100 graded picks in a bucket and a
    calibration gap wider than two standard errors). Below that it says so and
    changes nothing.
"""
import argparse
import datetime as dt
import json
import math
import os
import ssl
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger.json")
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
ET = dt.timezone(dt.timedelta(hours=-4))

PATHS = {"mlb": "baseball/mlb", "wnba": "basketball/wnba", "nba": "basketball/nba",
         "nfl": "football/nfl", "ncaaf": "football/college-football",
         "nhl": "hockey/nhl", "atp": "tennis/atp", "wta": "tennis/wta",
         "epl": "soccer/eng.1", "mls": "soccer/usa.1", "pga": "golf/pga",
         "ufc": "mma/ufc"}

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url, tries=2):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40, context=_CTX) as r:
                return json.load(r)
        except Exception:
            pass
    return {}


def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(d):
    with open(LEDGER, "w") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)


# ------------------------------------------------------------------ record
def record(state=None):
    """Snapshot the current board's picks. Safe to run repeatedly.

    `state` lets a caller that has already researched the slate hand its
    dashboard state in, so the hourly rebuild fetches everything once instead
    of twice.
    """
    if state is None:
        sys.path.insert(0, HERE)
        import dashboard as D
        D.refresh()
        state = D._STATE
    book = load()
    added = 0
    for slot in ("today", "tomorrow"):
        for lg, rows in (state["slots"].get(slot) or {}).items():
            for r in rows:
                if not r.get("mypick"):
                    continue
                key = r["id"]                     # league:espn_competition_id
                if key in book and book[key].get("status") != "open":
                    continue                      # already settled, never rewrite
                leg = next((L for L in r["legs"]
                            if L.get("side") and L["side"] == r.get("myside")), None)
                entry = dict(league=lg, pick=r["mypick"], matchup=r["label"],
                             conf=round((r["myconf"] or 0) * 100, 1),
                             why=r.get("why", ""), tip=r.get("tip"),
                             price=(leg or {}).get("price"),
                             dog=bool((leg or {}).get("dog")),
                             # Whether the book made my side the favourite. Derive
                             # it from the price, not from the board's `pick`
                             # column -- that column holds the best historical ROI
                             # band, which is usually the underdog, so comparing
                             # against it labelled every favourite a market fade.
                             market_agrees=(None if not leg or not leg.get("price")
                                            else not leg.get("dog")),
                             status="open", logged=dt.datetime.now(ET).isoformat()[:16])
                if key not in book:
                    added += 1
                book[key] = {**book.get(key, {}), **entry}
    save(book)
    return added, len(book)


# ------------------------------------------------------------------- grade
def _final(lg, comp_id):
    """(winner, away, home, ascore, hscore) once complete, else None."""
    path = PATHS.get(lg)
    if not path:
        return None
    for back in (0, 1, 2):
        day = (dt.datetime.now(ET) - dt.timedelta(days=back)).strftime("%Y%m%d")
        d = get(f"{ESPN}/{path}/scoreboard?dates={day}")
        for ev in d.get("events", []):
            comps = list(ev.get("competitions") or [])
            for grp in ev.get("groupings") or []:
                comps.extend(grp.get("competitions") or [])
            for c in comps:
                if str(c.get("id")) != str(comp_id):
                    continue
                st = ((c.get("status") or {}).get("type") or {})
                cs = c.get("competitors") or []
                names, scores = {}, {}
                for x in cs:
                    who = ((x.get("team") or {}).get("displayName")
                           or (x.get("athlete") or {}).get("displayName"))
                    names[x.get("homeAway", x.get("order"))] = who
                    try:
                        scores[who] = int(x.get("score"))
                    except (TypeError, ValueError):
                        # tennis posts no aggregate score, only a set line
                        sets = []
                        for ls in x.get("linescores") or []:
                            try:
                                v = str(int(ls.get("value")))
                            except (TypeError, ValueError):
                                continue
                            tb = ls.get("tiebreak")
                            sets.append(f"{v}({tb})" if tb not in (None, "") else v)
                        scores[who] = " ".join(sets) if sets else None
                    if x.get("winner"):
                        names["winner"] = who
                if not st.get("completed"):
                    # "pre" is a game that has not started -- not live, and
                    # nothing to show. Only state "in" is actually underway.
                    if st.get("state") != "in":
                        return None
                    return dict(live=True, state=st.get("shortDetail", ""),
                                scores=scores)
                win = names.get("winner")
                if win is None and all(v is not None for v in scores.values()) and len(scores) == 2:
                    win = max(scores, key=scores.get)
                return dict(live=False, winner=win, scores=scores,
                            state=st.get("shortDetail", ""))
    return None


def diagnose(e, res):
    """Describe a loss. Description only -- no parameter is changed from this."""
    bits = []
    scores = res.get("scores") or {}
    # set-scored sports carry a string line ("6 7(8)"), not a number -- read
    # the margin off the sets won rather than reporting nothing.
    strs = [v for v in scores.values() if isinstance(v, str)]
    if len(strs) == 2 and e["pick"] in scores:
        mine = scores[e["pick"]].split()
        other = next(v for k, v in scores.items() if k != e["pick"]).split()
        pairs = [(a, b) for a, b in zip(mine, other)]
        won = sum(1 for a, b in pairs
                  if a.split("(")[0].isdigit() and b.split("(")[0].isdigit()
                  and int(a.split("(")[0]) > int(b.split("(")[0]))
        lost = len(pairs) - won
        bits.append(f"lost {won}-{lost} in sets")
        if won == 0:
            bits.append("never won a set")
        elif won >= 1:
            bits.append("took it the distance")
    sc = [v for v in scores.values() if isinstance(v, int)]
    if len(sc) == 2:
        margin = abs(sc[0] - sc[1])
        bits.append(f"margin {margin}")
        if e["league"] == "mlb":
            bits.append("blowout" if margin >= 6 else
                        "comfortable" if margin >= 4 else
                        "one-run game" if margin == 1 else "close")
    if e.get("market_agrees") is True:
        bits.append("the book had my side favoured too")
    elif e.get("market_agrees") is False:
        bits.append("I took the side the book had as less likely")
    if e.get("dog"):
        bits.append("I took the underdog")
    if "TBD" in (e.get("why") or ""):
        bits.append("a starter was unannounced when I called it")
    c = e.get("conf") or 0
    bits.append(f"called at {c:.0f}%")
    return " · ".join(bits)


def grade():
    book = load()
    settled = []
    for key, e in book.items():
        if e.get("status") != "open":
            continue
        lg, comp = key.split(":", 1)
        res = _final(lg, comp)
        if not res:
            e.pop("live", None)          # was it ever marked live, it is not now
            e.pop("live_score", None)
            continue
        if res.get("live"):
            e["live"] = res.get("state")
            e["live_score"] = res.get("scores")
            continue
        win = res.get("winner")
        if not win:
            continue
        e.pop("live", None)
        e.pop("live_score", None)
        e["winner"] = win
        e["scores"] = res.get("scores")
        e["status"] = "won" if win == e["pick"] else "lost"
        e["settled"] = dt.datetime.now(ET).isoformat()[:16]
        if e["status"] == "lost":
            e["diagnosis"] = diagnose(e, res)
        settled.append((key, e))
    save(book)
    return settled


# ------------------------------------------------------------------ report
def _se(n):
    return math.sqrt(0.25 / n) * 100 if n else 0.0


def report():
    book = load()
    done = [e for e in book.values() if e.get("status") in ("won", "lost")]
    out = {"graded": len(done), "open": sum(1 for e in book.values()
                                            if e.get("status") == "open")}
    if not done:
        return out, []
    out["won"] = sum(1 for e in done if e["status"] == "won")
    out["lost"] = len(done) - out["won"]
    out["hit"] = 100 * out["won"] / len(done)
    by_lg = defaultdict(lambda: [0, 0])
    band = defaultdict(lambda: [0, 0, 0.0])
    for e in done:
        by_lg[e["league"]][0] += 1
        by_lg[e["league"]][1] += e["status"] == "won"
        b = min(int((e.get("conf") or 50) / 5) * 5, 85)
        band[b][0] += 1
        band[b][1] += e["status"] == "won"
        band[b][2] += e.get("conf") or 0
    out["by_league"] = {k: dict(n=v[0], won=v[1], hit=100 * v[1] / v[0])
                        for k, v in by_lg.items()}
    out["calibration"] = {
        b: dict(n=v[0], said=v[2] / v[0], actual=100 * v[1] / v[0],
                gap=100 * v[1] / v[0] - v[2] / v[0], se=_se(v[0]))
        for b, v in sorted(band.items())}
    # a recommendation only where the sample can carry one
    recs = []
    for b, c in out["calibration"].items():
        if c["n"] >= 100 and abs(c["gap"]) > 2 * c["se"]:
            recs.append(f'{b}-{b+5}% band: said {c["said"]:.1f}%, hit '
                        f'{c["actual"]:.1f}% over {c["n"]} picks '
                        f'({c["gap"]:+.1f}, {abs(c["gap"])/c["se"]:.1f} s.e.) '
                        f'— large enough to act on')
    return out, recs


# ----------------------------------------------------------- site payload
def board_payload(limit=40):
    """Everything the published page shows on its Results tab.

    Live scores, the running record, calibration, and the loss feed. Built
    from the same ledger the CLI reports on, so the page and the terminal can
    never disagree.
    """
    book = load()
    r, recs = report()
    live = [dict(league=e["league"], pick=e["pick"], matchup=e.get("matchup", ""),
                 state=e.get("live", ""), conf=e.get("conf"),
                 score=e.get("live_score") or {})
            for e in book.values()
            if e.get("status") == "open" and e.get("live")]
    live.sort(key=lambda x: (x["league"], x["pick"]))

    done = [e for e in book.values() if e.get("status") in ("won", "lost")]
    done.sort(key=lambda e: e.get("settled") or e.get("logged") or "", reverse=True)
    feed = [dict(league=e["league"], pick=e["pick"], status=e["status"],
                 conf=e.get("conf"), price=e.get("price"), dog=e.get("dog"),
                 score=e.get("scores") or {},
                 why=(e.get("diagnosis") if e["status"] == "lost"
                      else e.get("why") or ""),
                 when=(e.get("settled") or e.get("logged") or "")[:10])
            for e in done[:limit]]

    gate = recs or []
    # epoch ms of this capture, so the page can show its own age at render
    # time. The page cannot fetch, so honesty about staleness is the only
    # substitute for freshness.
    captured = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    return dict(captured=captured,
                graded=r.get("graded", 0), open=r.get("open", 0),
                won=r.get("won", 0), lost=r.get("lost", 0),
                hit=round(r["hit"], 1) if r.get("graded") else None,
                by_league=[dict(lg=k, n=v["n"], won=v["won"],
                                hit=round(v["hit"], 1))
                           for k, v in sorted(r.get("by_league", {}).items(),
                                              key=lambda x: -x[1]["n"])],
                calibration=[dict(band=b, n=c["n"], said=round(c["said"], 1),
                                  actual=round(c["actual"], 1),
                                  gap=round(c["gap"], 1), thin=c["n"] < 30)
                             for b, c in sorted(r.get("calibration", {}).items())],
                live=live, feed=feed, gate=gate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record", "grade", "report", "cycle"])
    a = ap.parse_args()
    if a.cmd in ("record", "cycle"):
        added, total = record()
        print(f"recorded {added} new pick(s); ledger holds {total}")
    if a.cmd in ("grade", "cycle"):
        s = grade()
        print(f"settled {len(s)} pick(s)")
        for k, e in s:
            mark = "WON " if e["status"] == "won" else "LOST"
            sc = e.get("scores") or {}
            line = " ".join(f"{k2} {v}" for k2, v in sc.items() if v is not None)
            print(f"  {mark} {e['pick'][:26]:<26} {line}")
            if e["status"] == "lost":
                print(f"       why: {e['diagnosis']}")
    if a.cmd in ("report", "cycle"):
        r, recs = report()
        if not r.get("graded"):
            print(f"\nnothing graded yet ({r['open']} open)")
            return
        print(f"\nRECORD  {r['won']}-{r['lost']}  ({r['hit']:.1f}%)  "
              f"| {r['open']} still open")
        for lg, v in sorted(r["by_league"].items(), key=lambda x: -x[1]["n"]):
            print(f"  {lg:<6} {v['won']}-{v['n']-v['won']}  {v['hit']:.1f}%")
        print("\nCALIBRATION")
        for b, c in r["calibration"].items():
            flag = "" if c["n"] >= 30 else "   (thin)"
            print(f"  said {c['said']:.0f}%  n={c['n']:<4} actual {c['actual']:.1f}%"
                  f"  gap {c['gap']:+.1f}{flag}")
        print("\nUPGRADE GATE")
        if recs:
            for x in recs:
                print("  " + x)
        else:
            print("  no bucket has both 100+ graded picks and a gap beyond two")
            print("  standard errors. Nothing here justifies a parameter change.")


if __name__ == "__main__":
    main()
