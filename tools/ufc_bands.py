"""How UFC favourites have done by their de-vigged chance band, at real
DraftKings prices since 2021 (ufc_history.json): writes ufc_bands.json,
a small summary the board shows beside each UFC pick.

    python tools/ufc_bands.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ufc_model as M  # noqa: E402

BANDS = ((50, 60), (60, 70), (70, 80), (80, 101))


def imp(a):
    a = float(a)
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    a = float(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def bands(book):
    acc = {f"{lo}-{min(hi, 100)}": [0, 0, 0.0] for lo, hi in BANDS}
    for f in book.values():
        a, b = f["a"], f["b"]
        ml = (f.get("odds") or {}).get("ml") or {}
        if a["won"] == b["won"] or ml.get(a["id"]) is None or ml.get(b["id"]) is None:
            continue
        ia, ib = imp(ml[a["id"]]), imp(ml[b["id"]])
        fav, q = (a, ia / (ia + ib)) if ia >= ib else (b, ib / (ia + ib))
        for lo, hi in BANDS:
            if lo <= 100 * q < hi:
                x = acc[f"{lo}-{min(hi, 100)}"]
                x[0] += fav["won"]
                x[1] += 1
                x[2] += (dec(ml[fav["id"]]) - 1) if fav["won"] else -1
    return {k: dict(won=w, n=n, roi=round(100 * pl / n, 1)) for k, (w, n, pl) in acc.items() if n}


if __name__ == "__main__":
    out = bands(M.load())
    with open(os.path.join(ROOT, "ufc_bands.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(out)
