"""Feed probe, run on GitHub's runners. Round 15: does each locks leg's
FanDuel id (marketId:selectionId) really name the line the card shows?"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")
import fanduel  # noqa: E402

book = json.load(open("locks.json"))
want = {book["legs"][k]["fd"]: book["legs"][k] for k in book["days"]["2026-10-15"]}
FD = fanduel.load()
seen = {}
for lg, games in FD.items():
    for g in games:
        d = fanduel._get(f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={g['id']}&tab=popular"
                         "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
        for m in (((d or {}).get("attachments") or {}).get("markets") or {}).values():
            for r in m.get("runners") or []:
                ref = f'{m.get("marketId")}:{r.get("selectionId")}'
                if ref in want:
                    seen[ref] = (m.get("marketType"), m.get("marketName"), r.get("runnerName"), r.get("handicap"),
                                 ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
        time.sleep(0.2)
for ref, L in want.items():
    print(f'{L["label"]:<38} card {L.get("price")!s:>7} | FanDuel says: {seen.get(ref, "NOT FOUND")}')
