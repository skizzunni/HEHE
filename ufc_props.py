"""UFC fight markets from FanDuel, priced and graded like every other prop.

FanDuel lists MMA under its sport page (eventTypeId 26420387), not a custom
page -- which is why the ufc/mma page ids came back empty. Each fight's
event page carries, depending on the fight:

    Moneyline                      -> Winner          (per fighter)
    Method of Victory              -> Method          (fighter by KO/TKO, Submission, Points)
    How fight will End             -> Ends by         (KO/TKO, Submission, Points)
    Will the fight go the distance -> Goes the distance (Yes / No)
    Total Rounds                   -> Total Rounds    (over / under N.5)

Round-combo and double-chance markets overlap one another, so there is no
honest way to take the margin out of them; they are left alone.

A leg's chance is FanDuel's price with the margin removed across that
market's own runners, used unadjusted (lottery.market_chance) -- the same
rule the locks and lottery use.

Grading reads ESPN's MMA scoreboard: the winner flag, the result type in
`details` ("Unofficial Winner Decision" / "Kotko" / "Submission"), and the
final round and clock. A draw, no contest or DQ voids every market.
"""
import datetime as dt
import json
import os
import re
import time
import unicodedata
import urllib.request

import fanduel

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "ufc_props")
TTL = 600
MMA = "26420387"
TABS = ("", "method-of-victory", "round-props", "time-props")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates="
MARKETS = ("Winner", "Method", "Ends by", "Goes the distance", "Total Rounds")
ROUND_MIN = 5.0


def _norm(x):
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", x.lower()).strip()


def _last(x):
    w = _norm(x).split()
    return w[-1] if w else ""


def _imp(o):
    try:
        v = float(o)
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def _odds(r):
    return ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")


def _price(o):
    v = int(float(o))
    return f"+{v}" if v > 0 else str(v)


# ------------------------------------------------------------------ fetch
def events():
    """[{eventId, name, start}] for every MMA fight FanDuel lists."""
    d = fanduel._get(f"{fanduel.BASE}/content-managed-page?page=SPORT&eventTypeId={MMA}"
                     f"&_ak={fanduel.AK}&timezone=America%2FNew_York")
    ev = ((d or {}).get("attachments") or {}).get("events") or {}
    return [dict(eventId=e.get("eventId"), name=e.get("name") or "", start=e.get("openDate"))
            for e in ev.values() if e.get("eventId")]


def markets(event_id):
    """Every market on one fight, from the main page and its prop tabs."""
    f = os.path.join(CACHE, f"{event_id}.json")
    try:
        if time.time() - os.path.getmtime(f) < TTL:
            with open(f) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    base = (f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={event_id}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    out = {}
    for t in TABS:
        p = fanduel._get(base + ("&tab=" + t if t else ""))
        out.update(((p or {}).get("attachments") or {}).get("markets") or {})
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(f, "w") as fh:
            json.dump(out, fh)
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ parse
def _devig(runners):
    """[(runner, fair chance)] with the market's margin removed, or [] when a
    price is missing (a partial market cannot be de-vigged honestly)."""
    imps = [_imp(_odds(r)) for r in runners]
    if not runners or any(i is None for i in imps):
        return []
    import devig
    fv = devig.fair_implied(*imps) if len(imps) > 1 else None
    return list(zip(runners, fv)) if fv else []


def _method(text):
    t = text.lower()
    if "ko" in t:
        return "KO/TKO"
    if "sub" in t:
        return "Submission"
    if "point" in t or "decision" in t:
        return "Points"
    return None


def parse(mk, fighters):
    """Props for one fight. `fighters` is the two names as ESPN spells them,
    so a leg's name grades against ESPN's result."""
    import lottery
    by_last = {_last(f): f for f in fighters}

    def who(text):
        for w in _norm(text).split():
            if w in by_last:
                return by_last[w]
        return None

    out = []

    def add(name, market, line, label, r, p, m):
        o = _odds(r)
        if o is None:
            return
        out.append(dict(name=name, market=market, line=line, label=label, price=_price(o),
                        imp=round(_imp(o), 4), p=round(lottery.market_chance(p), 4), aid=None,
                        fd=f'{m.get("marketId")}:{r.get("selectionId")}',
                        where=f'{m.get("marketName")}: {r.get("runnerName")}'))

    for m in mk.values():
        kind = (m.get("marketType") or "").upper()
        runners = [r for r in m.get("runners") or [] if (r.get("runnerStatus") or "ACTIVE") == "ACTIVE"]
        if kind == "MATCH_BETTING":
            for r, p in _devig(runners):
                f = who(r.get("runnerName"))
                if f:
                    add(f, "Winner", "win", f"{f} to win", r, p, m)
        elif kind == "METHOD_OF_VICTORY":
            for r, p in _devig(runners):
                f, how = who(r.get("runnerName")), _method(r.get("runnerName") or "")
                if f and how:
                    add(f, "Method", how, f"{f} by {how}", r, p, m)
        elif kind == "HOW_FIGHT_WILL_END":
            for r, p in _devig(runners):
                how = _method(r.get("runnerName") or "")
                if how:
                    add("Fight", "Ends by", how, f"Fight ends by {how}", r, p, m)
        elif kind.startswith("WILL_THE_FIGHT_GO_THE_DISTANCE"):
            for r, p in _devig(runners):
                yn = (r.get("runnerName") or "").strip().lower()
                if yn in ("yes", "no"):
                    add("Fight", "Goes the distance", yn.title(),
                        "Fight goes the distance" if yn == "yes" else "Fight does not go the distance",
                        r, p, m)
        elif kind == "TOTAL_ROUNDS":
            for r, p in _devig(runners):
                h, side = r.get("handicap"), (r.get("runnerName") or "").lower()
                if h is None or side not in ("over", "under"):
                    continue
                line = f"{'' if side == 'over' else 'u'}{float(h):g}"
                add("Fight", "Total Rounds", line, f"{side.title()} {float(h):g} rounds", r, p, m)
    return out


def for_slot(board_slot, labels=None):
    """Prop games for the board's UFC fights, shaped like player_props.for_slot."""
    rows = (board_slot or {}).get("ufc") or []
    if not rows:
        return []
    try:
        evs = events()
    except Exception:
        return []
    out = []
    for row in rows:
        names = [n.strip() for n in re.split(r"\s+(?:vs\.?|v|@)\s+", row.get("label") or "") if n.strip()]
        if len(names) != 2:
            continue
        lasts = {_last(n) for n in names}
        e = next((e for e in evs if lasts <= {_last(x) for x in re.split(r"\s+v\s+", e["name"])}), None)
        if not e:
            continue
        try:
            import datetime as dt
            q = dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(CACHE, f'{e["eventId"]}.json')),
                                          dt.timezone.utc).isoformat(timespec="seconds")
        except OSError:
            q = None
        props = [dict(p, gid=row["id"], quoted=q) for p in parse(markets(e["eventId"]), names)
                 if 0.30 <= p["p"] <= 0.97]
        props.sort(key=lambda p: -p["p"])
        if props:
            out.append(dict(id=row["id"], lg=(labels or {}).get("ufc", "UFC"),
                            match=row.get("label", ""), tip=row.get("tip"), props=props[:40]))
    return out


# ------------------------------------------------------------------ grading
def _scoreboard(day):
    try:
        with urllib.request.urlopen(ESPN + day, timeout=25) as r:
            return json.load(r)
    except Exception:
        return {}


def result(comp):
    """{winner, method, minutes, rounds} for a finished fight, or None when it
    is not final or has no winner (draw / no contest: every market voids).
    `method` is None when ESPN has not posted the result line yet -- seen
    live: a fight's details read only "Fight Over, Round End, ..." -- so the
    markets that need it wait instead of being voided."""
    st = (comp.get("status") or {}).get("type") or {}
    if not st.get("completed"):
        return None
    winner = next(((x.get("athlete") or {}).get("displayName") for x in comp.get("competitors") or []
                   if x.get("winner")), None)
    if not winner:
        return None
    how = None
    for d in comp.get("details") or []:
        m = re.search(r"winner\s+(\w+)", (d.get("type") or {}).get("text") or "", re.I)
        if m:
            how = _method(m.group(1).replace("kotko", "ko"))
            break
    s = comp.get("status") or {}
    try:
        mm, ss = (s.get("displayClock") or "0:00").split(":")
        minutes = (int(s.get("period") or 1) - 1) * ROUND_MIN + int(mm) + int(ss) / 60
    except ValueError:
        minutes = None
    rounds = ((comp.get("format") or {}).get("regulation") or {}).get("periods")
    return dict(winner=winner, method=how, minutes=minutes, rounds=rounds)


def went_distance(res):
    """Did the fight reach the final bell? The result line answers it when
    ESPN has posted one; otherwise the clock does -- a fight stopped before
    the last round's 5:00 did not go the distance. ESPN's result line has come
    late or never (a prop was voided for it on 2026-10-17), and voiding a
    settled question throws away a graded leg. None when neither is known."""
    if res.get("method") is not None:
        return res["method"] == "Points"
    m, r = res.get("minutes"), res.get("rounds")
    if m is None or not r:
        return None
    return m >= r * ROUND_MIN - 0.01


def settle(e, res):
    """'won' / 'lost' for one recorded UFC leg given the fight's result."""
    mk, line = e["market"], str(e["line"])
    if mk in ("Method", "Ends by") and res.get("method") is None:
        return None                     # result line not posted yet: wait
    if mk == "Goes the distance" and went_distance(res) is None:
        return None
    if mk == "Total Rounds" and res.get("minutes") is None:
        return None
    if mk == "Winner":
        ok = _norm(res["winner"]) == _norm(e["name"])
    elif mk == "Method":
        ok = _norm(res["winner"]) == _norm(e["name"]) and res["method"] == line
    elif mk == "Ends by":
        ok = res["method"] == line
    elif mk == "Goes the distance":
        ok = went_distance(res) == (line == "Yes")
    elif mk == "Total Rounds":
        under = line.startswith("u")
        x = float(line.lstrip("u"))
        ok = (res["minutes"] < x * ROUND_MIN) if under else (res["minutes"] > x * ROUND_MIN)
    else:
        return None
    return "won" if ok else "lost"


def grade(entries):
    """Settle open UFC legs in place from ESPN's scoreboard."""
    by_day = {}
    for e in entries:
        by_day.setdefault(e.get("date") or "", []).append(e)
    for day, es in by_day.items():
        if not day:
            continue
        comps = {}
        d0 = dt.date.fromisoformat(day)
        for d in (d0, d0 + dt.timedelta(days=1)):
            for ev in (_scoreboard(d.strftime("%Y%m%d")).get("events") or []):
                for c in ev.get("competitions") or []:
                    comps[str(c.get("id"))] = c
        for e in es:
            c = comps.get(e["gid"].split(":", 1)[1])
            if not c:
                continue
            st = ((c.get("status") or {}).get("type") or {})
            if not st.get("completed"):
                continue
            res = result(c)
            if res is None:
                e["status"] = "void"
                continue
            s = settle(e, res)
            if s is None:
                # waiting on ESPN's result line; give up after three days
                if (dt.date.today() - dt.date.fromisoformat(e["date"])).days > 3:
                    e["status"] = "void"
                continue
            e["status"] = s
            if res.get("minutes") is not None:
                e["value"] = round(res["minutes"], 2)
