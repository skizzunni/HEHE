"""Print results.json as a compact table.  python3 summary.py"""
import json
import os

R = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")))


def row(r):
    h1, h2 = r.get("h1", {}), r.get("h2", {})
    m = r.get("money", {})
    print(f"{r.get('strategy','')[:62]:62s} n={r.get('n','')!s:>3} cash {r.get('cashed','')}/{r.get('expected','')} "
          f"| H1 {h1.get('won')}/{h1.get('exp')} z{h1.get('z')} | H2 {h2.get('won')}/{h2.get('exp')} z{h2.get('z')} "
          f"| pays {r.get('avg_pays')} legs {r.get('avg_legs')} roi {m.get('roi')} geo.1 {m.get('geo_f0.1')} "
          f"geo.25 {m.get('geo_f0.25')} full {m.get('geo_f1.0')} peak {m.get('peak_bank')} streak {m.get('streak')} "
          f"chg {r.get('tickets_changed','')} -> {r.get('verdict')}")


print(R["_meta"])
for k in ("0_ladder_as_run", "0_current_rule_all_cards"):
    row(R[k]); print("  ", R[k].get("lost_on_one_leg", ""))
print("\n# 1 size")
for r in R["1_size"].values():
    row(r)
print("\n# 2 filters")
for k in ("walk_forward", "props_out"):
    row(R["2_filters"][k])
for r in R["2_filters"]["tip_spread"].values():
    row(r)
for src in ("card_leg_groups", "pool_leg_groups"):
    print(" ", src)
    for k, v in sorted(R["2_filters"][src].items()):
        flag = "*" if v["h1"]["z"] < 0 and v["h2"]["z"] < 0 else " "
        print(f"   {flag}{k:40s} {v['h1']['won']}/{v['h1']['n']} exp {v['h1']['exp']} z{v['h1']['z']} | "
              f"{v['h2']['won']}/{v['h2']['n']} exp {v['h2']['exp']} z{v['h2']['z']}  {v['verdict']}")
print("\n# 3 shrink", R["3_shrink"]["leg_logloss"], R["3_shrink"]["card_legs"])
for r in R["3_shrink"]["tickets"].values():
    row(r)
    if "leg_logloss_fit_vs_raw" in r:
        print("    leg logloss fit vs raw", r["leg_logloss_fit_vs_raw"])
print("\n# 4 correlation")
for k, v in R["4_correlation"].items():
    print(" ", k, json.dumps(v))
print("\n# 5 staking")
for k, v in R["5_staking"].items():
    print(" ", k, json.dumps(v))
print("\n# 7 every-game")
for r in R["7_everygame"].values():
    row(r)
    if "paired_vs_ladder" in r:
        print("    paired", r["paired_vs_ladder"])
