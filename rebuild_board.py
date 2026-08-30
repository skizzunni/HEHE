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
    d.refresh()
    out = {"at": d._STATE["at"].strftime("%b %-d, %-I:%M %p ET"),
           "dates": {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]},
           "slots": {}}
    for slot in ("today", "tomorrow"):
        lg = {}
        for k, _, lab in d.LEAGUES:
            rows = d._STATE["slots"][slot].get(k) or []
            lg[k] = {"label": lab,
                     "rows": [{"m": r["label"], "t": r["tip"], "p": r["pick"],
                               "c": round(r["conf"] * 100, 1) if r["conf"] is not None else None,
                               "pr": r["price"], "a": r["note"]} for r in rows]}
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
        return {f'{s}:{k}:{r["m"]}': r
                for s in b.get("slots", {}) for k in b["slots"][s]
                for r in b["slots"][s][k]["rows"]}
    o, n = flat(old), flat(new)
    out = []
    for key, r in n.items():
        prev = o.get(key)
        game = key.split(":", 2)[2]
        if prev is None:
            out.append(f"{game}: new on the board")
            continue
        if prev.get("pr") and r.get("pr") and prev["pr"] != r["pr"]:
            try:
                mv = int(r["pr"].replace("+", "")) - int(prev["pr"].replace("+", ""))
                out.append(f'{game}: {r["p"]} {prev["pr"]} → {r["pr"]} ({mv:+d})')
            except ValueError:
                pass
        if prev.get("p") and r.get("p") and prev["p"] != r["p"]:
            out.append(f'{game}: pick flipped {prev["p"]} → {r["p"]}')
        if "TBD" in (prev.get("a") or "") and r.get("a") and "TBD" not in r["a"]:
            out.append(f'{game}: starter named — {r["a"]}')
        if not prev.get("pr") and r.get("pr"):
            out.append(f'{game}: price posted — {r["p"]} {r["pr"]}')
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
