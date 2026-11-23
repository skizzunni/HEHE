"""Ticket-building and staking strategy lab (research only, 2026-11-23).

Replays on the project's own graded records; nothing here bets or writes
outside this folder.

    python3 work/strategy_lab/tickets/lab.py      # writes results.json here

Data
  card   locks.json days: the frozen 8 AM Locks card (~11 legs, one per game),
         graded.  39 cards 2026-10-15..11-22.  The ladder's input.
  pools  locks.json / safe_locks.json pools: the frozen 8 AM candidate pools,
         last 14 days; game lines graded from ledger.json final scores.
  board  ledger.json graded board picks with stated chance and price.

Protocol: each strategy is split into date halves (median day of the data it
uses); z = (cashed - expected) / sqrt(sum p(1-p)) per half, with expected the
8 AM stated chance.  Adopted only at z >= 2.8 in both halves.
"""
import collections
import itertools
import json
import math
import os
import random
import sys

ROOT = "/home/user/HEHE"
OUT = os.path.join(ROOT, "work/strategy_lab/tickets")
sys.path.insert(0, ROOT)
import locks  # noqa: E402
import ledger  # noqa: E402
import ladder  # noqa: E402
import ten_leg  # noqa: E402

BAR = 2.8
dec = locks._dec


# ---------------------------------------------------------------- helpers
def card_days(book):
    out = {}
    for d in sorted(book["days"]):
        keys = book["days"][d]
        keys = keys.get("legs") if isinstance(keys, dict) else keys
        legs = [dict(book["legs"][k], key=k) for k in keys or [] if k in book["legs"]]
        if legs:
            out[d] = legs
    return out


def settled(legs):
    return all(L.get("status") in ("won", "lost", "void", "push") for L in legs)


def cashed(legs):
    return not any(L.get("status") == "lost" for L in legs)


def pay(legs):
    """Payout per $1 if cashed: void/push legs at 1x."""
    return math.prod(dec(L["price"]) if L.get("status") == "won" else 1.0 for L in legs)


def stated(legs, key="p"):
    return math.prod(L[key] for L in legs)


def halves(days):
    days = sorted(days)
    mid = days[len(days) // 2]
    return mid


def zstat(rows):
    """rows: [(won 0/1, p)] -> dict(n, won, exp, z)."""
    n = len(rows)
    w = sum(r[0] for r in rows)
    e = sum(r[1] for r in rows)
    v = sum(r[1] * (1 - r[1]) for r in rows)
    return dict(n=n, won=w, exp=round(e, 2), z=round((w - e) / math.sqrt(v), 2) if v > 0 else None)


def verdict(z1, z2, sign=+1):
    if z1 is None or z2 is None:
        return "rejected (too few)"
    a, b = sign * z1, sign * z2
    if a >= BAR and b >= BAR:
        return "ADOPTED"
    if a > 0 and b > 0 and max(a, b) >= 1.0:
        return "on watch"
    return "rejected"


def money(tix, fracs=(0.1, 0.25, 0.5, 1.0)):
    """tix: [(cashed, pay_if_cashed)] in date order.  Flat $1 ROI, geometric
    mean bank multiple per day at fixed fraction f (f=1 is a full roll), the
    longest cashing streak, and the best bank a $1 full-roll ladder reached."""
    if not tix:
        return {}
    ret = [c * p for c, p in tix]
    out = dict(roi=round(sum(ret) / len(ret) - 1, 3))
    for f in fracs:
        logs = [math.log(1 - f + f * r) if (1 - f + f * r) > 0 else float("-inf") for r in ret]
        g = sum(logs) / len(logs)
        out[f"geo_f{f}"] = round(math.exp(g), 4) if g > float("-inf") else 0.0
    best = streak = run = 0
    bank = 1.0
    peak = 1.0
    for c, p in tix:
        if c:
            run += 1
            bank *= p
            peak = max(peak, bank)
        else:
            run, bank = 0, 1.0
        best = max(best, run)
    out["streak"] = best
    out["peak_bank"] = round(peak, 2)
    return out


def ticket_eval(name, per_day, mid):
    """per_day: {day: legs or []} -> record by half and money."""
    H = {"1st": [], "2nd": []}
    tix, pays, sts = [], [], []
    for d in sorted(per_day):
        legs = per_day[d]
        if not legs or not settled(legs):
            continue
        c = cashed(legs)
        p = stated(legs)
        H["1st" if d < mid else "2nd"].append((int(c), p))
        tix.append((int(c), pay(legs)))
        pays.append(math.prod(dec(L["price"]) for L in legs))
        sts.append(p)
    a, b = zstat(H["1st"]), zstat(H["2nd"])
    n = a["n"] + b["n"]
    return dict(strategy=name, n=n, cashed=a["won"] + b["won"], expected=round(a["exp"] + b["exp"], 2),
                h1=a, h2=b, avg_pays=round(sum(pays) / len(pays), 2) if pays else None,
                avg_legs=round(sum(len(per_day[d]) for d in per_day if per_day[d] and settled(per_day[d])) / max(n, 1), 2),
                ev_stated=round(sum(s * p for s, p in zip(sts, pays)) / len(pays), 3) if pays else None,
                money=money(tix), verdict=None)


def topk(legs, k, key="p"):
    s = sorted(legs, key=lambda L: -L[key])[:k]
    return s if len(s) == k else []


def combo(legs, lo, hi, maxk=8, pool=12, key="p"):
    """ladder.best_combo generalised: highest joint `key` chance paying lo..hi."""
    cand = sorted(legs, key=lambda L: -L[key])[:pool]
    best = None
    for k in range(1, maxk + 1):
        for c in itertools.combinations(cand, k):
            if len({L.get("gid") or L.get("key") for L in c}) < k:
                continue
            pays = math.prod(dec(L["price"]) for L in c)
            if not (lo <= pays <= hi):
                continue
            p = math.prod(L[key] for L in c)
            if best is None or p > best[0] + 1e-12:
                best = (p, list(c))
    return best[1] if best else []


# ---------------------------------------------------------------- data
BOOK = locks.load()
CARD = card_days(BOOK)
CMID = halves(CARD)
LED = ledger.load()


def pool_days():
    """{day: [graded game lines]} from the safe pools (the larger, superset
    pools), one row per line; status from ledger final scores."""
    out = {}
    for path in (locks.SAFE_LEDGER,):
        for d, x in sorted((locks.load(path).get("pools") or {}).items()):
            rows = []
            for L in x.get("legs") or []:
                if L.get("kind") == "prop" or not L.get("spec") or not L.get("p") or not dec(L.get("price")):
                    continue
                st, _ = locks._every_status(L, LED)
                rows.append(dict(L, status=st))
            out[d] = rows
    return out


POOLS = pool_days()
PMID = halves(POOLS)
RES = {}


def best_line_per_game(rows):
    best = {}
    for L in rows:
        g = L["gid"]
        if g not in best or L["p"] > best[g]["p"]:
            best[g] = L
    return sorted(best.values(), key=lambda L: -L["p"])


# ---------------------------------------------------------------- 0. baseline
def s0_baseline():
    runs = ladder.replay(BOOK)
    per = {}
    for r in runs:
        for e in r["days"]:
            per[e["day"]] = e
    H = {"1st": [], "2nd": []}
    tix = []
    mid = halves(per)
    for d, e in sorted(per.items()):
        if e["result"] not in ("won", "lost"):
            continue
        H["1st" if d < mid else "2nd"].append((int(e["result"] == "won"), e["prob"]))
        tix.append((int(e["result"] == "won"), ladder.settle_pay(e)))
    one_leg = sum(1 for e in per.values() if e["result"] == "lost" and sum(L["status"] == "lost" for L in e["legs"]) == 1)
    lost = sum(1 for e in per.values() if e["result"] == "lost")
    a, b = zstat(H["1st"]), zstat(H["2nd"])
    RES["0_ladder_as_run"] = dict(strategy="ladder as run (2026-11-03..)", n=a["n"] + b["n"],
                                  cashed=a["won"] + b["won"], expected=round(a["exp"] + b["exp"], 2), h1=a, h2=b,
                                  lost_on_one_leg=f"{one_leg}/{lost}", money=money(tix), verdict="baseline")
    # the current rule (2x-5x best combo) replayed on every card
    per2 = {d: combo(L, 2.0, 5.0, maxk=6, pool=12) for d, L in CARD.items()}
    r = ticket_eval("current rule 2-5x best combo, all 39 cards", per2, CMID)
    r["verdict"] = "baseline"
    RES["0_current_rule_all_cards"] = r
    return per2


# ---------------------------------------------------------------- 1. size
def s1_size(base):
    out = {}
    bands = [(1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (1.5, 2.5)]
    for lo, hi in bands:
        per = {d: combo(L, lo, hi) for d, L in CARD.items()}
        out[f"target {lo}-{hi}x"] = ticket_eval(f"best combo paying {lo}-{hi}x", per, CMID)
    for k in range(1, 9):
        per = {d: topk(L, k) for d, L in CARD.items()}
        out[f"top {k}"] = ticket_eval(f"top {k} Locks legs", per, CMID)
    for r in out.values():
        # chance of $1 -> $10,000 at the realised cash rate and average payout
        if r["n"] and r["avg_pays"] and r["avg_pays"] > 1 and r["cashed"]:
            need = math.ceil(math.log(10000) / math.log(r["avg_pays"]))
            r["reach_10k_realised"] = dict(wins_needed=need, chance=float(f"{(r['cashed'] / r['n']) ** need:.2e}"))
        # versus its own stated chance (calibration of the ticket); a size
        # cannot be "adopted" on cash rate alone -- fewer legs always cash more
        r["verdict"] = verdict(r["h1"]["z"], r["h2"]["z"])
    RES["1_size"] = out


# ---------------------------------------------------------------- 2. filters
def tip_band(L):
    t = str(L.get("tip") or "")
    try:
        hm, ap = t.split()
        h = int(hm.split(":")[0]) % 12 + (12 if ap.upper() == "PM" else 0)
    except ValueError:
        return "?"
    return "before 1 PM" if h < 13 else "1-6 PM" if h < 18 else "6 PM+"


def price_band(L):
    a = float(str(L["price"]).replace("+", ""))
    return "-500 or shorter" if a <= -500 else "-499..-350" if a <= -350 else "-349..-250" if a <= -250 else "-249 or longer"


def leg_groups(legs_by_day, mid, getters, min_n=8):
    res = {}
    for gname, fn in getters.items():
        acc = collections.defaultdict(lambda: {"1st": [], "2nd": []})
        for d, legs in legs_by_day.items():
            for L in legs:
                if L.get("status") not in ("won", "lost"):
                    continue
                acc[fn(L)]["1st" if d < mid else "2nd"].append((int(L["status"] == "won"), L["p"]))
        for k, h in acc.items():
            a, b = zstat(h["1st"]), zstat(h["2nd"])
            if a["n"] < min_n or b["n"] < min_n:
                continue
            # a filter DROPS a group, so it is supported when the group is short (z negative)
            res[f"{gname}={k}"] = dict(h1=a, h2=b, verdict=("drop ADOPTED" if a["z"] <= -BAR and b["z"] <= -BAR
                                                           else "on watch (short both)" if a["z"] < -1 and b["z"] < -1
                                                           else "keep"))
    return res


def s2_filters(base):
    G = dict(type=ladder.leg_type, league=lambda L: L.get("league"), price=price_band, tip=tip_band,
             type_league=lambda L: f"{L.get('league')}:{ladder.leg_type(L)}")
    card = leg_groups(CARD, CMID, G)
    # pools: one line per game and bet type (alternate lines of a game move together)
    pool1 = {}
    for d, rows in POOLS.items():
        seen = {}
        for L in rows:
            k = (L["gid"], (L.get("spec") or {}).get("t"))
            if k not in seen or L["p"] > seen[k]["p"]:
                seen[k] = L
        pool1[d] = [L for L in seen.values() if 0.70 <= L["p"] <= 0.95]
    pool = leg_groups(pool1, PMID, dict(type=ladder.leg_type, league=lambda L: L.get("league"), price=price_band,
                                         type_league=lambda L: f"{L.get('league')}:{ladder.leg_type(L)}"), min_n=15)
    # walk-forward: before each card, drop (league, type) kinds whose record on
    # earlier cards is short at z <= -2 on 10+ legs; then the 2-5x combo
    hist = collections.defaultdict(list)
    per = {}
    dropped_days = 0
    for d in sorted(CARD):
        bad = set()
        for k, rows in hist.items():
            z = zstat(rows)
            if z["n"] >= 10 and z["z"] is not None and z["z"] <= -2:
                bad.add(k)
        legs = [L for L in CARD[d] if (L.get("league"), ladder.leg_type(L)) not in bad]
        per[d] = combo(legs, 2.0, 5.0, maxk=6)
        dropped_days += sorted(x["key"] for x in per[d]) != sorted(x["key"] for x in (base.get(d) or []))
        for L in CARD[d]:
            if L.get("status") in ("won", "lost"):
                hist[(L.get("league"), ladder.leg_type(L))].append((int(L["status"] == "won"), L["p"]))
    wf = ticket_eval("walk-forward drop of short (league,type) kinds, 2-5x combo", per, CMID)
    wf["tickets_changed"] = dropped_days
    # props out (known study, re-run here on all cards)
    per_np = {d: combo([L for L in legs if L.get("kind") != "prop"], 2.0, 5.0, maxk=6) for d, legs in CARD.items()}
    np_ = ticket_eval("props out, 2-5x combo", per_np, CMID)
    # start-time spread of the current-rule ticket
    def hours(L):
        b = tip_band(L)
        t = str(L.get("tip") or "")
        try:
            hm, ap = t.split()
            h, m = hm.split(":")
            return int(h) % 12 + (12 if ap.upper() == "PM" else 0) + int(m) / 60
        except ValueError:
            return None
    spread = {"tight (<=3h)": {}, "wide (>3h)": {}}
    for d, legs in base.items():
        if not legs:
            continue
        hs = [hours(L) for L in legs if hours(L) is not None]
        if len(hs) < 2:
            continue
        spread["tight (<=3h)" if max(hs) - min(hs) <= 3 else "wide (>3h)"][d] = legs
    sp = {k: ticket_eval(f"current-rule tickets, tip spread {k}", v, CMID) for k, v in spread.items()}
    for r in [wf, np_] + list(sp.values()):
        r["verdict"] = verdict(r["h1"]["z"], r["h2"]["z"])
    RES["2_filters"] = dict(card_leg_groups=card, pool_leg_groups=pool, walk_forward=wf, props_out=np_, tip_spread=sp)


# ---------------------------------------------------------------- 3. shrink
def logloss(rows):
    return sum(-(w * math.log(p) + (1 - w) * math.log(1 - p)) for w, p in rows) / len(rows)


def platt(data, lam=50.0):
    a, b = 0.0, 1.0
    for _ in range(50):
        ga, gb = lam * a, lam * (b - 1)
        haa, hab, hbb = lam, 0.0, lam
        for x, y in data:
            p = 1 / (1 + math.exp(-(a + b * x)))
            r, w = p - y, p * (1 - p)
            ga += r; gb += r * x; haa += w; hab += w * x; hbb += w * x * x
        det = haa * hbb - hab * hab
        a -= (hbb * ga - hab * gb) / det
        b -= (haa * gb - hab * ga) / det
    return a, b


def lg(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def s3_shrink(base):
    out = {}
    legrows = {"1st": [], "2nd": []}
    for d, legs in CARD.items():
        for L in legs:
            if L.get("status") in ("won", "lost"):
                legrows["1st" if d < CMID else "2nd"].append((int(L["status"] == "won"), L["p"]))
    cal = {}
    for lam in (1.0, 0.9, 0.8, 0.7, 0.5):
        cal[f"lambda {lam}"] = {h: round(logloss([(w, 0.5 + lam * (p - 0.5)) for w, p in r]), 4) for h, r in legrows.items()}
        per = {}
        for d, legs in CARD.items():
            L2 = [dict(L, q=0.5 + lam * (L["p"] - 0.5)) for L in legs]
            per[d] = combo(L2, 2.0, 5.0, maxk=6, key="q")
        r = ticket_eval(f"shrink toward 50% lambda={lam}, 2-5x combo", per, CMID)
        r["tickets_changed"] = sum(bool(per[d]) and sorted(x["key"] for x in per[d]) != sorted(x["key"] for x in (base.get(d) or [])) for d in per)
        out[f"shrink {lam}"] = r
    # walk-forward Platt on earlier cards' legs, global and per leg type
    for mode in ("global", "per type"):
        per = {}
        hist = []
        wf_rows = {"1st": [], "2nd": []}
        for d in sorted(CARD):
            fits = {}
            if len(hist) >= 60:
                if mode == "global":
                    fits[None] = platt([(lg(p), w) for _, w, p in hist])
                else:
                    for t in set(t for t, _, _ in hist):
                        sub = [(lg(p), w) for tt, w, p in hist if tt == t]
                        if len(sub) >= 30:
                            fits[t] = platt(sub)
            L2 = []
            for L in CARD[d]:
                f = fits.get(None if mode == "global" else ladder.leg_type(L))
                q = 1 / (1 + math.exp(-(f[0] + f[1] * lg(L["p"])))) if f else L["p"]
                L2.append(dict(L, q=q))
                if L.get("status") in ("won", "lost"):
                    wf_rows["1st" if d < CMID else "2nd"].append((int(L["status"] == "won"), q, L["p"]))
            per[d] = combo(L2, 2.0, 5.0, maxk=6, key="q")
            for L in CARD[d]:
                if L.get("status") in ("won", "lost"):
                    hist.append((ladder.leg_type(L), int(L["status"] == "won"), L["p"]))
        r = ticket_eval(f"walk-forward Platt ({mode}), 2-5x combo", per, CMID)
        r["tickets_changed"] = sum(bool(per[d]) and sorted(x["key"] for x in per[d]) != sorted(x["key"] for x in (base.get(d) or [])) for d in per)
        r["leg_logloss_fit_vs_raw"] = {h: [round(logloss([(w, q) for w, q, _ in v]), 4), round(logloss([(w, p) for w, _, p in v]), 4)] for h, v in wf_rows.items()}
        out[f"platt {mode}"] = r
    for r in out.values():
        r["verdict"] = verdict(r["h1"]["z"], r["h2"]["z"])
    # the relevant test for a picker is cashed vs the CURRENT rule, paired
    RES["3_shrink"] = dict(leg_logloss=cal, tickets=out,
                           card_legs={h: zstat(r) for h, r in legrows.items()})


# ---------------------------------------------------------------- 4. correlation
def clump(by_day, mid, perms=2000, seed=7):
    """Same-day same-league pairs' residual products vs the same legs shuffled
    across days within league (keeps each league's calibration)."""
    rng = random.Random(seed)
    res = {}
    for half in ("1st", "2nd"):
        legs = [(d, L.get("league"), int(L["status"] == "won") - L["p"]) for d, ls in by_day.items()
                if (d < mid) == (half == "1st") for L in ls if L.get("status") in ("won", "lost")]
        bylg = collections.defaultdict(list)
        for d, l, r in legs:
            bylg[l].append((d, r))

        def stat(groups):
            s = 0.0
            for lgname, rows in groups.items():
                acc = collections.defaultdict(float)
                sq = 0.0
                for d, r in rows:
                    acc[d] += r
                    sq += r * r
                s += (sum(v * v for v in acc.values()) - sq) / 2   # sum over pairs
            return s
        obs = stat(bylg)
        npairs = sum(sum(c * (c - 1) / 2 for c in collections.Counter(d for d, _ in rows).values()) for rows in bylg.values())
        null = []
        for _ in range(perms):
            g2 = {}
            for l, rows in bylg.items():
                ds = [d for d, _ in rows]
                rs = [r for _, r in rows]
                rng.shuffle(rs)
                g2[l] = list(zip(ds, rs))
            null.append(stat(g2))
        m = sum(null) / len(null)
        sd = math.sqrt(sum((x - m) ** 2 for x in null) / (len(null) - 1))
        res[half] = dict(legs=len(legs), same_day_league_pairs=int(npairs), obs=round(obs, 3), null_mean=round(m, 3),
                         z=round((obs - m) / sd, 2) if sd else None,
                         p_one_sided=round(sum(x >= obs for x in null) / len(null), 4))
    return res


def s4_corr():
    card = clump(CARD, CMID)
    pool = clump({d: best_line_per_game(r) for d, r in POOLS.items()}, PMID)
    # tickets: top-K Locks legs, single-league vs mixed
    single, mixed = {}, {}
    for k in (2, 3, 4, 5):
        for d, legs in CARD.items():
            t = topk(legs, k)
            if not t:
                continue
            (single if len({L.get("league") for L in t}) == 1 else mixed)[(d, k)] = t
    def ev(name, per):
        H = {"1st": [], "2nd": []}
        for (d, k), t in per.items():
            if settled(t):
                H["1st" if d < CMID else "2nd"].append((int(cashed(t)), stated(t)))
        a, b = zstat(H["1st"]), zstat(H["2nd"])
        return dict(strategy=name, h1=a, h2=b)
    # same on the pools: the 2x every-game ticket
    sp, mp = {}, {}
    for d, rows in POOLS.items():
        eg = best_line_per_game(rows)
        for k in (2, 3, 4, 5, 6, 8):
            t = eg[:k]
            if len(t) == k:
                (sp if len({L.get("league") for L in t}) == 1 else mp)[(d, k)] = t
    def evp(name, per):
        H = {"1st": [], "2nd": []}
        for (d, k), t in per.items():
            if all(L["status"] in ("won", "lost", "void") for L in t):
                H["1st" if d < PMID else "2nd"].append((int(cashed(t)), stated(t)))
        return dict(strategy=name, h1=zstat(H["1st"]), h2=zstat(H["2nd"]))
    out = dict(card_pairs=card, pool_pairs=pool,
               card_single_league=ev("top-K (2-5) Locks tickets all one league", single),
               card_mixed=ev("top-K (2-5) Locks tickets mixed leagues", mixed),
               pool_single_league=evp("top-K every-game tickets all one league", sp),
               pool_mixed=evp("top-K every-game tickets mixed leagues", mp))
    # verdict: correlation is a positive-z finding (clumping)
    for k in ("card_pairs", "pool_pairs"):
        z1, z2 = out[k]["1st"]["z"], out[k]["2nd"]["z"]
        out[k]["verdict"] = ("ADOPTED (clumping)" if z1 >= BAR and z2 >= BAR else
                             "on watch" if z1 > 1 and z2 > 1 else "rejected (no clumping found)")
    RES["4_correlation"] = out


# ---------------------------------------------------------------- 5. staking
def board_rows():
    rows = []
    for e in LED.values():
        if e.get("status") not in ("won", "lost"):
            continue
        f = e.get("first") or {}
        conf = f.get("conf", e.get("conf"))
        price = f.get("price") or e.get("first_price") or e.get("price")
        d = e.get("date")
        if not conf or not price or not d:
            continue
        try:
            dd = dec(price)
        except (TypeError, ValueError):
            continue
        if not dd or dd <= 1:
            continue
        rows.append(dict(d=d, p=conf / 100, dec=dd, w=int(e["status"] == "won"), lg=e.get("league")))
    return rows


def s5_staking():
    rows = board_rows()
    mid = halves({r["d"] for r in rows})
    out = {}

    def flat(sel, name):
        res = {}
        for half in ("1st", "2nd"):
            R = [r for r in sel if (r["d"] < mid) == (half == "1st")]
            if not R:
                res[half] = dict(n=0)
                continue
            prof = [r["w"] * r["dec"] - 1 for r in R]
            sd = math.sqrt(sum(r["p"] * (1 - r["p"]) * r["dec"] ** 2 for r in R))
            res[half] = dict(n=len(R), roi=round(sum(prof) / len(R), 4), stated_ev=round(sum(r["p"] * r["dec"] - 1 for r in R) / len(R), 4),
                             z_vs_zero=round(sum(prof) / sd, 2) if sd else None,
                             hit=round(sum(r["w"] for r in R) / len(R), 3), stated_hit=round(sum(r["p"] for r in R) / len(R), 3))
        res["strategy"] = name
        res["verdict"] = verdict(res["1st"].get("z_vs_zero"), res["2nd"].get("z_vs_zero"))
        return res
    out["flat all picks"] = flat(rows, "flat $1 on every graded board pick")
    pos = [r for r in rows if r["p"] * r["dec"] > 1]
    out["flat stated-edge>0"] = flat(pos, "flat $1 where stated chance x price > 1")

    def kelly(sel, k, pfun, name):
        res = {}
        for half in ("1st", "2nd"):
            byd = collections.defaultdict(list)
            for r in sel:
                if (r["d"] < mid) == (half == "1st"):
                    byd[r["d"]].append(r)
            logs, nb = [], 0
            for d in sorted(byd):
                stakes = []
                for r in byd[d]:
                    p = pfun(r)
                    if p is None:
                        continue
                    b = r["dec"] - 1
                    f = (p * b - (1 - p)) / b
                    if f > 0:
                        stakes.append((k * f, r))
                tot = sum(s for s, _ in stakes)
                if tot > 1:
                    stakes = [(s / tot, r) for s, r in stakes]
                nb += len(stakes)
                m = 1 + sum(s * (r["w"] * r["dec"] - 1) for s, r in stakes)
                logs.append(math.log(max(m, 1e-9)))
            res[half] = dict(days=len(logs), bets=nb, growth=round(math.exp(sum(logs)), 4) if logs else None,
                             geo_per_day=round(math.exp(sum(logs) / len(logs)), 5) if logs else None)
        res["strategy"] = name
        g1, g2 = res["1st"]["growth"], res["2nd"]["growth"]
        res["verdict"] = "positive both halves (not a z test)" if g1 and g2 and g1 > 1 and g2 > 1 and res["1st"]["bets"] and res["2nd"]["bets"] else "rejected"
        return res
    for k in (0.1, 0.25, 0.5):
        out[f"kelly {k} stated"] = kelly(rows, k, lambda r: r["p"], f"Kelly x{k} on stated chance")
    # walk-forward: chance = earlier picks' hit rate in the same 5-point stated
    # band (shrunk to stated with 50 pseudo-picks), from days strictly before
    days = sorted({r["d"] for r in rows})
    band = lambda p: int(p * 20)
    cum = collections.defaultdict(lambda: [0, 0.0, 0])
    est = {}
    byd = collections.defaultdict(list)
    for r in rows:
        byd[r["d"]].append(r)
    for d in days:
        for r in byd[d]:
            w, ps, n = cum[band(r["p"])]
            est[id(r)] = (w + 50 * r["p"]) / (n + 50) if n >= 50 else None
        for r in byd[d]:
            c = cum[band(r["p"])]
            c[0] += r["w"]; c[1] += r["p"]; c[2] += 1
    for k in (0.1, 0.25, 0.5):
        out[f"kelly {k} wf-band"] = kelly(rows, k, lambda r: est.get(id(r)),
                                          f"Kelly x{k} on walk-forward band hit rate")
    wfpos = [r for r in rows if est.get(id(r)) and est[id(r)] * r["dec"] > 1]
    out["flat wf-band edge>0"] = flat(wfpos, "flat $1 where walk-forward band rate x price > 1")
    # Kelly on the ladder tickets themselves (stated joint chance x payout)
    lt = []
    for d, legs in CARD.items():
        t = combo(legs, 2.0, 5.0, maxk=6)
        if t and settled(t):
            lt.append((stated(t), math.prod(dec(L["price"]) for L in t)))
    out["ladder ticket stated EV"] = dict(n=len(lt), mean_stated_ev=round(sum(p * q for p, q in lt) / len(lt) - 1, 4),
                                          positive_ev_tickets=sum(p * q > 1 for p, q in lt),
                                          note="Kelly stakes 0 on a ticket with stated EV <= 0")
    out["_mid"] = mid
    RES["5_staking"] = out


# ---------------------------------------------------------------- 7. every-game targets
def s7_everygame(base):
    out = {}
    per_ladder = {d: base.get(d) for d in POOLS if base.get(d)}
    out["ladder rule on pool days"] = ticket_eval("current ladder rule, pool days", per_ladder, PMID)
    for T in (1.5, 2.0, 3.0):
        per = {}
        for d, rows in POOLS.items():
            eg = [dict(L, status="open", _st=L["status"]) for L in best_line_per_game(rows)]
            t = ten_leg.to_target(eg, T)
            per[d] = [dict(L, status=L["_st"]) for L in t["legs"]] if t else []
        r = ticket_eval(f"every-game safest lines to {T}x", per, PMID)
        both = [d for d in per if per[d] and settled(per[d]) and per_ladder.get(d) and settled(per_ladder[d])]
        only_eg = sum(cashed(per[d]) and not cashed(per_ladder[d]) for d in both)
        only_l = sum(cashed(per_ladder[d]) and not cashed(per[d]) for d in both)
        r["paired_vs_ladder"] = dict(days=len(both), only_everygame=only_eg, only_ladder=only_l,
                                     z=round((only_eg - only_l) / math.sqrt(only_eg + only_l), 2) if only_eg + only_l else None)
        r["verdict"] = verdict(r["h1"]["z"], r["h2"]["z"])
        out[f"every-game {T}x"] = r
    # same payout, same days: Locks best 1.5-2x combo vs every-game to 1.5x
    lk = {d: combo(CARD[d], 1.5, 2.0) for d in POOLS if d in CARD}
    eg15 = {}
    for d, rows in POOLS.items():
        eg = [dict(L, status="open", _st=L["status"]) for L in best_line_per_game(rows)]
        t = ten_leg.to_target(eg, 1.5)
        eg15[d] = [dict(L, status=L["_st"]) for L in t["legs"]] if t else []
    r = ticket_eval("Locks best 1.5-2x combo, pool days", lk, PMID)
    both = [d for d in lk if lk[d] and settled(lk[d]) and eg15.get(d) and settled(eg15[d])]
    a = sum(cashed(eg15[d]) and not cashed(lk[d]) for d in both)
    b = sum(cashed(lk[d]) and not cashed(eg15[d]) for d in both)
    r["paired_everygame1.5_vs_this"] = dict(days=len(both), only_everygame=a, only_locks=b,
                                             z=round((a - b) / math.sqrt(a + b), 2) if a + b else None)
    r["verdict"] = "comparison"
    out["locks 1.5x on pool days"] = r
    # cross-check against the project's own function
    out["check ten_leg.to_target_days 2x"] = ten_leg.to_target_days(locks.SAFE_LEDGER)
    for T in (1.25,):
        per = {}
        for d, rows in POOLS.items():
            eg = [dict(L, status="open", _st=L["status"]) for L in best_line_per_game(rows)]
            t = ten_leg.to_target(eg, T)
            per[d] = [dict(L, status=L["_st"]) for L in t["legs"]] if t else []
        r = ticket_eval(f"every-game safest lines to {T}x", per, PMID)
        r["verdict"] = verdict(r["h1"]["z"], r["h2"]["z"])
        out[f"every-game {T}x"] = r
    # fixed counts of the safest every-game lines
    for k in (1, 2, 3, 4, 5, 6, 8, 10, 12, 15):
        per = {d: best_line_per_game(rows)[:k] for d, rows in POOLS.items()}
        per = {d: v for d, v in per.items() if len(v) == k}
        r = ticket_eval(f"top {k} every-game lines", per, PMID)
        r["verdict"] = verdict(r["h1"]["z"], r["h2"]["z"])
        out[f"every-game top {k}"] = r
    # the mechanism: every-game safest lines by stated band
    bands = collections.defaultdict(lambda: {"1st": [], "2nd": []})
    for d, rows in POOLS.items():
        for L in best_line_per_game(rows):
            if L["status"] in ("won", "lost"):
                b = "95%+" if L["p"] >= 0.95 else "90-95%" if L["p"] >= 0.90 else "85-90%" if L["p"] >= 0.85 else "<85%"
                bands[b]["1st" if d < PMID else "2nd"].append((int(L["status"] == "won"), L["p"]))
    out["every-game legs by band"] = {b: dict(h1=zstat(v["1st"]), h2=zstat(v["2nd"])) for b, v in bands.items()}
    RES["7_everygame"] = out


if __name__ == "__main__":
    base = s0_baseline()
    s1_size(base)
    s2_filters(base)
    s3_shrink(base)
    s4_corr()
    s5_staking()
    s7_everygame(base)
    RES["_meta"] = dict(card_days=len(CARD), card_first=min(CARD), card_last=max(CARD), card_mid=CMID,
                        pool_days=len(POOLS), pool_first=min(POOLS), pool_last=max(POOLS), pool_mid=PMID, bar=BAR)
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(RES, fh, indent=1, default=str)
    print(json.dumps(RES["_meta"]))
