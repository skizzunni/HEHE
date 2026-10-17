"""Feed probe, run on GitHub's runners. Round 25: what UFC grading and pricing
need. (1) FanDuel MMA runner fields: handicap on Total Rounds, ids for the
bet slip, every market name on a fight. (2) ESPN MMA results: how a finished
fight reports winner, method and round."""
import datetime as dt
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
import fanduel as F  # noqa: E402
import picks as P  # noqa: E402

d = F._get(f"{F.BASE}/content-managed-page?page=SPORT&eventTypeId=26420387"
           f"&_ak={F.AK}&timezone=America%2FNew_York")
ev = ((d or {}).get("attachments") or {}).get("events") or {}
print("fights listed:", len(ev), sorted({(e.get("openDate") or "")[:10] for e in ev.values()}))
e = sorted(ev.values(), key=lambda e: e.get("openDate") or "")[0]
print("first:", e.get("eventId"), e.get("name"), e.get("openDate"), "competition", e.get("competitionId"))
base = (f"{F.BASE}/event-page?_ak={F.AK}&eventId={e['eventId']}"
        "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
names = Counter()
for t in ("", "method-of-victory", "round-props", "time-props"):
    p = F._get(base + ("&tab=" + t if t else ""))
    for m in (((p or {}).get("attachments") or {}).get("markets") or {}).values():
        names[m.get("marketType")] += 1
        if m.get("marketType") in ("TOTAL_ROUNDS", "WILL_THE_FIGHT_GO_THE_DISTANCE?", "ROUND_BETTING",
                                   "MATCH_BETTING") or "ROUND" in (m.get("marketType") or "")[:6]:
            r = (m.get("runners") or [{}])[0]
            print("  ", m.get("marketType"), "| marketId", m.get("marketId"), "| runner keys",
                  sorted(r.keys())[:14], "| handicap", r.get("handicap"), "| sel", r.get("selectionId"),
                  "|", m.get("marketName"))
print("market types:", names.most_common(30))

# ESPN MMA: last weekend's results
for back in range(1, 9):
    day = (dt.date.today() - dt.timedelta(days=back)).strftime("%Y%m%d")
    sb = P.get(f"{P.ESPN}/mma/ufc/scoreboard?dates={day}")
    done = []
    for ev2 in sb.get("events") or []:
        for c in ev2.get("competitions") or []:
            st = (c.get("status") or {}).get("type") or {}
            if st.get("completed"):
                done.append((ev2, c))
    if done:
        print("ESPN", day, len(done), "finished fights")
        for ev2, c in done[:3]:
            st = c.get("status") or {}
            print("   status:", json.dumps({k: st.get(k) for k in ("period", "displayClock", "type", "result")})[:600])
            print("   competitors:", [((x.get("athlete") or {}).get("displayName"), x.get("winner")) for x in c.get("competitors") or []])
            print("   comp keys:", sorted(c.keys()))
            for k in ("details", "notes", "headlines", "situation", "format"):
                if c.get(k):
                    print("   ", k, json.dumps(c.get(k))[:400])
        break
