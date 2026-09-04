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
    out = {"at": d._STATE["at"].strftime("%b %-d, %-I:%M %p ET"),
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
                mc = round(r["myconf"] * 100, 1) if r["myconf"] else None
                hit, hit_n = blended_hit(k, k in SOCCER, mc, live, r["why"],
                                         bool(leg and leg.get("dog")),
                                         (leg or {}).get("price"))
                tk, tl, hide = tier_of(k, mc, hit, bool(leg and leg.get("dog")),
                                       bool(leg and leg.get("price")))
                pk, pl = price_note(k, k in SOCCER,
                                    (leg or {}).get("price"),
                                    bool(leg and leg.get("dog")))
                ek, el = ev_note(k in SOCCER, mc, (leg or {}).get("price"),
                                 bool(leg and leg.get("dog")))
                rows.append({"mp": r["mypick"], "t": r["tip"],
                             "mc": mc, "tk": tk, "tl": tl, "hd": hide,
                             "pk": pk, "pl": pl, "ek": ek, "el": el,
                             # fair price and edge come from the SAME rounded
                             # rate the row displays, so the three never
                             # disagree by a rounding step on screen
                             "hit": round(hit, 4) if hit is not None else None,
                             "hn": hit_n,
                             "fv": fair_price(round(hit, 4) if hit is not None else None),
                             "ev": edge_pct(round(hit, 4) if hit is not None else None,
                                            (leg or {}).get("price")),
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
            return mc / 100.0, 0
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
TENNIS_LOCK = 72.0          # tennis at 72%+ : 63-9 (87.5%) on 72 graded picks
MLB_FLOOR = 58.0            # below this MLB is 14-18 (43.8%), worse than a coin flip
_TENNIS = ("atp", "wta")
_MAJOR = ("mlb", "ncaaf", "nfl", "nba", "nhl", "wnba")


def _is_soccer(league):
    return league not in _TENNIS and league not in _MAJOR


def tier_of(league, mc, hit, dog=False, priced=False):
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
    #     tennis >= 72%                63-9   (87.5%)
    #     soccer favourites            28-3   (90.3%)
    #     the two together             91-12  (88.3%)   <- this rule
    #     adding MLB >= 58%           122-24  (83.6%)   <- so MLB stays out
    #
    # Tennis is cleanly monotonic (53.6 / 63.6 / 80.8 / 87.5 across the bands),
    # and the soccer split is the dog rule again: favourites 90.3%, dogs 41.9%.
    # Chosen after seeing these numbers, so it is in-sample and the forward rate
    # will be lower -- but each leg is individually large and mechanistic.
    if not dog:
        if league in _TENNIS and mc >= TENNIS_LOCK:
            return "lock", "lock", False
        if _is_soccer(league) and priced:
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
