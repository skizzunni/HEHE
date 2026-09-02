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
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BOARD = os.path.join(HERE, "board.html")
STATE = os.path.join(HERE, ".cache", "last_board.json")

import dashboard as d          # noqa: E402
import ledger                  # noqa: E402


def snapshot():
    """Fresh research for both days, one row per game, best picks first.

    The same pass also feeds the ledger: every pick on the board is recorded,
    anything that has finished is graded, and the running record goes onto the
    page. Research happens once and both consumers read the same state.
    """
    d.refresh()
    ledger.record(d._STATE)
    ledger.grade()
    out = {"at": d._STATE["at"].strftime("%b %-d, %-I:%M %p ET"),
           "dates": {"today": d._STATE["dates"][0], "tomorrow": d._STATE["dates"][1]},
           "slots": {}}
    # every soccer competition collapses into one tab -- a parlay is built
    # across leagues, not within one, so splitting them cost more than it gave
    SOCCER = {k for k, p, _ in d.LEAGUES if p.startswith("soccer/")}
    # what each band has actually done, so the badges answer to the record
    live = live_bands(ledger.load().values(), SOCCER)
    for slot in ("today", "tomorrow"):
        lg = {}
        soccer_rows = []
        for k, _, lab in d.LEAGUES:
            rows = []
            for r in d._STATE["slots"][slot].get(k) or []:
                if not r.get("mypick"):
                    continue
                # join the price to my side; legs are keyed away/home, picks by name
                leg = next((L for L in r["legs"]
                            if L.get("side") and L["side"] == r.get("myside")), None)
                mc = round(r["myconf"] * 100, 1) if r["myconf"] else None
                hit, hit_n = blended_hit(k, k in SOCCER, mc, live, r["why"],
                                         bool(leg and leg.get("dog")))
                tk, tl, hide = tier_of(k, mc, hit)
                pk, pl = price_note(k, k in SOCCER,
                                    (leg or {}).get("price"),
                                    bool(leg and leg.get("dog")))
                rows.append({"mp": r["mypick"], "t": r["tip"],
                             "mc": mc, "tk": tk, "tl": tl, "hd": hide,
                             "pk": pk, "pl": pl,
                             "hit": round(hit, 4) if hit is not None else None,
                             "hn": hit_n,
                             "fv": fair_price(hit),
                             "ev": edge_pct(hit, (leg or {}).get("price")),
                             "why": r["why"],
                             "p": leg["price"] if leg else None,
                             "d": bool(leg["dog"]) if leg else False,
                             "dk": (leg or {}).get("dk"),
                             "lg": lab})
            # rank by what the band has actually hit, not by a raw confidence
            # that means something different in every sport
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
    "tennis": ((72.0, 0.784), (64.0, 0.706), (58.0, 0.610), (0.0, 0.509)),
    "mlb":    ((61.0, 0.596), (57.0, 0.580), (0.0, 0.550)),
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


def _band_key(league, mc, why=None, is_soccer=False, dog=None):
    """-> (sport, cut, split) naming this pick's band, or None.

    The third slot is whatever actually separates that sport: for tennis
    whether the opponent is unranked, for soccer whether we are on the
    underdog. Both are measured, neither is assumed.
    """
    if mc is None:
        return None
    sport = ("tennis" if league in ("atp", "wta") else
             "mlb" if league == "mlb" else
             "soccer" if is_soccer else None)
    if sport is None:
        return None
    split = (opponent_unranked(why) if sport == "tennis" else
             bool(dog) if sport == "soccer" else None)
    for cut, _ in MEASURED[sport]:
        if mc >= cut:
            return sport, cut, split
    return None


def live_bands(entries, soccer_keys=()):
    """-> {band key: (n, won)} from every settled pick on the ledger."""
    out = {}
    soccer_keys = set(soccer_keys)
    for e in entries:
        if e.get("status") not in ("won", "lost"):
            continue
        lg = e.get("league")
        key = _band_key(lg, e.get("conf"), e.get("why"),
                        lg in soccer_keys, e.get("dog"))
        if key is None:
            continue
        n, w = out.get(key, (0, 0))
        out[key] = (n + 1, w + (e["status"] == "won"))
    return out


def blended_hit(league, is_soccer, mc, live, why=None, dog=None):
    """Backtest rate for this band, corrected by what it has actually done.

    Returns (rate, live_n) so the board can show the evidence behind the
    number rather than asking to be taken on faith.
    """
    key = _band_key(league, mc, why, is_soccer, dog)
    if key is None:
        # Football has no live band yet (its season is a week old). Rather
        # than show nothing -- which left a -100000 leg with no fair price and
        # no edge, silent on the worst bets the board carries -- use the
        # model's own confidence as the rate. The prior-season carry-over
        # backtest puts NCAAF's Brier at 0.2004, about what a well-calibrated
        # ~73% model scores, so the number is honest to a first approximation.
        # Live sample shows as zero, and the band takes over once it exists.
        if league in ("ncaaf", "nfl") and mc is not None:
            return mc / 100.0, 0
        return None, 0
    sport, cut, _nr = key
    prior = dict(MEASURED[sport])[cut]
    n, w = live.get(key, (0, 0))
    return (PRIOR_N * prior + w) / (PRIOR_N + n), n


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


TENNIS_DEAD_ZONE = 58.0     # replicated across every month and every K


def tier_of(league, mc, hit):
    """-> (key, label, hide) for a pick, from its measured hit rate.

    `hide` is reserved for the tennis dead zone -- the one band with a
    replicated no-signal finding. Everything else stays on the board wearing
    an honest label, because a weak pick you can see beats a hidden one.
    """
    if mc is None:
        return None, None, False
    dead = league in ("atp", "wta") and mc < TENNIS_DEAD_ZONE
    if hit is None:
        return (None, None, dead)
    for cut, key, label in LABEL_CUTS:
        if hit >= cut:
            return key, label, dead
    return "coin", "coin flip", dead


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


def write(new):
    """Swap the embedded data block in board.html for `new`."""
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
    main()
