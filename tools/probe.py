"""Feed probe, run on GitHub's runners. Round 26: why did the Oct 16 lock
'Cleveland Guardians +2.5' (mlb:401908026) grade void, and is Bruins-Ducks
(nhl:401892518) final?"""
import json
import sys

sys.path.insert(0, ".")
import dashboard as D  # noqa: E402

for path, eid in (("baseball/mlb", "401908026"), ("hockey/nhl", "401892518")):
    s = D.get(f"{D.ESPN}/{path}/summary?event={eid}")
    comp = (((s or {}).get("header") or {}).get("competitions") or [{}])[0]
    st = (comp.get("status") or {}).get("type") or {}
    print(path, eid, comp.get("date"), st.get("name"), st.get("detail"))
    print("   ", [((x.get("team") or {}).get("displayName"), x.get("score")) for x in comp.get("competitors") or []])
