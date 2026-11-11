"""Board picks against the injury report as it stood at tip-off
(injuries.before on the archived review/injuries snapshots): did picks whose
own side had more players Out do worse than those whose opponent did?
python tools/injury_study.py  -- prints n, won% vs stated%, per group and half."""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import injuries                                                   # noqa: E402

ET = ZoneInfo("America/New_York")


def rows(ledger, days, before=injuries.before):
    out = []
    for v in ledger.values():
        lg = v.get("league")
        if lg not in ("nba", "nhl", "nfl") or v.get("status") not in ("won", "lost") \
                or v.get("date") not in days or v.get("record_excluded"):
            continue
        try:
            t = dt.datetime.strptime(v["date"] + " " + v["tip"], "%Y-%m-%d %I:%M %p").replace(tzinfo=ET)
        except (KeyError, ValueError, TypeError):
            continue
        T = before(v["date"], t.astimezone(dt.timezone.utc).isoformat(), lg)
        teams = list(v.get("scores") or {})
        if not T or len(teams) != 2 or v.get("pick") not in teams:
            continue
        opp = [k for k in teams if k != v["pick"]][0]
        mine = sum(1 for _, s in T.get(v["pick"]) or [] if s == "Out")
        theirs = sum(1 for _, s in T.get(opp) or [] if s == "Out")
        out.append(dict(date=v["date"], mine=mine, theirs=theirs, won=v["status"] == "won", conf=v.get("conf") or 0))
    return out


def table(R):
    R = sorted(R, key=lambda r: r["date"])
    mid = R[len(R) // 2]["date"] if R else ""
    lines = []
    for lab, f in (("my side more out", lambda r: r["mine"] > r["theirs"]), ("even", lambda r: r["mine"] == r["theirs"]),
                   ("their side more out", lambda r: r["mine"] < r["theirs"])):
        cells = []
        for h, g in (("1st", lambda r: r["date"] < mid), ("2nd", lambda r: r["date"] >= mid)):
            x = [r for r in R if f(r) and g(r)]
            if x:
                cells.append(f"{h} {sum(r['won'] for r in x)}/{len(x)} {100 * sum(r['won'] for r in x) / len(x):.0f}%"
                             f" vs {sum(r['conf'] for r in x) / len(x):.0f}%")
        lines.append(f"{lab}: " + " | ".join(cells))
    return lines


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    led = json.load(open(os.path.join(root, "ledger.json")))
    days = {f[:-5] for f in os.listdir(injuries.DIR) if f.endswith(".json")}
    R = rows(led, days)
    print(len(R), "games")
    print("\n".join(table(R)))
