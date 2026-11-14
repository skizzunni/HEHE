"""How a league's board picks moved since a saved snapshot: the published
board's rows for one league (pick and stated chance), saved now and compared
later -- a pick whose chance dropped 3+ points means money moved to the other
side; a pick that changed side or vanished (a scratched bout) is flagged.

    python tools/line_moves.py LEAGUE --save SNAP.json [--url URL]
    python tools/line_moves.py LEAGUE --compare SNAP.json [--url URL]
"""
import argparse
import json
import re
import urllib.request

URL = "https://skizzunni.github.io/HEHE/"


def board(url=URL, fetch=None):
    """The published page's data (the const D line)."""
    if fetch is None:
        with urllib.request.urlopen(url + "?t=line_moves", timeout=30) as r:
            html = r.read().decode("utf-8")
    else:
        html = fetch(url)
    m = re.search(r"const D\s*=\s*(\{.*?\});\s*\n", html, re.S)
    return json.loads(m.group(1)) if m else {}


def rows(D, league, day="today"):
    """{game key: {pick, chance, time}} for the league's rows on that day."""
    out = {}
    for r in (((D.get("slots") or {}).get(day) or {}).get(league) or {}).get("rows") or []:
        key = r.get("id") or r.get("m") or r.get("mp")
        out[str(key)] = dict(pick=r.get("mp"), chance=r.get("mc"), time=r.get("t"))
    return out


def compare(before, after, drop=3):
    """Lines describing each change: chance moves of `drop`+ points, side
    changes, scratched and new games. Unchanged games are left out."""
    out = []
    for k, b in before.items():
        a = after.get(k)
        if a is None:
            out.append(f"GONE {b['pick']} ({b['chance']}%) -- no longer on the board (scratched or started)")
        elif a["pick"] != b["pick"]:
            out.append(f"SIDE CHANGED {b['pick']} ({b['chance']}%) -> {a['pick']} ({a['chance']}%)")
        elif isinstance(a["chance"], (int, float)) and isinstance(b["chance"], (int, float)):
            d = a["chance"] - b["chance"]
            if d <= -drop:
                out.append(f"DOWN {b['pick']} {b['chance']}% -> {a['chance']}% ({d:+.0f}): money moving to the other side")
            elif d >= drop:
                out.append(f"UP {b['pick']} {b['chance']}% -> {a['chance']}% ({d:+.0f})")
    for k, a in after.items():
        if k not in before:
            out.append(f"NEW {a['pick']} ({a['chance']}%)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("league")
    ap.add_argument("--save")
    ap.add_argument("--compare")
    ap.add_argument("--url", default=URL)
    a = ap.parse_args()
    D = board(a.url)
    now = rows(D, a.league)
    if a.save:
        with open(a.save, "w") as fh:
            json.dump(dict(at=D.get("at"), rows=now), fh, indent=1)
        print(f"saved {len(now)} {a.league} rows as of {D.get('at')}")
    if a.compare:
        with open(a.compare) as fh:
            snap = json.load(fh)
        ch = compare(snap["rows"], now)
        print(f"{a.league}: {len(now)} rows now ({D.get('at')}) vs {len(snap['rows'])} at {snap.get('at')}")
        print("\n".join(ch) if ch else "no pick moved 3+ points, changed side or left the board")
