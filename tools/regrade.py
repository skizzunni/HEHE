"""Nightly independent re-grade of the pick ledger.

ledger.grade settles picks from ESPN's SCOREBOARD. This re-fetches every
recently settled game from a different endpoint -- the game SUMMARY -- and
settles it again with its own code: the winner from the scores alone (the
feed's winner flag is not trusted), soccer on the 90-minute score, a level
score a draw, and the same betting rules (ledger._settle's contract: "or
draw" wins on a draw, a 3-way soccer moneyline loses on one, a two-way tie
pushes; postponed, cancelled, abandoned and walkover games are void).
Every disagreement with ledger.json is listed in review/regrade.json and on
the Results tab. Nothing is changed in the ledger: a mismatch is for review.

Runs once a night (the first run from 3:00 AM Eastern), over the picks
settled in the last DAYS days; `--from/--to` re-grades any window.

    python3 tools/regrade.py [--force] [--from 2026-10-15 --to 2026-10-19]
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "review", "regrade.json")
DAYS = 3
NIGHT_HOUR = 3


def day_of(e):
    return e.get("played") or e.get("date") or (e.get("settled") or "")[:10] or (e.get("logged") or "")[:10]


def expected(e, sm, soccer):
    """(state, score) from the game summary, or (None, why) when unknowable."""
    comp = ((sm.get("header") or {}).get("competitions") or [{}])[0]
    st = (comp.get("status") or {}).get("type") or {}
    name, detail = (st.get("name") or "").upper(), (st.get("shortDetail") or st.get("detail") or "").upper()
    for key, state in (("POSTPONED", "postponed"), ("CANCEL", "cancelled"), ("ABANDON", "abandoned"),
                       ("FORFEIT", "walkover"), ("WALKOVER", "walkover")):
        if key in name:
            return state, None
    if "W/O" in detail or "WALKOVER" in detail:
        return "walkover", None
    if not st.get("completed"):
        return None, "not final in the summary"
    pts = {}
    for x in comp.get("competitors") or []:
        who = ((x.get("team") or {}).get("displayName") or (x.get("athlete") or {}).get("displayName"))
        try:
            if soccer and ("AET" in name or "PEN" in name or "EXTRA" in name):
                ls = x.get("linescores") or []
                pts[who] = int(float(ls[0].get("value"))) + int(float(ls[1].get("value")))
            else:
                pts[who] = int(float(x.get("score")))
        except (TypeError, ValueError, IndexError, AttributeError):
            return None, "no usable score"
    if len(pts) != 2:
        return None, "no usable score"
    (a, sa), (b, sb) = pts.items()
    pick = e.get("pick")
    if sa == sb:
        if e.get("dc"):
            return "won", pts
        return ("lost" if soccer else "push"), pts
    win = a if sa > sb else b
    same = (win or "").strip().casefold() == (pick or "").strip().casefold()   # feeds differ in case
    return ("won" if same else "lost"), pts


def regrade(entries, lo, hi, fetch=None):
    import ledger
    fetch = fetch or (lambda lg, cid: ledger.get(f"{ledger.ESPN}/{ledger.PATHS.get(lg)}/summary?event={cid}"))
    rows, unchecked = [], 0
    todo = []
    for k, e in sorted(entries.items()):
        if e.get("status") in (None, "open") or not lo <= day_of(e) <= hi:
            continue
        lg, cid = k.split(":", 1)
        if lg in ("atp", "wta") or not ledger.PATHS.get(lg):
            unchecked += 1                      # tennis: no summary header scores
            continue
        todo.append((k, e, lg, cid))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        sums = list(ex.map(lambda t: fetch(t[2], t[3]), todo))
    for (k, e, lg, cid), sm in zip(todo, sums):
        if not sm:
            unchecked += 1
            continue
        want, score = expected(e, sm, lg in ledger.SOCCER)
        if want is None:
            unchecked += 1
            continue
        have = e.get("state") or e["status"]
        # a void-kind recorded only as "void" (before states were explicit)
        same = (have == want or (have == "void" and want in ("postponed", "cancelled", "abandoned", "walkover")))
        rows.append(dict(key=k, league=lg, pick=e.get("pick"), dc=bool(e.get("dc")), day=day_of(e),
                         ledger=have, regrade=want, score=score, match=same))
    bad = [r for r in rows if not r["match"]]
    return dict(window=[lo, hi], checked=len(rows), unchecked=unchecked, mismatches=bad,
                ran=dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"))


def main():
    import ledger
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--from", dest="lo")
    ap.add_argument("--to", dest="hi")
    a = ap.parse_args()
    now = dt.datetime.now(ledger.ET)
    try:
        with open(OUT) as fh:
            last = json.load(fh)
    except (OSError, ValueError):
        last = {}
    if not (a.force or a.lo) and (now.hour < NIGHT_HOUR or (last.get("night") == now.date().isoformat())):
        print("regrade: not tonight's run")
        return last
    lo = a.lo or (now.date() - dt.timedelta(days=DAYS)).isoformat()
    hi = a.hi or now.date().isoformat()
    rep = regrade(ledger.load(), lo, hi)
    rep["night"] = now.date().isoformat()
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
    print(f"regrade {lo}..{hi}: {rep['checked']} checked, {len(rep['mismatches'])} mismatches, "
          f"{rep['unchecked']} not checkable")
    return rep


if __name__ == "__main__":
    main()
