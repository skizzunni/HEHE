"""Feed probe, run on GitHub's runners. Round 21: why did today's WTA picks
carry no Kalshi price? For every open KXATPMATCH / KXWTAMATCH market: the
spread (wide ones are dropped), and which of ESPN's scheduled singles players
for today and tomorrow match a Kalshi name and which do not."""
import datetime as dt
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
import kalshi as K  # noqa: E402
import picks as P  # noqa: E402

names, spreads = {}, Counter()
for ser in ("KXATPMATCH", "KXWTAMATCH"):
    evs = K._series(ser)
    print(f"{ser}: {len(evs)} open events")
    for ev in evs:
        for m in ev.get("markets") or []:
            y, n = K._price(m, "yes"), K._price(m, "no")
            who = K._norm(m.get("yes_sub_title"))
            if not who:
                continue
            sp = None if not y or not n else round(y - (1 - n), 3)
            names[who] = (ser, sp, y, n, m.get("last_price_dollars") or m.get("last_price"),
                          ev.get("title"))
            spreads[("none" if sp is None else "<=.08" if 0 <= sp <= 0.08
                      else "<=.15" if 0 <= sp <= 0.15 else ">.15")] += 1
print("spread buckets:", dict(spreads))
for i, (k, v) in enumerate(names.items()):
    if i < 12:
        print("  ", k, v)

today = dt.datetime.now(P.ET).date() if hasattr(P, "ET") else dt.date.today()
for d in (today, today + dt.timedelta(days=1)):
    tag = d.strftime("%Y%m%d")
    for tour in ("atp", "wta"):
        sb = P.get(f"{P.ESPN}/tennis/{tour}/scoreboard?dates={tag}")
        hit, miss = [], []
        for ev in sb.get("events", []):
            for grp in ev.get("groupings") or []:
                gname = (grp.get("grouping") or {}).get("displayName", "")
                if "Singles" not in gname:
                    continue
                for c in grp.get("competitions") or []:
                    st = ((c.get("status") or {}).get("type") or {})
                    if st.get("completed"):
                        continue
                    for x in c.get("competitors") or []:
                        nm = (x.get("athlete") or {}).get("displayName")
                        if not nm:
                            continue
                        (hit if K._norm(nm) in names else miss).append(
                            (nm, ev.get("name"), names.get(K._norm(nm), (None, None))[1]))
        print(f"{tag} {tour}: matched {len(hit)} unmatched {len(miss)}")
        for h in hit[:8]:
            print("   hit ", h)
        tour_names = Counter(e for _, e, _ in miss)
        print("   unmatched by event:", tour_names.most_common(6))
        for m in miss[:15]:
            print("   miss", m)
# names on Kalshi that look like a surname match but differ
espn_last = {}
print("kalshi sample by series:", Counter(v[0] for v in names.values()))
print(json.dumps(sorted(names)[:60]))
