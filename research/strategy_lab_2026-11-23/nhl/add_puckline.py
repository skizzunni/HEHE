"""Fill puck lines missing from games.json (2022-23: books carry no 'close'
block, only 'current'/spreadOdds -- the same last snapshot the moneyline
already falls back to). Uses the SAME book as the stored moneyline, sides
matched by team id. Writes odds.home_spread/home_spread_price/away_spread_price
plus odds.pl_src='current'."""
import concurrent.futures as cf, json, re, sys
sys.path.insert(0, ".")
import os; os.environ.setdefault("LEAGUE", "hockey/nhl")
import nhl_history as H

def pl(g):
    j = H.get(H.ODDS.format(g["id"])) or {}
    for it in j.get("items", []):
        if (it.get("provider") or {}).get("name") != g["odds"]["book"]:
            continue
        side = {}
        for k in ("awayTeamOdds", "homeTeamOdds"):
            x = it.get(k) or {}
            m = re.search(r"/teams/(\d+)", ((x.get("team") or {}).get("$ref") or ""))
            cur = x.get("current") or {}
            pt = H._ml((cur.get("pointSpread") or {}).get("american")) if isinstance(cur.get("pointSpread"), dict) else None
            pr = H._ml((cur.get("spread") or {}).get("american")) if isinstance(cur.get("spread"), dict) else None
            pr = pr if pr is not None else H._ml(x.get("spreadOdds"))
            if m and pt is not None and pr is not None:
                side[m.group(1)] = (pt, pr)
        h, a = side.get(g["home"]["id"]), side.get(g["away"]["id"])
        if h and a and h[0] == -a[0] and abs(h[0]) == 1.5 and 1.0 <= H._imp(h[1]) + H._imp(a[1]) <= 1.12:
            return dict(home_spread=h[0], home_spread_price=h[1], away_spread_price=a[1], pl_src="current")
    return None

gs = json.load(open("games.json"))
todo = [g for g in gs.values() if g.get("odds") and "home_spread" not in g["odds"]]
with cf.ThreadPoolExecutor(8) as ex:
    for g, r in zip(todo, ex.map(pl, todo)):
        if r: g["odds"].update(r)
json.dump(gs, open("games.json", "w"))
print(len(todo), "missing;", sum(1 for g in todo if "home_spread" in g["odds"]), "filled")
