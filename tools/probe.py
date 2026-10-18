"""Feed probe, run on GitHub's runners. Round 30: FanDuel's alternate NFL
totals ladder for this week -- does it price far unders as if the score were
symmetric (as our model did), or does it carry the fat upper tail that 351
finished NFL games show (data/totals_lab.json)?"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, ".")
import fanduel  # noqa: E402
import stacks as S  # noqa: E402


def imp(o):
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


lab = json.load(open("data/totals_lab.json"))["leagues"]["nfl"]["all"]["tails"]
print("finished NFL games, hit rate:", {d: (v["under"], v["over"]) for d, v in lab.items()})
FD = fanduel.load()
agg = defaultdict(list)
for g in (FD.get("nfl") or [])[:16]:
    main = (g.get("total") or {}).get("over")
    if not main or main[0] is None:
        continue
    L0 = float(main[0])
    lad = defaultdict(dict)
    for kind, team, side, L, ref, price, where in fanduel.load_alts(g):
        if kind == "total" and price:
            lad[float(L)][side] = price
    rows = []
    for L in sorted(lad):
        u, o = lad[L].get("under"), lad[L].get("over")
        if not u or not o:
            continue
        pu = imp(u) / (imp(u) + imp(o))
        d = L - L0
        rows.append((L, round(d, 1), u, o, round(pu, 3)))
        for dd in (3, 7, 10, 14):
            if abs(d - dd) <= 0.5:
                agg[("under", dd)].append(pu)
            if abs(d + dd) <= 0.5:
                agg[("over", dd)].append(1 - pu)
    print(g["away"], "@", g["home"], "main", L0)
    for r in rows:
        if abs(r[1]) <= 15:
            print("   line", r[0], "off", r[1], "under", r[2], "over", r[3], "fair under", r[4])
print("FanDuel fair chance by offset (mean over games) vs finished-game hit rate:")
for (side, dd), v in sorted(agg.items()):
    print(f"  {side} {dd}: FanDuel {100*sum(v)/len(v):.1f} (n={len(v)})  actual {lab[str(dd)][side]}  "
          f"old-model {100*S.ncdf(dd/10.5):.1f}")
