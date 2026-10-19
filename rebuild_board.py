"""Re-research every league and regenerate board.html for republishing.

    python3 rebuild_board.py

Fetches upcoming games for today and tomorrow across all twelve leagues, diffs
against the previous run, rewrites the embedded data block inside board.html,
and prints what changed. Publishing the file is a separate step (the Artifact
tool) because only a Claude session can do that.

Why this exists: a published Artifact cannot fetch anything. Its CSP blocks all
outbound requests, and none of the available runtime capabilities grant network
access. The page can only ever hold data baked in at publish time, so keeping it
current means re-baking and republishing it -- which is what this does.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BOARD = os.path.join(HERE, "board.html")
STATE = os.path.join(HERE, ".cache", "last_board.json")

import dashboard as d          # noqa: E402
import ledger                  # noqa: E402
import parlays                 # noqa: E402
import stacks                  # noqa: E402
import fanduel                 # noqa: E402
import kalshi                  # noqa: E402
import player_props            # noqa: E402
import props_ledger             # noqa: E402
import locks                    # noqa: E402
import calls                    # noqa: E402
import lottery                  # noqa: E402


def snapshot():
    """Fresh research for both days, one row per game, best picks first.

    The same pass also feeds the ledger: every pick on the board is recorded,
    anything that has finished is graded, and the running record goes onto the
    page. Research happens once and both consumers read the same state.
    """
    d.refresh()
    # Grading is a separate concern from research. When it throws, the board
    # itself is still perfectly good, so losing the whole rebuild -- and with
    # it the Pages deploy, since the deploy job is skipped when build fails --
    # costs far more than the missed grading pass. About half the scheduled
    # runs were dying somewhere in here with no way to tell where: Actions
    # logs need admin rights to read, so a bare traceback in the job output is
    # the only diagnostic available.
    try:
        ledger.record(d._STATE)
        ledger.grade()
    except Exception:
        import traceback
        sys.stderr.write("ledger pass failed -- board still rebuilt:\n")
        traceback.print_exc()
    # Claimed held-out accuracy against what each league has ACTUALLY done.
    # The page used to state backtest figures alone, which had drifted badly:
    # it advertised MLB at 58.6% while MLB was running 49.0% live, and quoted
    # NBA/WNBA/NHL numbers for leagues with no picks at all. Computing the
    # comparison here means the boast cannot outlive the evidence.
    CLAIMED = {"mlb": 58.6, "nba": 73.1, "wnba": 70.4, "nhl": 58.0, "tennis": 65.9}
    seen = {}
    for e in ledger.load().values():
        if e.get("status") not in ("won", "lost"):
            continue
        k = "tennis" if e["league"] in ("atp", "wta") else e["league"]
        v = seen.setdefault(k, [0, 0])
        v[0] += 1 if e["status"] == "won" else 0
        v[1] += 1
    scoreboard = []
    for k in sorted(set(list(CLAIMED) + [x for x, v in seen.items() if v[1] >= 8])):
        w, n = seen.get(k, (0, 0))
        scoreboard.append({"lg": k, "claim": CLAIMED.get(k),
                           "n": n, "w": w,
                           "act": round(100.0 * w / n, 1) if n else None})

    out = {"at": d._STATE["at"].strftime("%b %-d, %-I:%M %p ET"),
           "scoreboard": scoreboard,
           "dates": {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]},
           # ESPN path per league, so the open page can refresh live scores
           # itself. GitHub throttles scheduled workflows hard -- the 20-minute
           # cron actually fires every 1.5 to 4 hours -- so a build-triggered
           # refresh alone leaves the Results tab looking frozen.
           "paths": {k: pth for k, pth, _ in d.LEAGUES},
           "slots": {}}
    # every soccer competition collapses into one tab -- a parlay is built
    # across leagues, not within one, so splitting them cost more than it gave
    SOCCER = {k for k, p, _ in d.LEAGUES if p.startswith("soccer/")}
    # what each band has actually done, so the badges answer to the record
    live = live_bands(ledger.load().values(), SOCCER)
    fit_platt(ledger.load().values())
    out["tuning"] = {lg: dict(a=a, b=b, n=n) for lg, (a, b, n) in PLATT.items()}
    # FanDuel (New York) ids, where FanDuel's feed has this game and market.
    try:
        FD = fanduel.load()
    except Exception:
        FD = {}
    for slot in ("today", "tomorrow"):
        lg = {}
        soccer_rows = []
        for k, _, lab in d.LEAGUES:
            rows = []
            for r in d._STATE["slots"][slot].get(k) or []:
                if not r.get("mypick") or r["mypick"].strip().upper() == "TBD":
                    continue          # an undetermined competitor is not a pick
                # join the price to my side; legs are keyed away/home, picks by name
                leg = next((L for L in r["legs"]
                            if L.get("side") and L["side"] == r.get("myside")), None)
                if r.get("dc"):
                    leg = None        # "or draw": the straight price is not this bet's
                mc = round(r["myconf"] * 100, 1) if r["myconf"] else None
                hit, hit_n = blended_hit(k, k in SOCCER, mc, live, r["why"],
                                         bool(leg and leg.get("dog")),
                                         (leg or {}).get("price"))
                if k in SOCCER and mc is not None:
                    hit, hit_n = None, 0              # no band study for soccer
                # ONE probability per pick: the chance published (and graded).
                # The band's past rate is shown beside it as history only --
                # until 2026-10-19 it drove the Card's fair price, edge, sweep
                # and order, so the Card priced a 72% pick at 81.7%.
                hist, p_pub = hit, (mc / 100 if mc is not None else None)
                hit = p_pub
                tk, tl, hide = tier_of(k, mc, hit, bool(leg and leg.get("dog")),
                                       (leg or {}).get("price"))
                pk, pl = price_note(k, k in SOCCER,
                                    (leg or {}).get("price"),
                                    bool(leg and leg.get("dog")))
                ek, el = ev_note(k in SOCCER, mc, (leg or {}).get("price"),
                                 bool(leg and leg.get("dog")))
                rows.append({"mp": r["mypick"] + (" or draw" if r.get("dc") else ""),
                             "t": r["tip"],
                             "mc": mc, "tk": tk, "tl": tl, "hd": hide,
                             # below the league's cutoff: a lean, not a call
                             "nc": not calls.is_call(k, mc),
                             "pk": pk, "pl": pl, "ek": ek, "el": el,
                             # fair price and edge come from the SAME rounded
                             # rate the row displays, so the three never
                             # disagree by a rounding step on screen
                             "hit": round(hit, 4) if hit is not None else None,
                             "id": r.get("id"),
                             # the band's past rate (history, not the pick's chance)
                             "hist": round(hist, 4) if hist is not None else None,
                             "hn": hit_n,
                             "fv": fair_price(round(hit, 4) if hit is not None else None),
                             "ev": edge_pct(round(hit, 4) if hit is not None else None,
                                            (leg or {}).get("price")),
                             "why": r["why"],
                             "p": leg["price"] if leg else None,
                             "d": bool(leg["dog"]) if leg else False,
                             "dk": (leg or {}).get("dk"),
                             "fd": fanduel.ml_ref(FD, k, (r.get("mkt") or {}).get("away"),
                                                  (r.get("mkt") or {}).get("home"),
                                                  r["mypick"]),
                             "lg": lab})
            # ranked by the published chance (the one probability)
            rows.sort(key=lambda x: (x["mc"] is None, -(x["hit"] or 0),
                                     -(x["mc"] or 0)))
            if k in SOCCER:
                soccer_rows.extend(rows)
            else:
                lg[k] = {"label": lab, "rows": rows}
        soccer_rows.sort(key=lambda x: (x["mc"] is None, -(x["hit"] or 0),
                                        -(x["mc"] or 0)))
        lg["soccer"] = {"label": "Soccer", "rows": soccer_rows}
        out["slots"][slot] = lg
    out["results"] = ledger.board_payload()
    # strong calls' record on picks the cut-offs never saw (tools/daily_review)
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "review", "call_min.json")) as fh_:
            out["strong"] = json.load(fh_).get("holdout")
    except (OSError, ValueError):
        out["strong"] = None
    # The review's own alarms, for the Results tab: a split trailing its
    # stated chance by 2+ standard errors, or records grading never settled.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "review", "log.json")) as fh_:
            _log = json.load(fh_)
        _day = max(_log)
        _r = _log[_day]
        out["health"] = dict(day=_day, trailing=[a_ for a_ in (_r.get("audit") or [])
                                                 if a_.get("flag") and _still_offered(a_.get("name"))],
                             stuck=([" ".join(map(str, x)) for x in (_r.get("stuck") or [])]
                                    + _unmatched_players())[:10],
                             checked=len(_r.get("audit") or []))
    except (OSError, ValueError, KeyError):
        out["health"] = None
    # inputs older than the build: a scoreboard served from the fallback
    # cache after ESPN refused this run (dashboard.SERVED_STALE)
    old_in = sorted(((u, a) for u, a in d.SERVED_STALE.items() if "scoreboard" in u and a > 1200),
                    key=lambda x: -x[1])
    if isinstance(out.get("health"), dict):
        out["health"]["stale_inputs"] = [
            [re.sub(r"^.*/sports/|/scoreboard.*$", "", u), round(a / 60)] for u, a in old_in[:8]]
    # the live chooser re-run on each set card's saved pool must give that card
    if isinstance(out.get("health"), dict):
        rb = []
        for nm, path_ in (("Locks", None), ("Safe Locks", locks.SAFE_LEDGER)):
            for day_ in sorted((locks.load(path_).get("pools") or {}))[-3:]:
                r_ = locks.replay(day_, path_)
                if r_ and not r_[0]:
                    rb.append(f"{nm} {day_}")
        try:
            import lottery as _lot
            for day_ in sorted((_lot.load().get("pools") or {}))[-3:]:
                if _lot.replay(day_) is False:
                    rb.append(f"Lottery {day_}")
        except Exception as ex_:
            rb.append(f"Lottery replay failed to run: {ex_}")
        out["health"]["replay_bad"] = rb
    # what each proposed change did against the current chooser (tools/paired.py)
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                               "paired_eval.json")) as fh_:
            _pe = json.load(fh_)
        out["paired"] = dict(run=_pe.get("run"), rule=_pe.get("rule"), studies=[
            dict(name=s_["name"], baseline=s_.get("baseline"), proposal=s_.get("proposal"),
                 same=s_.get("same"), promoted=s_.get("promoted"),
                 result={k: {x: v.get(x) for x in ("picks", "old_won", "new_won", "diff", "ci95_diff",
                                                     "new_won_old_missed", "old_won_new_missed",
                                                     "changed", "net", "promote")}
                         for k, v in list(s_["result"].items())[:10]})
            for s_ in _pe.get("studies") or []])
    except (OSError, ValueError, KeyError, TypeError):
        out["paired"] = None
    out["parlays"] = parlays.build_all(out)
    # Stacks: long tickets of high-probability legs (alt totals, "won't win
    # by N"), priced from each game's moneyline, spread and total. Kept apart
    # from the picks ledger; every leg is graded in stacks.json. Each section
    # has its own try: one feed or model failing must not take the others, or
    # the board, down with it.
    labels = {k: lab for k, _, lab in d.LEAGUES}
    try:
        out["stacks"] = stacks.build(d._STATE["slots"], SOCCER, labels)
        for st_ in out["stacks"].values():
            for tickets in st_["tickets"].values():
                for t in tickets:
                    for L in t["legs"]:
                        L["fd"] = fanduel.leg_ref(FD, L["league"], L["home"], L["away"], L["spec"])
                    t["fd_n"] = sum(1 for L in t["legs"] if L["fd"])
        # Kalshi: the exact market and side for each leg, to rebuild the
        # ticket as a Kalshi combo
        try:
            KB = kalshi.load()
            by_id = {r["id"]: r for sl in d._STATE["slots"].values()
                     for rows in sl.values() for r in rows}
            for st_ in out["stacks"].values():
                for tickets in st_["tickets"].values():
                    for t in tickets:
                        kalshi.attach(t, KB, by_id)
            # Kalshi-ready stacks: built only from lines Kalshi lists, so
            # every leg of every ticket can be placed in a Kalshi combo
            out["kalshi_stacks"] = stacks.build(d._STATE["slots"], SOCCER, labels,
                                                extra=kalshi.extra_specs(KB),
                                                keep=kalshi.keep_listed(KB))
            for st_ in out["kalshi_stacks"].values():
                for tickets in st_["tickets"].values():
                    for t in tickets:
                        kalshi.attach(t, KB, by_id)
            n = sum(len(v) for v in KB.values())
            kt = out["kalshi_stacks"]["today"]
            legs_ = [L for st_ in out["kalshi_stacks"].values() for ts in st_["tickets"].values()
                     for t in ts for L in t["legs"]]
            priced = sum(1 for L in legs_ if (L.get("kalshi") or {}).get("price"))
            print(f"kalshi: {priced} of {len(legs_)} ticket legs carry a Kalshi ask",
                  file=sys.stderr)
            print(f"kalshi: {n} games listed; Kalshi-ready stacks today from "
                  f"{kt['games']} games: " + ", ".join(f"{n_}-leg x{len(t)}"
                  for n_, t in kt["tickets"].items()), file=sys.stderr)
        except Exception:
            import traceback
            sys.stderr.write("kalshi lookup failed -- stacks kept without it:\n")
            traceback.print_exc()
        dates = {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]}
        stacks.record(out["stacks"], dates)
        stacks.grade(ledger._final)
        out["stacks_record"] = stacks.report()
        out["backtest"] = stacks.backtest_summary()
        st = out["stacks"]["today"]
        print(f'stacks: {st["games"]} games priced today, '
              + ", ".join(f'{n}-leg x{len(t)}' for n, t in st["tickets"].items()),
              file=sys.stderr)
    except Exception:
        import traceback
        sys.stderr.write("stacks failed -- board still rebuilt:\n")
        traceback.print_exc()
    try:
        out["markets"] = stacks.markets(d._STATE["slots"], SOCCER, labels)
    except Exception:
        import traceback
        sys.stderr.write("markets failed -- board still rebuilt:\n")
        traceback.print_exc()
    # Player props, where DraftKings posts priced ones.
    try:
        # settle yesterday's recorded props first, so today's prices use the
        # margin their own results support
        try:
            props_ledger.grade()
            props_ledger.tune()
        except Exception as e:
            print("props grading skipped:", e, file=sys.stderr)
        out["props"] = {}
        for slot in ("today", "tomorrow"):
            games = player_props.for_slot(d._STATE["slots"][slot], labels)
            try:
                import ufc_props
                games += ufc_props.for_slot(d._STATE["slots"][slot], labels)
            except Exception as ex:
                print(f"props: ufc failed: {ex}", file=sys.stderr)
            try:
                import participation
                participation.annotate(games)       # who is confirmed to play
            except Exception as ex:
                print(f"props: participation check failed (no prop recommended): {ex}",
                      file=sys.stderr)
            out["props"][slot] = dict(games=games,
                                      tickets=player_props.prop_tickets(games))
            mega = player_props.mega_ticket(games)
            if mega:
                out["props"][slot]["mega"] = mega
                # recorded with the stacks so every leg is graded
                out["props"][slot]["tickets"]["25"] = [mega]
        try:
            import td_scorers
            out["td"] = {s_: td_scorers.for_slot(d._STATE["slots"][s_]) for s_ in ("today", "tomorrow")}
            td_scorers.record(out["td"]["today"], d._STATE["dates"][0])
            td_scorers.log(out["td"]["today"], d._STATE["dates"][0])
            td_scorers.log(out["td"]["tomorrow"], d._STATE["dates"][1])
            td_scorers.grade()
            for s_ in out["td"]:
                for g_ in out["td"][s_]:
                    g_.pop("everyone", None)      # keep the page small
            print("td scorers: " + ", ".join(f"{s_} {len(v)} games" for s_, v in out["td"].items()),
                  file=sys.stderr)
        except Exception as ex:
            print(f"td scorers failed: {ex}", file=sys.stderr)
        try:
            import ladders
            n_ = ladders.log([d._STATE["slots"][s_] for s_ in ("today", "tomorrow")])
            print(f"ladders: {n_} football games logged", file=sys.stderr)
        except Exception as ex:
            print(f"ladders failed: {ex}", file=sys.stderr)
        n = props_ledger.record(out["props"].get("today"), d._STATE["dates"][0])
        out["props_tuning"] = props_ledger.TUNING
        print(f"props: recorded {n} new legs; tuning {props_ledger.TUNING}", file=sys.stderr)
        print("props: " + ", ".join(f'{s_} {len(v["games"])} games, '
                                    f'{sum(len(g["props"]) for g in v["games"])} props'
                                    for s_, v in out["props"].items()), file=sys.stderr)
    except Exception:
        import traceback
        sys.stderr.write("props failed -- board still rebuilt:\n")
        traceback.print_exc()
    # The day's locks: the 11 likeliest bets FanDuel lists (game lines and player
    # props), one per game. After the props, which they draw on.
    try:
        days_ = {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]}
        out["locks"] = {s_: locks.build(d._STATE["slots"].get(s_), SOCCER, labels, FD,
                                        day=days_[s_],
                                        prop_games=((out.get("props") or {}).get(s_) or {}).get("games"))
                        for s_ in ("today", "tomorrow")}
        locks.grade(ledger._final)
        if locks.card_time():
            # from 8:00 AM Eastern the day's card is set and shown as recorded
            locks.record(out["locks"]["today"], d._STATE["dates"][0])
            out["locks"]["today"] = locks.carry_extras(out["locks"]["today"],
                                                       locks.frozen(d._STATE["dates"][0]))
        else:
            out["locks"]["today"]["preview"] = True
        for v_ in out["locks"].values():
            v_.pop("pool", None)                # saved in the ledger, not published
        out["locks_record"] = locks.report()
        lk = out["locks"]["today"]
        print(f'locks: {len(lk["locks"])} of {lk["available"]} FanDuel games, '
              f'all-hit chance {100 * lk["prob"]:.1f}%', file=sys.stderr)
        for L_ in lk["locks"]:
            print(f'   lock {100 * L_["p"]:5.1f}%  {L_["label"]:<40} {str(L_.get("price") or ""):>7}  '
                  f'{L_.get("lg") or L_.get("league")}  {L_["match"]}', file=sys.stderr)
    except Exception:
        import traceback
        sys.stderr.write("locks failed -- board still rebuilt:\n")
        traceback.print_exc()
    # Safe Locks: the same card from heavy favourites (-2000 .. -500), beside
    # the regular one, whose rules stay as they are (locks.SAFE_LEDGER)
    try:
        days_ = {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]}
        out["safe_locks"] = {s_: locks.build(d._STATE["slots"].get(s_), SOCCER, labels, FD,
                                             day=days_[s_], dec=locks.SAFE_DEC, band=locks.SAFE_BAND,
                                             prop_games=((out.get("props") or {}).get(s_) or {}).get("games"))
                             for s_ in ("today", "tomorrow")}
        locks.grade(ledger._final, locks.SAFE_LEDGER)
        if locks.card_time():
            locks.record(out["safe_locks"]["today"], d._STATE["dates"][0], locks.SAFE_LEDGER, "safe")
            out["safe_locks"]["today"] = locks.carry_extras(
                out["safe_locks"]["today"], locks.frozen(d._STATE["dates"][0], locks.SAFE_LEDGER))
        else:
            out["safe_locks"]["today"]["preview"] = True
        for v_ in out["safe_locks"].values():
            v_.pop("pool", None)
        out["safe_locks_record"] = locks.report(locks.SAFE_LEDGER)
        sk = out["safe_locks"]["today"]
        print(f'safe locks: {len(sk["locks"])} of {sk["available"]} games, '
              f'all-hit chance {100 * sk["prob"]:.1f}%', file=sys.stderr)
        for L_ in sk["locks"]:
            print(f'   safe {100 * L_["p"]:5.1f}%  {L_["label"]:<40} {str(L_.get("price") or ""):>7}  '
                  f'{L_.get("lg") or L_.get("league")}  {L_["match"]}', file=sys.stderr)
    except Exception:
        import traceback
        sys.stderr.write("safe locks failed -- board still rebuilt:\n")
        traceback.print_exc()
    # The lottery: $1 tickets built to pay ~$10,000, from game lines and props
    try:
        try:
            _kb = kalshi.load()             # cached minutes ago by the stacks step
        except Exception:
            _kb = None
        days_ = {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]}
        out["lottery"] = {s_: lottery.build(d._STATE["slots"].get(s_), SOCCER, labels, FD,
                                            ((out.get("props") or {}).get(s_) or {}).get("games"),
                                            day=days_[s_], KB=_kb)
                          for s_ in ("today", "tomorrow")}
        lottery.grade(ledger._final)
        if locks.card_time():
            lottery.record(out["lottery"]["today"], days_["today"])
            fz = lottery.frozen(days_["today"])
            if fz:
                fz["edges"] = out["lottery"]["today"].get("edges")
                fz["pool"] = out["lottery"]["today"].get("pool")
                out["lottery"]["today"] = fz
        else:
            out["lottery"]["today"]["preview"] = True
        for v_ in out["lottery"].values():
            v_.pop("candidates", None)          # archived in lottery.json, not published
        out["lottery_record"] = lottery.report()
        pl_ = out["lottery"]["today"].get("pool") or {}
        print(f'lottery pool: {pl_}', file=sys.stderr)
        for e_ in out["lottery"]["today"].get("edges") or []:
            print(f'   edge {e_["edge"]:+5.1f}%  {e_["label"]:<40} {e_["price"]:>6}  model '
                  f'{e_["p_model"]:.2f} kalshi {e_["p_kalshi"]}  {e_["match"]}', file=sys.stderr)
        for t_ in out["lottery"]["today"]["tickets"]:
            print(f'lottery {t_["book"]} {t_.get("tier")}: {len(t_["legs"])} legs pays {t_["pays"]}x, '
                  f'1 in {t_["odds"]}', file=sys.stderr)
    except Exception:
        import traceback
        sys.stderr.write("lottery failed -- board still rebuilt:\n")
        traceback.print_exc()
    return out


# Conviction tiers, cut on each sport's OWN measured curve.
#
# A first pass used one 58% threshold everywhere. That was a category error:
# the MLB model is capped at 66% by construction, so its whole confidence
# scale is roughly half of tennis's, and a 54% baseball pick is not the same
# animal as a 54% tennis pick. It was hiding 11 of 19 MLB picks as "coin
# flips" when baseball has no coin-flip band at all.
#
# TENNIS -- walk-forward Elo, 3,224 matches, monthly blocks the cuts were
# never fitted to. There is a genuine dead zone and it is wide:
#
#     says 50-58%   803/1577 = 50.9%  (+-1.3)     <- no signal at all
#     says 58-64%   504/826  = 61.0%  (+-1.7)
#     says 64-72%   ~
#     says 72%+     ~                 up to 78.4%
#
# MLB -- point-in-time backtest, 1,155 games from June. No dead zone, and a
# much flatter gradient, because baseball is simply less predictable:
#
#     says 50-53%   165/298  = 55.4%  (+-2.9)     <- weak, but not a coin flip
#     says 53-56%   148/266  = 55.6%  (+-3.1)
#     says 56-59%   125/229  = 54.6%  (+-3.3)
#     says 59-62%    93/154  = 60.4%  (+-4.0)
#     says 62-67%   121/208  = 58.2%  (+-3.5)
#
# Keeping only MLB legs at 57%+ moves the hit rate 56.5% -> 58.0%, and 61%+
# gets 59.6%. Tennis moves 58.4% -> 65.9% -> 73.1% over the same exercise.
# Baseball's ceiling really is about 60%; no threshold repairs that.
#
# Every other league has no per-band validation yet, so it gets no tier claim
# and nothing is hidden -- an unmeasured league should not be dressed in
# numbers borrowed from a measured one.
# WHERE THE BOOK'S TAX SITS -- MEASURED PER SPORT, AT CLOSING PRICES
#
# Betting blind at the close and counting, across ~26,000 games:
#
#     sport    favourites   underdogs    gap        n
#     WNBA       -7.16%       +3.91%    +11.07     620
#     MLB        -5.24%       -1.19%     +4.05    1812
#     NHL        -5.50%       -1.49%     +4.01    2935
#     NFL        -5.65%       -7.10%     -1.45     627
#     NBA        -4.01%       -7.90%     -3.89    2705
#     soccer     -2.93%       -8.76%     -5.83    8193
#     NCAAF      -3.33%      -14.46%    -11.13    1666
#
# Baseball is the EXCEPTION, not the rule. The first version of this file
# generalised "take the underdog" from MLB alone; in college football that
# rule loses 14.5% a bet, and long dogs at +250 or worse lose 22.5%.
#
# The mechanism is consistent once the sports are lined up. Where a longshot
# is genuinely hopeless -- NCAAF dogs at +250 win 14.7%, soccer's win 20.2% --
# the public buys the lottery ticket anyway and the book prices the appetite.
# Where the "longshot" is not really long, because the sport is low-scoring and
# the odds stay compressed, dogs win often enough to be underpriced. Hockey
# and baseball live at that end; college football lives at the other.
#
# The best-powered results are the negative ones (soccer -5.83 at 3.4 standard
# errors, NCAAF -11.13 at 3.2), and those are the ones that protect money.
# The positive ones are weaker: WNBA +11.07 is 1.9 s.e., NHL +4.01 is 1.5.
# Each sport's confidence means something different -- tennis runs to 95%,
# the MLB model is capped at 66% -- so the raw number cannot rank a mixed
# slate. This maps a pick onto the hit rate its OWN sport's backtest measured
# for that band, which is comparable across sports and is what a slip actually
# multiplies together.
MEASURED = {
    # Cutting the top band finer (88 / 80 / 72) was tried and REVERTED. The
    # ledger does show a gradient across it -- 82.6% / 84.6% / 100% on n of
    # 23 / 13 / 7 -- but crossing that with the ranked-opponent split leaves
    # cells of three and four picks, all inheriting the same prior, so the
    # only thing separating them is noise. It duly inverted: a 95.3% call
    # came out BELOW a 78.7% call. A band has to be wide enough to carry a
    # number, and above 72% that means one band.
    # Re-measured for the tennis_v2 rating model (level seeds + experience ramp
    # + surface blend), walk-forward Apr-Sep, 5,166 predictions. The old table
    # came from the ranking-points model, whose bottom band carried no signal at
    # all (50-58% went 50.9%). The rating model finds real signal there -- 54.6%
    # on n=1857 -- which is why the bottom band now carries a number instead of
    # being a pure dead zone. It is still thin: 54.6% is barely past the 52.4%
    # breakeven at -110, so the dead-zone hide stays in place.
    "tennis": ((72.0, 0.757), (64.0, 0.697), (58.0, 0.608), (0.0, 0.546)),
    # MLB's table used to come from 27 graded picks. It now comes from all
    # 1,948 priced 2026 games replayed through the exact rule the board ships,
    # market anchor included. Finer cuts were tried and dropped for the same
    # reason as tennis: 56-59 came out at 60.0% and 59-62 at 55.8%, an
    # inversion well inside 2 s.e. One cut survives, and it survives on the
    # untouched quarter too (70.3% there against 68.4% overall).
    "mlb":    ((62.0, 0.684), (0.0, 0.547)),
    # Tomorrow's games have no price yet, so they never pass through the
    # anchor, and an unanchored 61% is a different animal from an anchored
    # one -- scoring it against the table above flattened every unpriced leg
    # to the same number. This is the same 1,948 games scored on the model's
    # OWN confidence. 57-60 (57.8%) and 54-57 (57.3%) are one band because
    # nothing separates them but noise.
    "mlb_raw": ((60.0, 0.609), (54.0, 0.575), (0.0, 0.513)),
    # Soccer graded nothing at all until the grader's league map was fixed,
    # and the 49 picks it had been silently discarding are the worst block on
    # the board: 46.9% against a claimed 58.7%. Its confidence is INVERTED --
    # the 50-55% band hits 55.6% while the 60-70% band hits 40.0% -- so there
    # is no band structure worth keeping. What does separate is which side of
    # the price we are on, and hard: favourites 9/11, underdogs 14/38, a
    # 45-point gap at 2.6 s.e. That corroborates the price map's blind result
    # over 8,193 games (favourites -2.93%, underdogs -8.76%), so it is two
    # independent lines of evidence rather than one thin one. Prior is the
    # pooled 49.1% outright rate; dog and favourite earn their way apart.
    "soccer": ((0.0, 0.491),),
}


def fair_price(p):
    """The American price at which a bet at probability `p` breaks even.

    This is the number a professional works from and the board never had: a
    pick is only worth backing if the book pays BETTER than its fair price,
    however high the win probability is. An 85% leg offered at -2000 is a bad
    bet; the same leg at -300 is a good one.
    """
    if p is None or not 0.0 < p < 1.0:
        return None
    return (f"-{round(100 * p / (1 - p))}" if p >= 0.5
            else f"+{round(100 * (1 - p) / p)}")


def edge_pct(p, american):
    """Expected return per unit staked, in percent, or None with no price."""
    if p is None or american is None:
        return None
    try:
        v = int(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    dec = 1 + (v / 100 if v > 0 else 100 / -v)
    return round((p * dec - 1) * 100, 1)

# The backtest is a prior, not a verdict. Every settled pick on this board is
# evidence about how a band ACTUALLY performs live, and where the two disagree
# the live record has to be allowed to win -- otherwise the board keeps
# advertising a number the results have already contradicted.
#
# PRIOR_N is how many backtest games one live game is worth arguing against.
# At 40 a single day barely moves a band and a full month moves it a long way,
# which is the behaviour we want: responsive, not twitchy.
PRIOR_N = 40.0


# Tennis confidence is built from the two rankings. When the opponent is
# unranked the model has no information about them and substitutes a default,
# so the number it prints is manufactured rather than measured -- and the
# ledger shows it: holding claimed confidence almost fixed at 72-84%, picks
# against a RANKED opponent went 16/17 (94.1%) while picks against an
# unranked one went 9/14 (64.3%). Across all 90 settled tennis picks the
# calibration error flips sign with it (+5.3 ranked, -3.4 unranked).
#
# n is too small to hard-code a penalty, so this splits the band instead and
# lets each half earn its own rate from the record. The separation widens
# only as fast as the evidence supports.
def opponent_unranked(why):
    """True when the model priced this pick against an unranked opponent."""
    if not why:
        return None
    m = re.search(r"rank\s+(\S+)\s+vs\s+(\S+)", why)
    return m.group(2) == "NR" if m else None


def _band_key(league, mc, why=None, is_soccer=False, dog=None, price=None):
    """-> (sport, cut, split) naming this pick's band, or None.

    The third slot is whatever actually separates that sport: for tennis
    whether the opponent is unranked, for soccer whether we are on the
    underdog. Both are measured, neither is assumed.

    MLB splits a step earlier, on the sport itself: a priced MLB pick has been
    pulled toward the close and an unpriced one has not, so the two carry
    different calibration and cannot share a table.
    """
    if mc is None:
        return None
    sport = ("tennis" if league in ("atp", "wta") else
             ("mlb" if price else "mlb_raw") if league == "mlb" else
             "soccer" if is_soccer else None)
    if sport is None:
        return None
    split = (opponent_unranked(why) if sport == "tennis" else
             bool(dog) if sport == "soccer" else None)
    for cut, _ in MEASURED[sport]:
        if mc >= cut:
            return sport, cut, split
    return None


# A band rate is an AVERAGE over every price in the band, so using it as a
# point probability over-values long prices and under-values short ones --
# the favourite-longshot bias reappearing inside our own bands. It showed up
# on the board immediately: soccer's underdog band credits every dog 43.1%,
# while the ledger has them at 52.9% from +100 to +150, 23.1% from +150 to
# +250 and 25.0% beyond that. A +450 dog was being handed 43.1% and a +40%
# "edge", pointing the card straight at the worst bets it carries.
#
# So where a leg has a price, the band contributes an OFFSET in log-odds from
# the de-vigged market rather than a flat rate. Each leg keeps its own price
# and still carries whatever the band has measured. Scored on the ledger
# (Brier, lower better): soccer underdogs 0.2327 flat -> 0.2172 anchored,
# soccer favourites 0.1875 -> 0.1728, MLB favourites 0.2496 -> 0.2439, all
# of them also beating the raw market.
SOCCER_HOLD, TWO_WAY_HOLD = 1.07, 1.04     # three-way markets are taxed harder


def _devig(american, is_soccer):
    """De-vigged win probability implied by one side's price, or None."""
    p = implied(american)
    if p is None:
        return None
    return min(max(p / (SOCCER_HOLD if is_soccer else TWO_WAY_HOLD), 0.01), 0.99)


def _logit(p):
    return math.log(p / (1 - p))


def live_bands(entries, soccer_keys=()):
    """-> {band key: (n, won, priced_n, sum_logit_market)} from the ledger.

    The last two accumulate the market's own view of the picks in each band,
    so the band can be expressed as an offset from a price instead of a rate.
    """
    out = {}
    soccer_keys = set(soccer_keys)
    for e in entries:
        if e.get("status") not in ("won", "lost"):
            continue
        lg = e.get("league")
        is_soc = lg in soccer_keys
        key = _band_key(lg, e.get("conf"), e.get("why"), is_soc, e.get("dog"),
                        e.get("price"))
        if key is None:
            continue
        n, w, pn, s = out.get(key, (0, 0, 0, 0.0))
        m = _devig(e.get("price"), is_soc)
        if m is not None:
            pn, s = pn + 1, s + _logit(m)
        out[key] = (n + 1, w + (e["status"] == "won"), pn, s)
    return out


# ------------------------------------------------------------ self-tuning
# Leagues with no backtested band (football, UFC) used to show the model's raw
# confidence forever. The ledger says that was wrong for college football by a
# mile: picks it called 60-70% won 85.5% (165 graded). So each rebuild re-fits
# a Platt correction -- logit(rate) = a + b * logit(confidence) -- on that
# league's graded picks, shrunk toward "no change" (a=0, b=1) by PLATT_LAMBDA
# pseudo-observations so a thin league barely moves. Validated before it
# shipped: fitted on the first half of NCAAF's 444 picks, it cut log loss on
# the unseen half from 0.613 to 0.592 and its stated rate came within 2.1
# points of the actual (raw: 9.3 points off). NFL and UFC, already close,
# stay where they are.
PLATT_LEAGUES = ("ncaaf", "nfl", "ufc")
PLATT_LAMBDA = 50.0
PLATT_MIN_N = 30
PLATT = {}            # league -> (a, b, n), filled by fit_platt()


def _fit_platt(data, lam=PLATT_LAMBDA):
    a, b = 0.0, 1.0
    for _ in range(50):
        ga, gb = lam * a, lam * (b - 1)
        haa, hab, hbb = lam, 0.0, lam
        for x, y in data:
            p = 1 / (1 + math.exp(-(a + b * x)))
            r, w = p - y, p * (1 - p)
            ga += r
            gb += r * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        a -= (hbb * ga - hab * gb) / det
        b -= (haa * gb - hab * ga) / det
    return a, b


def fit_platt(entries):
    PLATT.clear()
    by = {}
    for e in entries:
        if e.get("league") in PLATT_LEAGUES and e.get("status") in ("won", "lost") and e.get("conf"):
            c = min(max(e["conf"] / 100.0, 0.01), 0.99)
            by.setdefault(e["league"], []).append((_logit(c), e["status"] == "won"))
    for lg, data in by.items():
        if len(data) >= PLATT_MIN_N:
            a, b = _fit_platt(data)
            PLATT[lg] = (round(a, 3), round(b, 3), len(data))


def recalibrated(league, mc):
    """(rate, graded n) for a league without a measured band."""
    a, b, n = PLATT.get(league, (0.0, 1.0, 0))
    c = min(max(mc / 100.0, 0.01), 0.99)
    return min(max(1 / (1 + math.exp(-(a + b * _logit(c)))), 0.01), 0.99), n


def blended_hit(league, is_soccer, mc, live, why=None, dog=None, price=None):
    """Backtest rate for this band, corrected by what it has actually done.

    Returns (rate, live_n) so the board can show the evidence behind the
    number rather than asking to be taken on faith.
    """
    key = _band_key(league, mc, why, is_soccer, dog, price)
    if key is None:
        # Football has no live band yet (its season is a week old). Rather
        # than show nothing -- which left a -100000 leg with no fair price and
        # no edge, silent on the worst bets the board carries -- use the
        # model's own confidence as the rate. The prior-season carry-over
        # backtest puts NCAAF's Brier at 0.2004, about what a well-calibrated
        # ~73% model scores, so the number is honest to a first approximation.
        # Live sample shows as zero, and the band takes over once it exists.
        if league in ("ncaaf", "nfl") and mc is not None:
            return recalibrated(league, mc)
        # UFC's number IS the de-vigged market price, so it is already the best
        # available estimate of the win probability -- but it is the market's
        # estimate, not ours, and it has no graded history here yet.
        if league == "ufc" and mc is not None:
            return recalibrated(league, mc)
        return None, 0
    sport, cut, _nr = key
    prior = dict(MEASURED[sport])[cut]
    n, w, pn, s = live.get(key, (0, 0, 0, 0.0))
    rate = (PRIOR_N * prior + w) / (PRIOR_N + n)
    m = _devig(price, is_soccer)
    if m is None or pn < MIN_PRICED:
        return rate, n
    # What this band has done, relative to what the market said about it --
    # then shrunk toward the market by its own sample size. Forty results
    # cannot support a full-strength claim of beating a price, and an
    # unshrunk offset is a constant in log-odds, so it asserts a LARGER
    # percentage edge the longer the price. Shrinking keeps the direction the
    # band measured without letting a thin sample manufacture a +27% bet on a
    # +450 shot.
    offset = _logit(min(max(rate, 0.01), 0.99)) - s / pn
    offset *= pn / (pn + OFFSET_K)
    return 1 / (1 + math.exp(-(_logit(m) + offset))), n


# below this many priced results the offset is noise, so the flat band stands
MIN_PRICED = 8
# priced results at which the band's offset carries half its measured weight
OFFSET_K = 40


# A badge has to mean the same thing in every sport or it is false
# advertising. These cuts are on the MEASURED hit rate, not on a model
# confidence, so "solid" is one promise across the whole board: tennis at 72%
# confidence and MLB at 62% confidence get the same word only if they have
# earned the same result.
LABEL_CUTS = ((0.75, "strong", "strong"), (0.65, "solid", "solid"),
              (0.57, "lean", "lean"), (0.53, "thin", "thin"))


DOG_FRIENDLY = {"mlb", "nhl", "wnba"}       # underdogs carry the lighter tax
DOG_TAXED = {"ncaaf", "nba", "nfl"}         # and the heavier one here
SOCCER_LONG_DOG = 250                       # +250 and worse: -11.4% over 9,206


# College football breaks this model's confidence scale. The widest rating gap
# in the pool is 348 Elo, which maps to at most 88.1%, while the market prices
# CFB games at 97-99.9%. Measured on the Sept 5 slate: across 32 market
# favourites at 85%+ implied, the model sat a mean 35.3 points BELOW the book,
# and 25.0 points below across all 49 priced games.
#
# Direction survives that -- it agrees with the market favourite on 45 of 49 --
# but a model that cannot express a mismatch has no standing to back a heavy
# underdog. Where it fights a book price under 35% implied, the market side is
# taken instead. On the Sept 5 slate that caught Tulsa at +425 and The Citadel
# at +950.
CFB_DOG_FLOOR = 0.35


def cfb_dog_override(league, is_soccer, price, dog):
    """True when a football pick backs a dog the market has all but written off."""
    if league not in ("ncaaf", "nfl") or not dog or price is None:
        return False
    m = _devig(price, is_soccer)
    return m is not None and m < CFB_DOG_FLOOR


def ev_note(is_soccer, mc, price, dog):
    """-> (key, label) for whether this pick beats the price it is offered at.

    Hit rate and profit are different things, and the ledger separates them
    cleanly. Across 140 priced graded picks:

        model ABOVE the de-vigged price   86 picks  41-45 (47.7%)  ROI +10.4%
        model BELOW it                    54 picks  35-19 (64.8%)  ROI  +3.9%

    The lower hit rate makes more money, because it is getting paid better. And
    the best cell on the board is +EV with the underdog rule applied: 19 picks,
    13-6 (68.4%), ROI +24.1%. So a badge for "likely to win" is not a badge for
    "worth betting" -- 97 of the 105 LOCK-grade picks carry no price at all and
    cannot be bet at that number by anyone.

    "no value" is the Rutgers case from Sept 3: a -8000 line the model rated
    64.7%. That risks 80 units to win 1 on a pick its own model gives a 35%
    chance of losing. It lost. One pick is not a pattern, but the arithmetic
    does not need a sample to be wrong.
    """
    if price is None or mc is None:
        return None, None
    m = _devig(price, is_soccer)
    if m is None:
        return None, None
    edge = mc / 100.0 - m
    if edge >= 0.02 and not dog:
        return "value", "+EV"
    if edge <= -0.15:
        return "noval", "no value"
    return None, None


def price_note(league, is_soccer, price, dog):
    """-> (key, label) marking where this leg sits against the book's tax."""
    if not dog or price is None:
        return None, None
    try:
        v = int(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None, None
    if is_soccer:
        return ("taxed", "taxed") if v >= SOCCER_LONG_DOG else (None, None)
    if league in DOG_FRIENDLY:
        return "value", "value"
    if league in DOG_TAXED:
        return "taxed", "taxed"
    return None, None


# Retired. This hid every tennis pick under 58% because the ranking-points
# model measured 50.9% there -- no signal at all. The rating model that
# replaced it goes 54.6% on 1,857 walk-forward predictions in the same band,
# so those picks now show with an honest label instead of being suppressed.
TENNIS_DEAD_ZONE = 58.0


# LOCK -- the one cut the ledger supports as a genuine tier, measured on 287
# graded picks with the TBD recording bug removed:
#
#     everything graded            188-99  (65.5%)
#     the board's old >=58 cut     130-50  (72.2%)
#     conf >=65, favourites only    87-15  (85.3%)   <- LOCK
#     conf >=70, favourites only    70-12  (85.4%)
#     ANY plus-money underdog       27-39  (40.9%)   <- the leak
#
# Excluding underdogs is most of it. Taking the dog was called at 56.7% and
# came in at 40.9%, a 15.8-point hole, while favourites called at 57.8% came
# in at 66.7%. That split is large, on 66 and 69 picks respectively, and it is
# the same failure the soccer slips showed: plus-money legs sold as floor.
#
# Honesty about the cut: it was chosen after looking at these results, so the
# 85.3% is in-sample and the true forward rate is lower. The dog/favourite
# split is the part that is robust; the exact 65 threshold is not.
LOCK_CONF = 65.0
TENNIS_LOCK = 72.0          # tennis at 72%+ : 68-10 (87.2%) on 78 graded picks
# A soccer favourite priced near even money is a coin flip wearing a favourite's
# label, and calling it a lock was the weak link. Split by de-vigged price:
#
#     implied >= 60%   19-0  (100.0%)  ROI +46.0%
#     implied <  60%   12-4  ( 75.0%)  ROI +39.9%
#
# Sept 4 lost Viking FK at -130, i.e. 56.5% implied, straight out of the weak
# band. Both bands are profitable -- the discarded one still returns +39.9% --
# so this is a tightening of what may wear the LOCK badge, not a claim that the
# dropped picks are bad. And 19-0 is a perfect record on nineteen picks: it will
# regress, and the badge should be read as "the strongest cell measured so far",
# not as a promise of 100%.
SOCCER_LOCK_IMPLIED = 0.60   # retired with soccer
NCAAF_LOCK = 60.0            # NCAAF at 60%+ : 27-3 (90.0%) on 30 graded picks
UFC_LOCK = 65.0              # UFC at 65%+   : 7-2  (77.8%) on 9 graded picks -- thin
MLB_FLOOR = 58.0            # below this MLB is 14-18 (43.8%), worse than a coin flip
_TENNIS = ("atp", "wta")
# ufc belongs here, not in the soccer bucket. _is_soccer() is a negative test,
# so without this a UFC favourite at 60%+ implied would inherit the soccer LOCK
# rule -- a badge earned by 35 graded soccer picks, awarded to a sport with a
# market-derived number, no model and no track record whatsoever.
_MAJOR = ("mlb", "ncaaf", "nfl", "nba", "nhl", "wnba", "ufc", "ncaab", "pga")


def _is_soccer(league):
    return league not in _TENNIS and league not in _MAJOR


def tier_of(league, mc, hit, dog=False, priced=None):
    """-> (key, label, hide) for a pick, from its measured hit rate.

    Nothing is hidden any more. The tennis dead zone was hidden because the
    ranking-points model had no signal below 58% (measured 50.9%), but the
    rating model that replaced it goes 54.6% there on 1,857 walk-forward
    predictions. That is thin rather than absent, and a thin pick wearing an
    honest label beats a pick you cannot see.
    """
    if mc is None:
        return None, None, False
    # LOCK, re-cut on 307 graded picks. The old rule (any sport at 65%+, no
    # dog) went 91-16 (85.0%). Splitting it by where the record actually lives
    # does better on the same volume:
    #
    #     tennis >= 72%                68-10  (87.2%)
    #     soccer favs, implied >= 60%  19-0  (100.0%)
    #     the two together             87-10  (89.7%)   <- this rule
    #     with ANY soccer favourite    99-14  (87.6%)   <- the looser previous cut
    #     adding MLB >= 58%           122-24  (83.6%)   <- so MLB stays out
    #
    # Tennis is cleanly monotonic (53.6 / 63.6 / 80.8 / 87.5 across the bands),
    # and the soccer split is the dog rule again: favourites 90.3%, dogs 41.9%.
    # Chosen after seeing these numbers, so it is in-sample and the forward rate
    # will be lower -- but each leg is individually large and mechanistic.
    # LOCK, rebuilt for an American-sports-only board. The old rule was tennis
    # at 72%+ plus soccer favourites; both sports are gone, so it is re-cut on
    # what remains, measured across 141 graded American picks:
    #
    #     NCAAF >= 60%        27-3   (90.0%)   <- this rule
    #     NCAAF overall       46-9   (83.6%)
    #     UFC   >= 65%         7-2   (77.8%)   n=9, too thin to badge
    #     MLB   >= 65%         3-2   (60.0%)   nothing here clears
    #     any American >= 70% 9-1   (90.0%)    n=10
    #
    # NCAAF carries this board now. MLB stays out entirely -- at 38-34 (52.8%)
    # it is a coin flip, and no threshold inside it reaches lock grade.
    if not dog:
        if league == "ncaaf" and mc >= NCAAF_LOCK:
            return "lock", "lock", False
        # Second leg, and it is thinner than the first: 7-2 on nine graded
        # picks. It is here because it is the only other American cell above
        # 75%, not because nine results prove anything. UFC's number is the
        # de-vigged market price rather than a model of ours, so this badge
        # says "the market is confident and has been right so far", which is
        # a weaker claim than the NCAAF leg makes.
        if league == "ufc" and mc >= UFC_LOCK:
            return "lock", "lock", False
    if hit is None:
        return (None, None, False)
    # MLB under 58% has no signal: 14-18 (43.8%) across 32 graded picks, against
    # 10-7 (58.8%) above it. Same shape as the tennis dead zone the rating model
    # retired, but this one is still measured and still dead.
    if league == "mlb" and mc < MLB_FLOOR:
        return "nosig", "no signal", False
    for cut, key, label in LABEL_CUTS:
        if hit >= cut:
            return key, label, False
    return "coin", "coin flip", False


def implied(american):
    """American odds as an implied probability, vig included."""
    try:
        v = int(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def changes(new):
    """What moved since the last rebuild."""
    try:
        with open(STATE) as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return ["first run — no prior board to compare"]
    def flat(b):
        """Key rows by slot/league/pick. Tolerates an older snapshot schema:
        a stored board written before a field rename should produce 'first run'
        rather than a KeyError."""
        out = {}
        for s in b.get("slots", {}):
            for k in b["slots"][s]:
                for r in b["slots"][s][k].get("rows", []):
                    name = r.get("mp")
                    if name:
                        out[f"{s}:{k}:{name}"] = r
        return out
    o, n = flat(old), flat(new)
    if not o:
        return ["previous board used an older format — no comparison possible"]
    out = []
    for key, r in n.items():
        prev = o.get(key)
        game = key.split(":", 2)[2]
        if prev is None:
            out.append(f"{game}: new on the board")
            continue
        if prev.get("p") and r.get("p") and prev["p"] != r["p"]:
            a, b = implied(prev["p"]), implied(r["p"])
            if a is not None and b is not None:
                # American odds are not subtractable across the +/- boundary:
                # +101 to -104 is five cents of probability, not 205. Report
                # the move where it is actually comparable.
                note = ""
                if prev["p"].startswith("+") and r["p"].startswith("-"):
                    note = "  — now a favourite"
                elif prev["p"].startswith("-") and r["p"].startswith("+"):
                    note = "  — now an underdog"
                out.append(f'{game}: {prev["p"]} → {r["p"]} '
                           f'({100*(b-a):+.1f} pts implied){note}')
        if not prev.get("p") and r.get("p"):
            out.append(f'{game}: price posted at {r["p"]}')
        if "TBD" in (prev.get("why") or "") and r.get("why") and "TBD" not in r["why"]:
            out.append(f'{game}: starter named — {r["why"]}')
        if prev.get("mc") and r.get("mc") and abs(prev["mc"] - r["mc"]) >= 3.0:
            out.append(f'{game}: confidence {prev["mc"]:.1f}% → {r["mc"]:.1f}%')
    return out


def _unmatched_players(days=14):
    """Props set aside because the player's name could not be matched to the
    box score uniquely: listed for review rather than silently dropped."""
    try:
        import datetime as dt
        import props_ledger
        cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        return [f'unmatched player: {e.get("name")} ({e.get("gid")}, {e.get("market")})'
                for e in props_ledger.load().values()
                if e.get("void_why") == "identity_unresolved" and (e.get("date") or "") >= cut]
    except Exception:
        return []


def _still_offered(name):
    """False for an audit line on a prop market already taken off the
    board: the review log is written once a day, so without this a market
    switched off at 4 AM kept its alarm on the Results tab until the next
    morning (seen 2026-10-18, "props uel Shots")."""
    w = (name or "").split(" ", 2)
    if len(w) == 3 and w[0] == "props":
        import props_ledger
        return props_ledger.offered(w[1], w[2])
    return True


def write(new):
    """Swap the embedded data block in board.html for `new`."""
    # every build checks its own data before publishing (integrity.py);
    # problems go to the Results tab's Checks box and the build log
    try:
        import integrity
        bad = integrity.check(new)
    except Exception as ex:                     # the check must never block a build
        bad = [("D", "integrity check failed to run", str(ex))]
    if isinstance(new.get("health"), dict):
        new["health"]["integrity"] = bad
    elif bad:
        new["health"] = dict(day="", trailing=[], stuck=[], checked=0, integrity=bad)
    for b in bad[:5]:
        print(f"integrity: {b[1]} at {b[0]}: {b[2]}", file=sys.stderr)
    src = open(BOARD).read()
    blob = json.dumps(new, separators=(",", ":"))
    src2 = re.sub(r"const D = \{.*?\};\n", "const D = " + blob.replace("\\", "\\\\") + ";\n",
                  src, count=1, flags=re.S)
    if src2 == src:
        sys.exit("could not find the embedded data block in board.html")
    open(BOARD, "w").write(src2)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        json.dump(new, fh)


def scores_only():
    """Re-grade and refresh live scores without re-researching the slate.

    Scores move every few minutes; ratings and starters do not. This is the
    cheap path for keeping the Results tab current between full rebuilds.
    """
    ledger.grade()
    try:
        with open(STATE) as fh:
            new = json.load(fh)
    except (OSError, ValueError):
        sys.exit("no prior board — run a full rebuild first")
    new["results"] = ledger.board_payload()
    write(new)
    R = new["results"]
    print(f'scores refreshed — {len(R["live"])} live, {R["won"]}-{R["lost"]} graded')


def main():
    if "--scores" in sys.argv:
        return scores_only()
    new = snapshot()

    # An empty board is a failed fetch, not a quiet slate.
    #
    # On 2026-09-04T02:19Z the runner published a board with zero rows in every
    # league for BOTH days and reported success, while the identical commit
    # built 56 rows on a laptop three minutes earlier. ESPN returns nothing to
    # the runner -- rate limit, datacenter-IP block, something -- and because
    # dashboard.get() swallows failures and returns {}, that arrived as "no
    # games today" rather than as an error. The site then served an empty board
    # for hours. This is the same cause as the intermittent hard failures: when
    # the fetch dies mid-parse it raises, and when it dies cleanly it just
    # returns nothing.
    #
    # Publishing nothing is strictly worse than publishing yesterday's board,
    # so bail before write() and let the deploy job skip. The last good board
    # keeps serving and the job output says why.
    rows = sum(len(v.get("rows") or [])
               for slot in new["slots"].values() for v in slot.values())
    if rows == 0:
        sys.exit("refusing to publish an empty board: every league returned zero "
                 "rows for both days, which means the feeds failed rather than "
                 "that nothing is scheduled. Previous board left in place.")

    moved = changes(new)
    write(new)
    up = {s: sum(len(v["rows"]) for v in new["slots"][s].values()) for s in new["slots"]}
    print(f'rebuilt board.html — today {up["today"]} upcoming, tomorrow {up["tomorrow"]}')
    print(f'captured {new["at"]}')
    R = new["results"]
    if R["graded"]:
        print(f'ledger {R["won"]}-{R["lost"]} ({R["hit"]}%) · '
              f'{len(R["live"])} live · {R["open"]} open')
    else:
        print(f'ledger {R["open"]} open, none graded yet')
    if moved:
        print(f"\n{len(moved)} change(s):")
        for m in moved[:25]:
            print("  " + m)
    else:
        print("\nno changes since last cycle")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Name the failure. Without this the Actions log shows only a non-zero
        # exit and the run is unreadable without admin rights on the repo.
        import traceback
        sys.stderr.write("\n=== rebuild failed ===\n")
        traceback.print_exc()
        raise
