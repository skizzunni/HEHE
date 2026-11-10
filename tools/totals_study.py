"""Overs and unders against the closing total, season by season, on
tools/nba_history.py output (any league). Pushes dropped; returns are a flat
$1 at the closing over / under price.   python tools/totals_study.py HISTORY.json"""
import json
import sys


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def season_of(day, start_month):
    return day[:4] if day[5:7] >= start_month else str(int(day[:4]) - 1)


def rows(G, start_month="08"):
    out = []
    for g in G.values():
        o = g.get("odds") or {}
        if "total" not in o:
            continue
        t = g["home"]["score"] + g["away"]["score"]
        if t == o["total"]:
            continue
        out.append(dict(season=season_of(g["day"], start_month), line=o["total"], over=t > o["total"],
                        p_over=imp(o["over"]) / (imp(o["over"]) + imp(o["under"])), oo=o["over"], uo=o["under"]))
    return out


def summary(R):
    lines = []
    for s in sorted({r["season"] for r in R}):
        x = [r for r in R if r["season"] == s]
        hit = 100 * sum(r["over"] for r in x) / len(x)
        said = 100 * sum(r["p_over"] for r in x) / len(x)
        ro = 100 * sum((dec(r["oo"]) - 1) if r["over"] else -1 for r in x) / len(x)
        ru = 100 * sum((dec(r["uo"]) - 1) if not r["over"] else -1 for r in x) / len(x)
        lines.append(f"{s} n{len(x)} over {hit:.1f}% vs {said:.1f}% priced, over {ro:+.1f}%, under {ru:+.1f}%")
    return lines


if __name__ == "__main__":
    print("\n".join(summary(rows(json.load(open(sys.argv[1])), sys.argv[2] if len(sys.argv) > 2 else "08"))))
