"""Feed probe, run on GitHub's runners. Round 16: 11 Europa League "1+ shots"
props at -900 to -2500 graded as 0 shots. Real zero-shot games, or a misread?
Print each lost player's ESPN roster entry (every stat) and, for contrast,
one winner's."""
import json
import sys
import urllib.request

sys.path.insert(0, ".")
import props_ledger as PL  # noqa: E402

book = json.load(open("props.json"))
want = [e for e in book.values() if e["league"] == "uel" and e["market"].startswith("Shots")
        and e["status"] in ("lost", "won")]
seen = set()
for e in want:
    eid = e["gid"].split(":", 1)[1]
    d = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{PL.SITE}/soccer/uefa.europa/summary?event={eid}", headers={"User-Agent": "Mozilla/5.0"}),
        timeout=25))
    hit = None
    for team in d.get("rosters") or []:
        for pl in team.get("roster") or []:
            if str((pl.get("athlete") or {}).get("id")) == str(e["aid"]):
                hit = pl
    st = {x.get("name"): x.get("value") for x in (hit or {}).get("stats") or []}
    print(f'{e["status"]:5} {e["name"]:<22} {e["market"]} {e["line"]} {e["price"]}: '
          f'starter={(hit or {}).get("starter")} subIn={(hit or {}).get("subbedIn")} '
          f'subOut={(hit or {}).get("subbedOut")} stats={json.dumps(st)[:400]}')
    if eid not in seen:
        seen.add(eid)
        bs = (d.get("boxscore") or {}).get("teams") or []
        print("   team stats:", [{s.get("name"): s.get("displayValue") for s in t.get("statistics") or []
                                   if "hot" in (s.get("name") or "")} for t in bs])
