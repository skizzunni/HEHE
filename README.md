# Picks system — post-mortem and rebuild

## What actually went wrong

Not the picks. The bet structure.

**Table tennis / MMA, 12 legs, +21074 — LOST.** Nine of twelve legs hit. A 75%
per-leg hit rate is genuinely good. It still lost, because a 12-leg parlay pays
nothing for 11/12. At a sustained 75% accuracy, the chance of running all twelve
is 3.2%.

**Golf R3 2-balls, 14 legs, +152121 — LOST.** Dead after four legs; nine legs
never got graded. Round-3 two-balls are near coinflips priced around -145, and
they are *correlated* — R3 pairings are set by leaderboard position, so a whole
card of "underdog beats favorite" is one repeated bet on the same idea.

**MLB, 10-leg (+20316) and 12-leg (+62536) — both still live, both effectively
gone.** Two legs in (Red Sox, Cubs), they need 8 and 10 more straight. At a
strong 58% per leg that is 1.28% and 0.43%.

## The math (run `python3 parlay_math.py`)

The price of each parlay tells you the accuracy it demands:

| Slip | Legs | Price | Per-leg accuracy to break even |
|---|---|---|---|
| Table tennis / MMA | 12 | +21074 | 64.00% |
| Golf 2-balls | 14 | +152121 | 59.25% |
| MLB | 10 | +20316 | 58.75% |
| MLB | 12 | +62536 | 58.47% |

Nobody picks 64% on table tennis moneylines. Nobody picks 59% on golf 2-balls.

And a picker who *is* genuinely skilled still loses on these, because the book's
hold compounds with every leg while the edge only multiplies. At a real 55%
edge against a 4.5% hold:

| Legs | Expected return per $1 |
|---|---|
| 1 | $0.957 |
| 4 | $0.839 |
| 8 | $0.703 |
| 12 | $0.590 |
| 14 | $0.540 |

A 55% picker is +EV on singles and burns 41 cents on the dollar by twelve legs.
Same $10, three ways: ten $1 singles returns $10.50; a 3-leg returns $8.76; a
12-leg returns $5.90.

## The fix

1. **Cap at 2–3 legs.** This is the single change that matters. Everything else
   is a rounding error next to leg count.
2. **Only bet where the model disagrees with the market.** `mlb_model.py`
   computes a win probability and compares it to the posted price. No edge, no
   bet — "no +EV plays today" is a valid output.
3. **Never correlate legs.** Golf 2-balls off one leaderboard, or ten home
   favorites, are one bet wearing a costume.
4. **Fractional Kelly staking** (quarter-Kelly), not flat $5 lottery tickets.
5. **Log every bet with the closing line.** Beating the close is the only
   real evidence a model works; win/loss over a weekend is noise.

## Files

- `parlay_math.py` — slip autopsy and parlay EV math. No network needed.
- `mlb_model.py` — Pythagorean team strength + log5 + starting-pitcher
  adjustment + home field, priced against market moneylines with EV and Kelly
  sizing. Needs `statsapi.mlb.com`.

```
python3 parlay_math.py
python3 mlb_model.py --date 2026-08-29 --odds TOR=-155 ATL=-190
```

## Environment note

The sandbox this was written in blocks all outbound sports data
(`statsapi.mlb.com`, `mlb.com`, `espn.com`, Yahoo, Baseball-Reference — every
one refused by the egress proxy). `mlb_model.py` reports that and exits rather
than guessing. Run it somewhere with normal network access and it produces real
numbers.

---

# v3 — stress test, audit, and multi-sport (2026-08-30)

## The correction that matters

An earlier pass in this session reported **61.6% accuracy** for the MLB model.
That number was wrong. It came from a backtest that used end-of-season stats to
predict August games — the model could see the future. Rebuilt with strictly
point-in-time inputs (no stat used for a game includes that game or any later
one), on a held-out window it never touched during fitting:

| Method | Accuracy (757 games) |
|---|---|
| **model v3** | **57.5%** (Brier 0.2449) |
| better W-L record | 55.6% |
| better run differential | 54.6% |
| always pick home | 53.4% |

**McNemar test, model vs. better-record baseline: chi² = 1.03, p = 0.31.**

The ~2-point edge is *not statistically significant* at this sample size. One
standard error is 1.8 points. The model has found a little signal; it has not
proven an edge.

## Bugs found and fixed

1. **Park factors were a no-op.** The venue constant multiplied both teams' run
   expectation, so it cancelled exactly in the win-probability ratio. It was
   reported as a model feature and contributed nothing. Removed — park belongs
   in a totals model.
2. **Probability sharpening made things worse.** An exponent k=1.18 was fitted
   on contaminated in-sample data and pushed probabilities away from 50%.
   Out-of-sample it *degraded* Brier (0.2449 → 0.2455). Shrinking (k=0.50)
   was also worse (0.2456). Raw output wins; the curve is left alone.
3. **Silent team-name mismatch.** The standings endpoint returns `"Rays"`; the
   schedule endpoint returns `"Tampa Bay Rays"`. Keying on name matched nothing
   and printed an empty slate instead of erroring. Now keyed on team **id**.
4. **`slate.py` crashed on soccer** — ESPN emits literal `null` entries inside
   the odds array.
5. **`slate.py` showed only the main event** for UFC/golf/tennis. Those feeds
   put every fight or matchup in `competitions[]`; it read only `[0]`.
6. **`"OFF"` prices** (suspended markets) hit `int()` and were mislabelled
   "price unreadable". Now reported as "market off".
7. **Soccer was priced as a two-way market.** It is three-way; the draw is now
   included in the de-vig.

Not a bug, for the record: the hardcoded starters in `devig.py` were checked
against the MLB API and are **correct**. The apparent mismatches were a
doubleheader (it took game 2), pitchers not yet announced, and an accent in
"Cristopher Sánchez".

## Calibration — read this before betting anything

| Model says | n | Actually wins |
|---|---|---|
| 50–55% | 315 | 55.9% |
| 55–60% | 258 | 58.1% |
| 60–65% | 128 | 59.4% |
| 65–70% | 56 | **58.9%** |

The model is **overconfident at the top**. Its most confident picks do not
outperform its middling ones. Output is clamped at 66% because that is the
edge of what the data supports; treating a 65% pick as better than a 58% one
is not supported by the backtest.

## Files

- `slate.py` — any sport, any date, de-vigged market prices. 16 leagues.
  `python3 slate.py mlb` / `slate.py ufc` / `slate.py epl --date 20260912` / `slate.py --all`
- `model_v3.py` — the validated MLB model. `--backtest` reproduces the table above.
- `mlb_model.py` — earlier model, different functional form, **never validated**.
  Its constants were not retuned to v3's, because those were fitted for a
  different structure and porting them would create a new bug.

## Tennis (added 2026-08-30)

`tennis.py` — US Open / any tour date. `python3 tennis.py --date 20260830`

**A walk-forward Elo was built, tested, and rejected.** On 7,812 completed 2026
matches with an August holdout of 776:

| Method | Accuracy |
|---|---|
| Elo (K=32, walk-forward) | 57.1% |
| more 2026 wins to date | 57.9% |
| better win rate to date | 56.0% |

McNemar, Elo vs. win-count: **chi² = 0.03, p = 0.873.** Indistinguishable from
a one-line heuristic.

**Why it failed:** Elo has no concept of tour level. Final 2026 ratings:

```
Daniel Merida   1660 (29-12)     Novak Djokovic   1624 (15-6)
Thiago Tirante  1643 (28-17)     Daniil Medvedev  1612 (33-15)
Rafael Jodar    1738 (43-14)     Adrian Mannarino 1418 (12-23)
```

A Challenger win counts the same as a Grand Slam win, elite players play fewer
matches, and their losses come against other elite players. Cold-starting
everyone at 1500 compounds it. The model was rating match volume, not strength.

**Replacement:** ranking points, which encode tour level directly —
`p = 1/(1+exp(-(ln ptsA - ln ptsB) * 0.8))`. Scores 60.2% on the same August
matches, but current rankings partly reflect those matches, so that is
**contaminated and not a clean validation**. Unlike `model_v3.py`, this model
has no uncontaminated backtest. Lean, with an asterisk.

Also fixed: `slate.py` returned **zero** rows for every tennis date. Tennis
nests matches under `groupings[]` (Men's/Women's Singles), not `competitions[]`,
and a Grand Slam returns its entire draw regardless of the `?dates=` filter, so
results now get date-filtered in US Eastern.

## Golf two-balls, backtested (2026-08-30)

`golf_2ball.py`. 36 tournaments, 4,191 player-tournament records, point-in-time
skill only (a rating uses rounds from prior events, never the one predicted).
R3/R4 only. Random pairings, n=1,571 decided:

| Signal | Win rate |
|---|---|
| point-in-time season form | 57.8% |
| better tournament position | 52.5% |
| hotter previous round | **52.0%** |
| tie rate | 11.1% |

"Who is playing well right now" is worth **2 points**, confirming the negative
round-to-round correlation found earlier. Season-long form is the only real
signal, and it scales with the gap: 52.0% under half a stroke, 70.9% above two.

**But real two-balls are leaderboard-adjacent**, so the gaps sit in the flat
bottom of that curve. On adjacent pairings the same signal scores **54.8%** and
the tie rate rises to **17.7%** — corrected up from the 9.6% previously
simulated. Without "tie no bet", roughly one leg in six dies on a tie alone.

**Cross-check of the Tour Championship R4 board:** the OWGR-anchored numbers
issued earlier came within **1.1 points mean absolute error** of this empirical
curve. Scheffler/Gotterup was called at 57.7% against an empirical 57.5%. That
model held up.

**Cross-check of the MLB board:** validated `model_v3` agrees with the earlier
v2.1 board on **14 of 14 sides**. Only confidence moved — v2.1 was inflated by
the sharpening step the walk-forward test later showed to be harmful.

## anysport.py — one engine, every league (2026-08-30)

Closes the gap between `slate.py` (which fetched games for any sport) and the
models, which were sport-specific. Walk-forward Elo with tuned K and home
advantage, validated per league on a held-out second half.

`python3 anysport.py wnba --backtest` / `python3 anysport.py nba --date 20261025`

Leagues: wnba, nba, ncaab, nfl, ncaaf, nhl, mlb, epl, mls.

### Validated accuracy by sport — predictability is NOT the same everywhere

| League | Elo | better W-L record | home | n |
|---|---|---|---|---|
| NBA | 72.3% | 69.4% | 55.8% | 631 |
| WNBA | 69.7% | **71.8%** | 55.6% | 142 |
| Premier League | 64.0% | **65.3%** | 56.8% | 125 |
| NHL | 57.1% | **60.0%** | 51.2% | 646 |
| MLB (model_v3) | 57.5% | 55.6% | 53.4% | 757 |
| Tennis (Elo) | 57.1% | **57.9%** | — | 776 |
| Golf 2-ball | 54.8% | — | — | 1571 |

### The consistent finding

**Elo does not significantly beat "pick the team with the better record" in a
single league tested.** It loses outright in WNBA, NHL, EPL and tennis; its
+2.9 in NBA is within 1.5 standard errors. Five sports, same answer.

### The trap in this table

High accuracy is not edge. Basketball is far more predictable than baseball —
and the market knows, so favorites are priced short. On 2026-08-30 the model
liked Dallas over Connecticut at 76.6%, the most likely winner on the board;
the market priced Dallas at 89.3%. Being right 76.6% of the time at a price
that demands 89.3% is a **losing** bet. The most predictable games are the
least profitable ones.

Accuracy tells you how often you are right. Only price tells you whether that
is worth anything.

### Margin-of-victory upgrade

Two margin models added alongside win-loss Elo:

- **MOV Elo** — FiveThirtyEight-form multiplier `((mov+3)^0.8)/(7.5+0.006*edge)`,
  which damps blowouts by already-strong teams so garbage time doesn't run the
  ratings away.
- **Point-differential power ratings** — each team's rating is its expected
  margin vs an average opponent; win probability is the normal CDF of the
  predicted margin over the residual spread.

Both tuned on the first 55% of each season, scored on the rest.

| League | median margin | win-loss Elo | **MOV Elo** | power | best baseline |
|---|---|---|---|---|---|
| NBA | 11 | 72.3% | **73.1%** | 72.7% | 69.4% |
| WNBA | 9 | 69.7% | **70.4%** | 66.9% | *71.8%* |
| EPL | 1 | **64.0%** | 63.2% | 60.8% | *65.3%* |
| NHL | 2 | 57.1% | 53.9% | **58.0%** | *60.0%* |
| MLB | 3 | 54.3% | 54.3% | 53.3% | 53.4% |

**Margin helps exactly where margins carry information and hurts where they
don't.** Basketball (median margin 9–11) gains; hockey (median 2, inflated by
empty-net goals) loses 3.2 points from MOV Elo, and soccer (median 1) loses
too. The mechanism, not the method, decides.

**NBA is the one genuine win:** MOV Elo at 73.1% with the best Brier in the
project (0.1875), beating the better-record baseline by +3.7 points. That is
1.85 standard errors — suggestive, still short of the 2 s.e. bar this repo
uses to call something real.

Note the MLB row: this generic Elo scores 54.3%, while `model_v3.py` scores
57.5% on the same sport. The gap is the starting pitcher. A sport-specific
feature beat three generic rating systems, which is the honest argument for
keeping `model_v3.py` rather than folding MLB into this engine.

Per-league best method is stored in `TUNED` and used automatically by the
board; override with `--method elo|movelo|power`.

## props.py — WNBA player props, backtested (2026-08-30)

`python3 props.py --date 20260830`. Models "X or more" points / rebounds /
assists. 7,759 player-games this season; tuned on July, scored on August
(3,706 props).

| Method | Accuracy | Calibration error |
|---|---|---|
| empirical rate, last 15 | 49.6% | 15.4 pts |
| Poisson on last 10 | 54.9% | 13.0 |
| Normal on last 10 | 54.3% | 9.1 |
| **Normal x P(plays)** | **59.2%** | **4.9** |
| Normal x P(plays), shrunk 0.70 | 58.2% | **3.1** |

### Availability is the biggest single term

Rotation players — 10+ logged games, 15+ minutes a night — **fail to appear in
7.6% of their team's games**. Every "over" dies on those nights no matter how
good the read. Multiplying by P(plays) cut calibration error nearly in half,
the largest single gain of any change in this repo.

### Raw prop models are wildly overconfident

Before correction, the model said 80–90% and delivered **67.6%**. Books set
prop lines at the player's median precisely so both sides sit near a coin flip.
Any model claiming 85% on a median line has mispriced itself, not found an edge.

The shrink exponent was fitted on July and *improved* August calibration
(5.4 → 3.1 pts) — unlike the MLB sharpening experiment, which was fitted
in-sample and failed out-of-sample. Same discipline, opposite result, which is
why both are recorded.

### Roster staleness

Players are assigned to teams by their most recent appearance, and any player
without an appearance in 14 days is dropped. On the 2026-08-30 board that
filter removed 49 players who would otherwise have been priced onto rosters
they no longer play for.

## MLB ensemble — the "ultimate model", and its honest ceiling (2026-08-30)

Combined every component that had earned validation: point-in-time team run
rates, sample-regressed starter ERA, **point-in-time bullpen ERA** (team runs
allowed minus that game's starter earned runs, over the innings the pen threw),
and MOV Elo from `anysport.py`. Weights tuned on **July only**, scored on
**August only** — separate windows, after the first grid search was caught
tuning and scoring on the same data.

Tuned result: **starter 0.65 / bullpen 0.30 / team run-rate 0.05 / Elo 0.00.**

| Model | August holdout | Brier |
|---|---|---|
| `model_v3` (starter + team) | 56.1% | 0.2456 |
| **ensemble (+ bullpen)** | **57.4%** | 0.2458 |

**The gain is +1.3 points with 1 standard error at 2.5 points, and Brier is
flat.** Adding a bullpen term and an Elo ensemble to a validated model bought
nothing measurable. That is the ceiling on this sport with these inputs.

Two things worth recording:

- **Elo tuned to weight zero.** The search was free to use it and refused.
  Baseball has too little signal in win-loss sequence once you know the
  starter — consistent with generic Elo scoring 54.3% on MLB in `anysport.py`.
- **Bullpen took 0.30**, the second-largest weight, confirming the earlier
  ablation where removing the pen cost more accuracy than removing the starter.

The standings short-name trap bit again while building this (`"Marlins"` vs
`"Miami Marlins"`). Team identity now comes from the schedule feed, never from
standings.

## FIP investigation — the deGrom case, tested properly (2026-08-30)

The model priced Texas at 54.9% with deGrom starting while the market had 65.2%.
Hypothesis: the starter term reads only ERA, so it misprices pitchers whose ERA
and peripherals disagree. Pulled K/BB/HBP/HR for all 7,807 starter outings and
built a point-in-time FIP term.

Sanity check: the derived FIP constant came out **3.085**, against the
real-world MLB value of ~3.10.

### Does FIP predict a pitcher's next start better than ERA?

Marginally, across 2,887 point-in-time starts:

| Predictor | Mean abs error, next start |
|---|---|
| ERA | 3.227 runs |
| **FIP** | **3.181 runs** |
| both averaged | 3.181 runs |

**Where ERA and FIP disagree by 1+ runs (28% of starts), FIP is clearly
better: 3.264 vs 3.412.** The hypothesis was right.

### Does it improve win predictions? No.

Sweeping the FIP weight, tuned on July and scored on August:

| w_fip | July (tune) | August (holdout) |
|---|---|---|
| 0.00 | 59.5% / .2436 | 57.4% / .2458 |
| 0.50 | 56.8% / .2455 | 56.1% / .2454 |
| 0.75 | 57.0% / .2464 | 57.1% / .2453 |
| 1.00 | 56.5% / .2473 | 57.1% / .2455 |

July tuning selects **w_fip = 0.00**. Holdout accuracy is unchanged at 57.4%.

### Why the fix is real but the gain is not

Mean absolute error predicting one start is **3.2 runs**. The entire ERA spread
between good and bad MLB starters is ~1.1 runs, and the standard deviation of a
single start around a pitcher's own mean is **4.02 runs**. A 0.05-run
improvement in the input is invisible under that much noise.

FIP is kept at a 0.50 blend on one narrow ground: it cuts mean disagreement
with the market from **5.3 to 4.5 points** across the 8/31 board. Closer
agreement with a liquid market is the best available proxy for being less
wrong. It is explicitly NOT claimed to improve win accuracy — the holdout says
it does not.

**And it did not rescue the case that motivated it.** deGrom's FIP (3.19) is
much better than his ERA (4.21), which should raise Texas — but opposing
starter Gage Jump's FIP (3.74 vs 4.69 ERA) improves by nearly as much, and they
cancel. Texas moved 54.9% -> 55.6%, still 9.6 points under the market. That
game remains a spot where the model is probably wrong and should not be bet.

## Does the model beat the market? No. (2026-08-30)

The one test that was missing all session. ESPN's scoreboard drops moneylines
once games finish, but the **core API retains them** —
`/events/{eid}/competitions/{cid}/odds` → `awayTeamOdds.moneyLine`. That yields
closing DraftKings prices for **2,045 completed 2026 games, 100% coverage**.

Model run strictly point-in-time over 655 games, Jul 1 – Aug 30:

| Method | Accuracy | Brier |
|---|---|---|
| model | 55.9% | 0.2452 |
| **market favourite** | **57.3%** | **0.2418** |

**The market is more accurate and better calibrated than the model.**

### Betting the model's edge at real prices

| Claimed edge | Bets | Win rate | ROI |
|---|---|---|---|
| ≥ 0 pts | 655 | 50.2% | +2.1% *(95% CI −5.8% to +9.7% — noise)* |
| ≥ 2 pts | 491 | 47.9% | −1.0% |
| ≥ 4 pts | 354 | 46.9% | −1.2% |
| ≥ 6 pts | 225 | 44.0% | −6.5% |
| ≥ 8 pts | 134 | 44.0% | −4.8% |
| **≥ 10 pts** | **72** | **38.9%** | **−14.3%** |

**The bigger the edge the model claims, the worse the bet does.** Monotonic.
When this model says the market is ten points wrong, backing it has returned
**−14.3%**.

### What this retracts

Every "+EV" number produced in this repo. A +20% EV figure does not mean value
— it means the model has diverged violently from a market measured here as more
accurate than the model, and those are precisely the bets that lose fastest.

The 57.5% accuracy figure elsewhere in this README stands and is useless for
betting. Beating a coin flip is not beating a book. The model's honest use is
as a sanity check on a price, never as a reason to take one.

## The fix: anchor to the market (2026-08-30)

Pure model loses to the market. Pure market is beatable by a hair. Sweeping the
blend weight, tuned on June–mid July and scored on 516 held-out games:

| Weight on model | Test accuracy | Test Brier |
|---|---|---|
| pure market | 57.4% | 0.2407 |
| **10% model / 90% market** | **57.8%** | **0.2406** |
| 20% model | 59.3% | 0.2407 |
| 50% model | 58.1% | 0.2413 |
| pure model | 56.0% | 0.2440 |

Tuning selects **10% model**. The gain over pure market is 0.0001 Brier —
effectively a tie, but it means the model adds a sliver of information rather
than subtracting. What is *robust* is the shape: **the more weight the model
gets, the worse it does.** Pure model is the worst row in the table.

Every board from here is generated at 90/10. That single change kills the
"+20% EV" plays, which the ROI table already showed return −14.3%.

### Why the day-to-day results swing so hard

A 57% process on a 14-game slate has an expected 8.0 wins and a standard
deviation of **1.9 games**. The normal range is 6 to 10.

| Wins of 14 | Share of days |
|---|---|
| 11+ | 8.4% |
| 8 | 21.2% |
| 5 or fewer | 9.1% |

Saturday's 11-of-12 and Sunday's 2-of-6 are both ordinary outcomes of the same
unchanged process. Nothing broke between them, and nothing was fixed between
them either. **On 2026-08-30 the model went 2–4 on completed games and the
market's favourites also went 2–4** — the day beat everyone holding chalk.

## dashboard.py + board.html — the live board (2026-08-30)

Twelve leagues in tabs: MLB, WNBA, NFL, NCAA FB, NBA, NHL, ATP, WTA, PGA,
Premier League, MLS, UFC.

**`dashboard.py` — the live one.** `python3 dashboard.py`, open
`http://localhost:8000`. A background thread refetches every 5 minutes and the
page reloads on the same cadence, so an open tab is never more than one cycle
stale. `--port` and `--interval` are configurable.

**`board.html` — the shareable one.** A published Artifact. It is a *snapshot*,
not live, and that is a platform constraint rather than a shortcut: a published
Artifact runs under a CSP that blocks external fetch/XHR entirely, and the only
runtime capabilities available (`artifact`, `downloads`, `mcp`, `self`) grant no
arbitrary network access. `mcp` reaches the viewer's own claude.ai connectors,
not ESPN. So a hosted page can hold data baked in at publish time and nothing
more. Republish to refresh it.

### The Lean column is the market, not the model

Deliberate. Over 655 MLB games against real closing prices the market called
57.3% and the model 55.9%, and backing the model where it disagreed lost more
the louder it disagreed (−1.0% at a two-point gap, −14.3% at ten). The board
shows the better forecast.

### Bug caught while building it

The tennis tabs rendered **625 rows** — a Grand Slam returns its entire draw
across all rounds and dates regardless of the scoreboard date filter. Ported the
US-Eastern date filter from `slate.py`; tennis now shows the day's 40 matches.
Same class of bug as the original `slate.py` tennis failure, in new code.
