"""Re-research every league and regenerate board.html for republishing.

    python3 rebuild_board.py

Fetches upcoming games for today and tomorrow across all twelve leagues, diffs
against the previous run, rewrites the embedded data block inside board.html,
and prints what changed. Publishing the file is a separate step (the Artifact
tool) because only a Claude session can do that.

Why this exists: a published Artifact cannot fetch anything. Its CSP blocks all
outbound requests, and none of the available runtime capabilities grant network
access. The page can only ever hold data baked in at publish time, so keeping it
current means re-baking and republishing it -- which is what this does.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BOARD = os.path.join(HERE, "board.html")
STATE = os.path.join(HERE, ".cache", "last_board.json")

import dashboard as d          # noqa: E402


def snapshot():
    """Fresh research for both days, one row per game, best picks first."""
    d.refresh()
    out = {"at": d._STATE["at"].strftime("%b %-d, %-I:%M %p ET"),
           "dates": {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]},
           "slots": {}}
    for slot in ("today", "tomorrow"):
        lg = {}
        for k, _, lab in d.LEAGUES:
            rows = []
            for r in d._STATE["slots"][slot].get(k) or []:
                if not r.get("mypick"):
                    continue
                # join the price to my side; legs are keyed away/home, picks by name
                leg = next((L for L in r["legs"]
                            if L.get("side") and L["side"] == r.get("myside")), None)
                rows.append({"mp": r["mypick"], "t": r["tip"],
                             "mc": round(r["myconf"] * 100, 1) if r["myconf"] else None,
                             "why": r["why"],
                             "p": leg["price"] if leg else None,
                             "d": bool(leg["dog"]) if leg else False})
            # strongest calls first; anything unrated sinks to the bottom
            rows.sort(key=lambda x: (x["mc"] is None, -(x["mc"] or 0)))
            lg[k] = {"label": lab, "rows": rows}
        out["slots"][slot] = lg
    return out


def changes(new):
    """What moved since the last rebuild."""
    try:
        with open(STATE) as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return ["first run — no prior board to compare"]
    def flat(b):
        """Key rows by slot/league/pick. Tolerates an older snapshot schema:
        a stored board written before a field rename should produce 'first run'
        rather than a KeyError."""
        out = {}
        for s in b.get("slots", {}):
            for k in b["slots"][s]:
                for r in b["slots"][s][k].get("rows", []):
                    name = r.get("mp")
                    if name:
                        out[f"{s}:{k}:{name}"] = r
        return out
    o, n = flat(old), flat(new)
    if not o:
        return ["previous board used an older format — no comparison possible"]
    out = []
    for key, r in n.items():
        prev = o.get(key)
        game = key.split(":", 2)[2]
        if prev is None:
            out.append(f"{game}: new on the board")
            continue
        if prev.get("p") and r.get("p") and prev["p"] != r["p"]:
            try:
                mv = int(r["p"].replace("+", "")) - int(prev["p"].replace("+", ""))
                out.append(f'{game}: {prev["p"]} → {r["p"]} ({mv:+d})')
            except ValueError:
                pass
        if not prev.get("p") and r.get("p"):
            out.append(f'{game}: price posted at {r["p"]}')
        if "TBD" in (prev.get("why") or "") and r.get("why") and "TBD" not in r["why"]:
            out.append(f'{game}: starter named — {r["why"]}')
        if prev.get("mc") and r.get("mc") and abs(prev["mc"] - r["mc"]) >= 3.0:
            out.append(f'{game}: confidence {prev["mc"]:.1f}% → {r["mc"]:.1f}%')
    return out


def main():
    new = snapshot()
    moved = changes(new)
    src = open(BOARD).read()
    blob = json.dumps(new, separators=(",", ":"))
    src2 = re.sub(r"const D = \{.*?\};\n", "const D = " + blob.replace("\\", "\\\\") + ";\n",
                  src, count=1, flags=re.S)
    if src2 == src:
        sys.exit("could not find the embedded data block in board.html")
    open(BOARD, "w").write(src2)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        json.dump(new, fh)
    up = {s: sum(len(v["rows"]) for v in new["slots"][s].values()) for s in new["slots"]}
    print(f'rebuilt board.html — today {up["today"]} upcoming, tomorrow {up["tomorrow"]}')
    print(f'captured {new["at"]}')
    if moved:
        print(f"\n{len(moved)} change(s):")
        for m in moved[:25]:
            print("  " + m)
    else:
        print("\nno changes since last cycle")


if __name__ == "__main__":
    main()
