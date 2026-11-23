"""NFL anytime-TD history (data/td_history.json), Locks prop legs (locks.json),
and the Elijah Higgins record. Read-only."""
import collections, json, os
from common import *
OUT = []
def add(name, rows, sec):
    r = fmt(name, rows); r["sec"] = sec; OUT.append(r); print(r["line"])
td = json.load(open(os.path.join(ROOT, "data", "td_history.json")))
T = []
for k, e in td.items():
    if e.get("status") in ("won", "lost") and isinstance(e.get("p"), (int, float)):
        e = dict(e); e["y"] = int(e["status"] == "won"); e["dec"] = dec(e.get("price")); T.append(e)
print("== TD history (all graded anytime-TD player-games)")
add("td_history all", T, "td")
for a, b in [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, 1)]:
    add(f"td p in [{a},{b})", [e for e in T if a <= e["p"] < b], "td")
print("== Locks card prop legs (locks.json legs, kind=prop)")
L = json.load(open(os.path.join(ROOT, "locks.json")))["legs"]
LP = []
for k, e in L.items():
    if e.get("kind") == "prop" and e.get("status") in ("won", "lost") and isinstance(e.get("p"), (int, float)):
        e = dict(e); e["y"] = int(e["status"] == "won"); e["dec"] = dec(e.get("price")); LP.append(e)
add("Locks prop legs", LP, "locks")
add("Locks game legs", [dict(e, y=int(e["status"] == "won"), dec=dec(e.get("price"))) for e in L.values()
                        if e.get("kind") == "game" and e.get("status") in ("won", "lost") and isinstance(e.get("p"), (int, float))], "locks")
by = collections.defaultdict(list)
for e in LP: by[(e.get("league"), e.get("market"))].append(e)
for k, v in sorted(by.items(), key=lambda x: -len(x[1])):
    if len(v) >= 5: add(f"  Locks {k[0]} {k[1]}", v, "locks")
print("== Elijah Higgins records in props.json")
for k, e in json.load(open(os.path.join(ROOT, "props.json"))).items():
    if "Elijah Higgins" in e.get("label", ""):
        print(" ", e["date"], e["label"], e["price"], e["p"], e["status"], e.get("value"))
json.dump(OUT, open("results_c.json", "w"), indent=1)
