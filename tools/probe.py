"""Feed probe, run on GitHub's runners. Round 29: tonight's finished UFC
fights as ESPN reports them -- why did 'Steven Koslow to win' grade void?"""
import json
import sys

sys.path.insert(0, ".")
import ufc_props as U  # noqa: E402

for day in ("20261017", "20261018"):
    sb = U._scoreboard(day)
    for ev in sb.get("events") or []:
        for c in ev.get("competitions") or []:
            st = (c.get("status") or {}).get("type") or {}
            if not st.get("completed"):
                continue
            who = [((x.get("athlete") or {}).get("displayName"), x.get("winner")) for x in c.get("competitors") or []]
            det = [((d.get("type") or {}).get("text")) for d in (c.get("details") or [])[:4]]
            print(day, c.get("id"), who, "| details:", det, "| period", (c.get("status") or {}).get("period"),
                  (c.get("status") or {}).get("displayClock"), "| result():", U.result(c))
