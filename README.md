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

## dashboard.py + board.html — the upcoming board (2026-08-30)

**Upcoming games only.** Anything completed or in progress is dropped — a
settled game is not a pick, and a live one cannot be taken at the posted price.

**Each cycle re-researches and diffs against the last one**, so genuinely new
information surfaces in a "New since last cycle" feed instead of being buried:

| Watched | Reported as |
|---|---|
| starter goes TBD → named | `starter named — Molina 2.89 vs Elder 3.95` |
| moneyline moves | `Rays -170 → -172 (-2)` |
| pick changes side | `pick flipped Marlins → Nationals` |
| game appears for the first time | `new on the board` |

The **Analysis** column carries the probable starters and their season ERAs for
MLB, pulled from the MLB StatsAPI on every cycle, so the number is legible
rather than asserted.


Twelve leagues in tabs: MLB, WNBA, NFL, NCAA FB, NBA, NHL, ATP, WTA, PGA,
Premier League, MLS, UFC.

**`dashboard.py` — the live one.** `python3 dashboard.py`, open
`http://localhost:8000`. A background thread refetches every 5 minutes and the
page reloads on the same cadence, so an open tab is never more than one cycle
stale. `--port` and `--interval` are configurable.

**Two days, not one.** Every refresh fetches *today and tomorrow* for all twelve
leagues in a single pass, and both surfaces carry a Today/Tomorrow switch above
the league tabs. Routes are `/{today|tomorrow}/{league}`. Multi-day events (a
Grand Slam draw, a golf week) are filtered to the selected day in US Eastern, or
tennis returns its entire bracket on both tabs.

Tomorrow's rows fill in as books post — most MLB lines go up overnight, so a
board captured in the afternoon shows fewer prices for tomorrow than one
captured at night.

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

## Everything else, thrown at it (2026-08-30)

Pulled every remaining signal the feeds expose and tested each one walk-forward,
tuned on July and scored on August. Weather coverage was 100% across 2,052
games — temperature, condition, wind speed and direction, plus day/night, series
position, and fatigue/rest computed from game logs.

| Added feature | July (tune) | August (holdout) |
|---|---|---|
| **baseline** | 54.9% / .2455 | **56.0% / .2458** |
| + starter rest days | 55.1% / .2452 | 56.2% / .2456 |
| + getaway day | 55.7% / .2453 | 55.5% / .2459 |
| + bullpen fatigue (3-day IP) | 54.3% / .2474 | 56.2% / .2456 |
| + wind speed × direction | 54.6% / .2459 | **55.0%** / .2473 |
| + temperature | 54.9% / .2457 | 55.8% / .2464 |
| + day/night | 57.3% / .2455 | 56.8% / .2461 |
| + head-to-head series | 55.7% / .2462 | **55.2%** / .2461 |
| + win streak | 56.8% / .2465 | 56.5% / .2460 |
| **all that helped on tune, combined** | — | **56.2% / .2457** |

Two features improved on the tuning window. Combining them moved the holdout by
**+0.2 points of accuracy and 0.0001 Brier** — noise. Several made it actively
worse: wind cost a full point, head-to-head nearly as much.

### The complete list of things tested this session

park factors · FIP · Elo · margin-of-victory Elo · point-differential power
ratings · bullpen ERA · platoon splits · probability sharpening · probability
shrinking · weather · temperature · wind · day/night · getaway day ·
head-to-head · win streaks · starter rest · bullpen fatigue

**Only bullpen ERA ever produced a real gain.** Everything else landed inside
the noise or hurt.

### Why more data cannot fix this

Every signal above is *public*. The book has the same weather report, the same
rest days, the same bullpen usage — and prices them before posting. Adding
information the market already holds cannot create an edge against that market;
it can only move you closer to a number the market already found.

Edge would require either data the market does not have, or a genuinely better
way of combining what everyone has. Measured over 655 games with real closing
prices, this model's combination is **worse** than the market's: 55.9% to 57.3%.

That is the honest end of the road on public data.

### Why the published board is not live, and what runs instead

A published Artifact **cannot fetch anything**. Its CSP blocks every outbound
request, and none of the runtime capabilities available (`artifact`,
`downloads`, `mcp`, `self`) grant network access — `mcp` reaches the viewer's own
claude.ai connectors, not ESPN. The page can only hold data baked in at publish
time. That is a platform property, not a shortcut.

So keeping it current means re-baking and republishing it:

- **`rebuild_board.py`** re-researches all twelve leagues for today and
  tomorrow, diffs against the previous run, rewrites the embedded data block in
  `board.html`, and prints what moved. One command.
- An **hourly Routine** (`trig_015WGar6u9pKE2SDuPMYdXay`, fires at :17) runs
  that and republishes the artifact. **One hour is the scheduler's floor** — a
  5-minute cron is rejected outright.
- **`dashboard.py`** is the only genuine 5-minute surface, because it runs as a
  real server that can make outbound calls. `python3 dashboard.py`.

| Surface | Cadence | Fetches live? |
|---|---|---|
| `dashboard.py` | 5 min | yes |
| published artifact | hourly, via Routine | no — republished |

## Favourite-longshot bias, measured (2026-08-30)

A board that only names favourites points at the worst-priced side of every
game. Measured across **4,090 real sides of 2,045 completed 2026 games** at
closing DraftKings prices:

| Price band | Actually won | Price implied | Gap | Flat ROI |
|---|---|---|---|---|
| −200 or shorter | 66.9% | 70.8% | **−3.9** | −5.5% |
| −200 to −160 | 58.9% | 63.8% | **−4.9** | **−7.8%** |
| −160 to −130 | 54.5% | 58.8% | **−4.3** | −7.4% |
| −130 to −100 | 51.8% | 53.3% | −1.5 | −3.0% |
| +100 to +130 | 46.2% | 47.0% | −0.8 | −1.5% |
| +130 to +160 | 41.1% | 41.3% | **−0.2** | **−0.7%** |
| +160 to +200 | 35.9% | 36.4% | −0.5 | −1.6% |
| +200 or longer | 28.6% | 30.2% | −1.6 | −5.1% |

**Every favourite band won less often than its own price implied.** Underdog
bands land within a point of fair. Blind on every game: **favourites −5.6%,
underdogs −1.3%.**

Neither wins — that is the vig — but the favourite is consistently the more
expensive way to be right, and the −200 to −160 band, the worst on the board at
−7.8%, is exactly where parlay legs come from.

The board now shows **both sides of every game** with price, implied
probability, and that band's historical ROI, plus a DOG tag on the side the
market prices as less likely. The tag is a price marker, not a recommendation:
on 2026-08-30 four underdogs won of thirteen priced games, and backing all of
them blind lost four units.

## picks.py — my model's call on every game (2026-08-31)

The board previously echoed the bookmaker's favourite. It now carries my own
forecast for every game in every league that has a validated model, with the
numbers that produced it.

| League group | Method | Held-out accuracy |
|---|---|---|
| MLB | starter ERA/FIP (regressed) .65 + bullpen ERA .30 + team run rates .05 | 57.5% |
| NBA / WNBA / NCAAF / NFL | margin-of-victory Elo | 73.1% / 70.4% |
| NHL | point-differential power ratings | 58.0% |
| EPL / MLS | win-loss Elo | 64.0% |
| Tennis | ranking points, `1/(1+exp(-(ln ptsA − ln ptsB)·0.8))` | 57.1% |

Each pick ships with a **Why**: the starters and their ERA/FIP, the bullpen gap
where it exceeds 0.35 runs, recent form, or the rating gap and last-ten record
for team sports. The reasoning is inspectable rather than asserted.

The market moves to a check column. A **DOG** tag marks a game where my model
takes the side the book prices as less likely — the real disagreements, and
also the ones most likely to be my error: over 655 MLB games the market called
57.3% against my 55.9%, and backing my disagreements lost up to 14.3%.

Coverage on 2026-08-31: **109 of 109 upcoming games carry a model pick**, against
13 that had a posted price.

## Slip builder (2026-08-31)

Tap any pick to add it to a slip. The slip prices the parlay live and hands off
to the sportsbook.

**The handoff is real, not a mock.** ESPN's odds feed carries DraftKings
bet-slip deep links per outcome, wrapped in a tracking gateway whose `preurl`
holds the actual sportsbook URL. `deep_links()` unwraps it and extracts the
outcome id; the slip joins them into
`sportsbook.draftkings.com/event/{id}?outcomes=a,b,c`. All 24 sides of the
2026-08-31 MLB slate resolved. The full URL is also printed as copyable text,
since a sandboxed page cannot guarantee an outbound navigation succeeds.

**What the analysis shows** — combined parlay price, what $5 returns, the
probability the book's price implies, my model's own probability (product of
per-leg confidences), and the resulting expected value. Plus two warnings drawn
from measurements in this repo rather than intuition:

- two or more legs priced −130 to −200 flags the band that returned −7.4% to
  −7.8% across 4,090 settled sides;
- four or more legs flags the structure that produced 9-of-12 and 11-of-12
  tickets which both paid zero.

A bug worth recording: `render()` reads `SLIP`, but the initial paint ran before
`const SLIP` was declared — a temporal-dead-zone ReferenceError that blanks the
page on load. Caught by executing the script against a stub DOM before
publishing rather than by eye. `SLIP` is now declared alongside `D`, and the
first paint is the last statement in the file.

### Fanatics handoff

Fanatics publishes **no betslip deep link**. Verified three ways rather than
assumed:

- ESPN's odds feed carries 62 deep links across MLB, NFL, WNBA and NCAAF — **all
  DraftKings**, no Fanatics;
- The Odds API's deep-link product supports **FanDuel and Betfair only**;
- no public Fanatics URL scheme is documented anywhere.

Inventing a plausible-looking URL would ship a link that 404s, which is worse
than none. So the Fanatics path is a **numbered transcription block** — one leg
per line with its price and league, plus the parlay total — copied in one tap:

```
1. Boston Red Sox   -167   [MLB]
2. Atlanta Braves   -155   [MLB]
3. Tampa Bay Rays   -172   [MLB]

3-leg parlay   +316   $5 returns $20.80
```

The clipboard API can be blocked in a sandboxed page, so a failed write falls
back to selecting the block for a manual copy rather than silently doing
nothing. The DraftKings link stays as a secondary because that one genuinely
resolves.

## 8/31 — two plausible ideas, both wrong; one real fix that changes no picks

Three high-confidence tennis picks lost today: Collignon (82%) to an unranked
qualifier, Tauson (83%) to an unranked Sloane Stephens, Waltert (78%). Twice I
wrote that the culprit looked like the model's flat 180-point floor for
unranked players — an unranked former Slam champion and an unranked journeyman
score identically. It was a clean story and it fit the losses.

It was wrong. Tested on 7,892 deduplicated 2026 singles matches, split Jan–Jul
train / August test:

| bucket | n (train) | model said | actually won | gap |
|---|---|---|---|---|
| both ranked | 3,565 | 62.3% | 64.9% | **+2.6** |
| opponent unranked | 2,048 | 76.5% | 75.9% | −0.5 |

The unranked gap is −0.5 on two thousand matches. There is nothing there. It
only appears in August (−6.3, n=267), which is the same small sample that
produced the losses I was reasoning from. I was pattern-matching on noise and
had said so out loud twice.

**Recent form also fails.** Blending a last-10 win-rate differential in
(weight fitted on train) flipped 55 August picks, and those flips were right
**47%** — worse than a coin flip. Held-out accuracy went 65.3% → 65.0%. This
is the third time a form-like feature has been tried and rejected here; Elo,
which is largely a form-and-volume measure, failed the same way.

**What is real** is the effect hiding in the first row: the model is
under-confident whenever both players are ranked, and the gap replicates out of
sample (+2.6 train, +5.9 test, both beyond two standard errors). A single scale
of 0.80 shrinks those matchups too far toward 50%. Fitting two scales on
Jan–Jul and scoring August:

| | Brier | accuracy |
|---|---|---|
| 0.80 flat | 0.2207 | 65.3% |
| 1.02 ranked / 0.78 otherwise | **0.2190** | 65.3% |

Better in 95% of 2,000 bootstrap resamples, with no overshoot at the top
(80–90% band lands +0.7 on n=91).

**And it changes not one pick.** The scale is a monotonic transform, so the
favoured side is identical either way — verified against tomorrow's board: 40
of 40 tennis picks unchanged, 39 confidences moved. It makes the numbers
honest; it does not find more winners.

The lesson worth keeping: today's losses were mostly variance, and the two
explanations that felt most insightful were both false. The only finding that
survived contact with the training data was one I had not noticed and that
pays nothing in accuracy. That is the normal shape of an honest result.

## The upgrade that was never a model problem

Every improvement in this repo has targeted accuracy. Accuracy is not what has
been losing. `parlay_opt.py` prices the structure instead, using hit rates
measured on held-out data rather than model confidence — the two are different
numbers and conflating them is how a 24-leg ticket gets built.

At the best rate this project has ever measured (84.6%, tennis 80–90% band with
both players ranked, n=91 August):

| legs | wins | book pays | EV per $1 | 1+ win in 30 tickets |
|---|---|---|---|---|
| 1 | 84.6% | −756 | −4.2% | 100% |
| 4 | 51.2% | −155 | −15.8% | 100% |
| 8 | 26.2% | +170 | −29.1% | 100% |
| 12 | 13.4% | +344 | −40.4% | 98.7% |
| 24 | 1.8% | +1,869 | −64.4% | 42.1% |

At the 70.6% rate that a realistic mixed tennis card supports, a 24-leg ticket
wins **once every 4,253 tries** and returns −64.4%. The two tickets actually
played on 8/31 were 24 and 25 legs.

The mechanism is that the book's margin compounds at exactly the rate the win
probability decays, so expected value falls monotonically with every leg added.
No achievable model accuracy reverses that: at a perfect-looking 84.6% per leg,
24 legs still returns −64.4%. Fewer legs is not a preference, it is arithmetic.

## Does the model add anything the price does not already know?

Asked properly for the first time: a logistic regression on 1,347 Apr–Jul games
with two features, logit(market) and logit(model), scored on 405 August games.

    market only    bias +0.045   market +0.876
    market + model bias +0.045   market +0.580   MODEL +0.439

    model coefficient, 95% CI over 300 bootstraps: [+0.097, +0.831]

The coefficient excludes zero, so the model does carry information beyond the
closing price — the first evidence in this repo that it is not pure noise once
you know the line. On 349 training games the same test could not detect it
(CI [−0.272, +1.494]); the earlier negative was underpowered, not a finding.

It does not translate into better August predictions: Brier 0.2393 blended
against 0.2391 for the raw price, accuracy 59.3% against 58.8%. Real signal,
too small to beat the vig.

## The August ROI that is not an edge

Betting the model's disagreements at real closing prices, August only:

    edge >= 0pt   n=227   ROI +10.8%   95% CI [-1.3%, +22.8%]
    edge >= 4pt   n=117   ROI +12.2%   95% CI [-5.9%, +30.9%]

Both intervals contain zero. And the same model over the longer Jul 1 - Aug 30
window in `vs_market.py` returned -1.2% at the 4-point threshold and -14.3% at
ten points, monotonically worse with edge size.

Same model, overlapping data, opposite sign, depending on where the window is
cut. That is the signature of noise, not of an edge that appeared in August. A
single month of +10% on 227 bets is roughly what a coin flip produces at these
prices, and the confidence interval says so directly.

Recorded here because the temptation is to keep the flattering window. The
honest read remains the longer one.

## Two MLB models, and the wrong one was being quoted

`model_v3.py` is the file with the validated backtest, and every MLB accuracy
figure in this repo and on the site came from it: 0.55 starter / 0.45 team run
rates, no bullpen, 57.5%.

The board does not use it. `picks.py` runs 0.65 starter / 0.30 bullpen / 0.05
team, and had never been backtested. Every MLB pick shown has come from that
formula while a number belonging to a different one was displayed beside it.

Run head to head, walk-forward over 780 held-out Jul-Aug games, with bullpen
ERA rebuilt point-in-time by differencing the pitcher index (each start's own
ER and IP, so nothing from the future enters):

| formula | Brier | accuracy |
|---|---|---|
| model_v3  0.55 / 0.00 / 0.45 | 0.2448 | 57.4% |
| **board  0.65 / 0.30 / 0.05** | **0.2443** | **58.6%** |
| fitted on train  0.75 / 0.05 / 0.20 | 0.2450 | 57.1% |

The board's formula is the better one — bullpen ERA earns its 30%. The error
was in the bookkeeping, not the picks: they were slightly better than
advertised. The site now shows 58.6%.

The third row is the recurring lesson. Grid-searching the three weights on the
1,052-game training half returned 0.75/0.05/0.20, which then scored worse out
of sample than either hand-set version. That is the fourth time in this project
that fitting a parameter has degraded held-out performance. The bootstrap is
also honest about the margin: the board's formula beats model_v3 on Brier in
77.9% of 2,000 resamples, short of the 95% that would make it decisive.

## Validating soccer: the problem was my sample, not the model

Eight soccer leagues went up tagged UNVALIDATED because each one, tested alone,
"could not be distinguished from noise". That label was wrong about where the
problem was. A single league gives a 60-200 match holdout where one standard
error is 3-6 points; nothing can clear that bar. I was reporting my own lack of
statistical power as a property of the model.

Pooled instead: 33 leagues, 12,460 completed matches, ratings still per-league
but hyperparameters fitted once on a training half and scored on the rest. A
draw counts as a LOSS throughout, because that is what it does to a 3-way
moneyline — scoring a draw as a half-win would validate a bet nobody can place.

    HELD-OUT HALF -- 5,977 matches
      my pick wins outright     49.1%
      always pick home          44.0%
      better win rate to date   46.3%
      edge over best baseline   +2.8 pts = 4.3 standard errors

That is decisive. All 35 soccer leagues now run one configuration: margin-of-
victory Elo, k=24, 50 Elo of home advantage.

### The flaw it exposed

Elo scores a draw as half a win, so its expectation runs hot against "does my
side win outright" — by 12 to 14 points across every confidence band. A logistic
map fitted on the training half fixes it:

    p_outright = sigmoid(-0.591 + 1.485 * logit(p_elo))

    HELD-OUT Brier   raw 0.2567  ->  recalibrated 0.2436

Six times the improvement the tennis recalibration produced, and the residual
gaps fall from -13 to between -0.3 and -6.

Three leagues previously dropped for losing to the home baseline (League One,
South Africa, Austria) are back: they were rejected on the same underpowered
per-league test, and the pooled result covers them.

---

# The dead zone (2026-09-01)

Asked to push tennis and baseball higher, I tested five ideas. Four failed.
The one that worked is not a better model — it is the discovery that half of
what the model prints is noise wearing a number.

## What was tested and rejected

**MLB park factors.** Built point-in-time (a park's runs per game against the
league, shrunk by sample size, from prior games only), used both to de-park
team run rates and to re-park the run estimate for the game being played.
Result: 3 picks changed out of 760, accuracy −0.1 pts.

There is a reason, and it is algebraic rather than empirical. Pythagenpat is a
*ratio* — `r_a^e / (r_a^e + r_h^e)`. A park factor multiplies both teams'
expected runs by the same number, so it cancels exactly. Park can only reach
the win probability through the second-order de-biasing of team rates, and that
is worth nothing measurable. A park factor cannot help a ratio model unless it
acts asymmetrically on the two sides — which needs batted-ball profiles the
public feed does not carry.

**MLB recency weighting.** Exponentially weighted team run rates against the
flat season average, half-lives from 100 games down to 10:

    season average          57.5%   Brier 0.2446   n=760
    half-life 100 games     56.6%   (-0.9 pts)
    half-life  40 games     56.7%   (-0.8 pts)
    half-life  10 games     54.6%   (-2.9 pts)

Monotonic and consistent on both holdout windows: the harder you weight recent
games, the worse it gets. Team run-scoring is stable; recency weighting just
throws away sample. **This is the fourth time in this project that "use recent
form" has lost on held-out data.** It should stop being proposed.

**Tennis Elo, repaired three ways.** `tennis.py` rejected Elo for rating
Challenger grinders above Djokovic. In this ESPN sample the mechanism looked
concrete and fixable: 2,600 of 7,919 matches are qualifying rounds, where a
player can bank three wins that count as much as a Slam quarterfinal. So Elo
was rebuilt with K scaled by draw level, by event tier, and by both:

    plain         58.4%   (the rejected one)
    round         56.2%   (-2.2 pts)   <- the hypothesis
    tier          58.5%   (+0.1 pts)
    both          57.5%   (-0.9 pts)
    sets          58.8%   (+0.5 pts)
    surface       58.4%   (+0.0 pts)

Discounting qualifying matches made it *worse*, and every other variant landed
inside one standard error (n=877, s.e. 1.7 pts). The qualifying-round theory
was wrong, and separate surface ratings — the single most-cited tennis
adjustment there is — did nothing at all.

## What survived: the model is a coin flip half the time

Walk-forward Elo over 3,224 completed 2026 matches, cut into monthly blocks
the thresholds were never fitted to:

    says 50-58%   803/1577 = 50.9%  (+-1.3)
    says 58-64%   504/826  = 61.0%  (+-1.7)
    says 64%+     580/821  = 70.6%  (+-1.7)

The bottom band is not a weak edge. It is *nothing* — 50.9% against a coin's
50%, with an error bar of 1.3 points. And it is not a quirk of one window or
one hyperparameter. Every month gives it:

    May 53.6%   June 49.0%   July 50.3%   August 50.8%

and so does every K (16 → 53.9%, 24 → 53.4%, 32 → 50.9%, 48 → 50.4%). No
monotone rescaling can repair it, because rescaling cannot create a flat
region where the data has one.

MLB shows the same shape, weaker and less well powered. Games where the two
starters are within a quarter of a run of each other, on a holdout the cut was
frozen before touching:

    close-pitcher games    48/96   =  50.0%  (+-5.1)
    clear-pitcher games   171/294  =  58.2%  (+-2.9)

+8.2 points, but only 1.4 standard errors — suggestive, not established. It
points the same way on the training half (+2.9), and the close bucket has never
once cleared 55% in any window.

## Why this is worth more than a better model

For a single bet, a 55% leg is mildly positive. For a parlay it is poison,
because the slip multiplies. Keeping only tennis legs the model calls 58% or
better:

    keep everything      877 legs   58.4%
    keep >= 58%          440 legs   65.9%
    keep >= 64%          201 legs   73.1%
    keep >= 70%           97 legs   78.4%

Half the slate, a 7.5-point jump in per-leg hit rate. Across twenty legs that
is the difference between one slip in five thousand and one in thirty.

No model change achieved anything close to that. Throwing away the bottom half
of the board did.

## Shipped

`rebuild_board.py` now tags every pick with a conviction tier at the measured
break points (58 / 64 / 72), and `board.html` hides the coin flips by default
with a one-click reveal. The tiers are cuts in the number the board already
prints, so nothing about the underlying models changed — the page just stops
presenting a coin flip as a lean.

**Caveat, stated plainly:** the thresholds come from walk-forward Elo, because
Elo is the only tennis estimator that can be built point-in-time from this
feed. The shipped board runs on ranking points, whose current values are
contaminated by the very matches any backtest would score. The *mechanism* —
two close players produce a coin flip, and no strength model can beat that — is
estimator-independent. The exact cut is not. The ledger now tags each graded
pick with its tier, so within a few hundred more calls the board can be
validated against its own record instead of a proxy.

---

# MLB totals and run line — tested against closing prices, not shipped (2026-09-02)

Asked to add over/under and run-line picks. Both were built, both were scored
against **DraftKings closing numbers** on 1,812 games with a matched
walk-forward model, and neither is worth shipping. Writing down why, so this
does not get proposed again without new information.

## The data

ESPN's scoreboard drops the odds node once a game goes final, which is why an
earlier harvest came back with 2,071 games and zero lines. The core API keeps
`open` / `close` / `current`, so the sample here is genuine closing lines:
2,071 of 2,071 games with a closing total and a closing run line.

## Totals: the model knows nothing the line does not

Expected runs per side come from the same engine that prices the moneyline;
totals fall out of simulating both sides from a gamma-mixed Poisson whose
dispersion (3.53) was fitted on April–June and frozen.

    TRAIN 04-06   every game  49.6%   ROI  -5.6%
    TEST  07-08   every game  53.1%   ROI  +1.3%

Opposite signs across windows, which alone is disqualifying. Worse, the edge
filter runs **backwards** — the more the model disagrees with the line, the
worse it does:

    TRAIN  edge>=2%  48.7%   edge>=6%  46.9%
    TEST   edge>=2%  53.0%   edge>=8%  50.7%

A real edge gets better as you raise the threshold. This gets worse, which is
the signature of disagreement that is pure noise. The direct test confirms it:

    corr(model total - line, actual total - line) = +0.014  (+-0.024)

Zero, on all 1,812 games and in both halves separately. And the model's own
number is a *worse* estimate of the actual total than the line is — mean
absolute error 3.586 runs against the closing line's 3.485.

One tempting artefact, checked and dismissed: the mean actual total (8.97)
sits 0.48 runs above the mean closing line (8.49), which looks like a standing
"overs" bias. It is not — it is right-skew, blowouts dragging the mean while
the median sits still. Betting every over at the closing price:

    over hits 49.4% over 1,979 games (+-1.1)   blind OVER ROI -5.5%

and month to month it wanders 44.4% to 55.2% with no stability. The total is
efficiently priced.

## Run line: a high hit rate that still loses money

    TRAIN  59.7% covered   ROI -2.0%
    TEST   57.2% covered   ROI -6.3%

Winning 57–60% of your bets sounds like the "solid" market, and it is the trap
in this whole exercise. Those wins are almost all the underdog taking +1.5 at
a price like -178, which needs ~64% to break even. A high hit rate at a bad
price is worse than a low hit rate at a good one — and in a parlay it is worse
still, because the payout is built from the prices.

The mirror side, the favourite laying -1.5 at plus money, is the only place
where an edge could survive the vig. It does not:

    TRAIN  covered 41.2%   book implied 43.1%   model said 38.5%   ROI -4.5%
    TEST   covered 42.0%   book implied 43.6%   model said 38.7%   ROI -3.4%

The model is biased low by 3+ points — simulating the two sides independently
understates how often a good team beats a bad pitcher badly. The filtered
buckets that look positive (train edge>=6%: +18.5% on n=68) have no surviving
counterpart in the test half, and the test's best bucket is +6.8% on n=136,
where one standard error on ROI is about 10 points.

## What this means

The moneyline model carries real information; the derived markets do not.
That is not a contradiction. A moneyline needs only the *ordering* of two
teams' scoring, which season run rates and a starter's ERA capture. A total
needs the *level* of combined scoring and a run line needs the *shape* of the
margin — both of which demand park-adjusted, handedness-aware, bullpen-usage
inputs that this public feed does not carry, and both of which the closing
line already prices better than this model does.

Nothing was shipped. Adding these as picks would have handed over legs with
negative expectation dressed up as coverage, which is the exact failure the
conviction tiers were added to prevent.

---

# Beating the price instead of the game (2026-09-02)

Pushed on the fair point that filtering the board is what a book does, and
that the job is to find what the price does not contain. Four attempts.

## Rejected

**Tennis fatigue.** A rating knows how good a player is; it cannot know that
one of them went five sets the day before yesterday. A first pass looked
promising — workload over 7 days correlated with the surprise in the result at
2.7 standard errors. It was an artefact: the test labelled the winner `w` and
then measured a variable defined from the winner's identity. Relabelled
symmetrically (A = higher rated, y = A won, everything computed pre-match) and
fitted on May–July, scored on August:

    rating only                test 59.2%   Brier 0.2345
    rating + workload          test 59.6%   Brier 0.2345
    rating + rest days         test 58.6%   Brier 0.2344
    rating + both              test 59.4%   Brier 0.2342

Nothing. The first result was the trap, not the finding.

**MLB bullpen availability.** The model puts 30% of its weight on a team's
season relief ERA, which describes a bullpen that never exists — the arms that
worked the last two days are down. Rebuilt from 13,340 relief appearances,
point-in-time, counting an arm out if it worked back-to-back or threw 2+
innings yesterday:

    season bullpen      56.2%   available bullpen  55.7%   (-0.5 pts)

The diagnostic explains it: availability moves a bullpen's ERA by a **median
of 0.025 runs**, 0.26 at the 90th percentile. At 30% weight inside a ratio,
that is nothing. The idea is sound and the magnitude is simply too small.

**Predicting the line move.** The correlation between the model's disagreement
with the opener and the market's subsequent drift is +0.103 (+-0.024), which
looks like 4.4 standard errors of signal. It is not: the market moves the same
way the model does only **49.9%** of the time. The correlation is picking up
magnitude — volatile games move more — not direction. Slope is +0.037, so the
market travels under 4% of the way toward the model. Betting the opener on
disagreement returns +3.9% in April–June and −4.9% in July–August.

## What did hold: the tax is not spread evenly

Betting every 2026 MLB game at the closing price, by price bucket:

    dog  +100..149   n=1371   ROI -1.19%
    fav  -100..149   n=1757   ROI -5.24%
    fav  -150..199   n= 531   ROI -5.08%

Four points of difference. That is the favourite-longshot bias — the standing
price of the public's preference for backing winners — and it is priced into
every board on the internet whether or not anyone points at it.

Spending the model's edge on the taxed side wastes it:

    model picks that are favourites   n=1480   won 56.9%   ROI -2.95%
    model picks that are underdogs    n= 332   won 48.5%   ROI +5.31%

The underdog picks **win less often and still make money**. That is the whole
result. It is not the model being clever — 48.5% is worse than its favourites
by eight points — it is the price being cheaper. Which is also why it should
travel: it does not require out-predicting the market's read of the game, only
for the vig to be lighter on one side of it. Positive in both halves
(Apr–Jun +1.2% on 221, Jul–Aug +13.5% on 111).

Stated honestly: n=332 is about one standard error, so this is well-founded
rather than proven. It has a known mechanism, it replicates in both halves,
and it survives every edge threshold (+5.0% to +7.0%). The favourite picks
clear zero at no threshold at all.

## Shipped

MLB underdog picks now carry a VALUE tag. The instruction that follows from
the numbers is blunt: **when the model likes an underdog, that is the bet.
When it likes a favourite, the book's tax is larger than the model's edge.**

## The pattern across every test in this file

Nine ideas tested over two days; two survived. Both survivors are about *which
bets to place*, not about predicting games better — the dead zone in tennis
confidence, and the vig gap between dogs and favourites. Every attempt to
predict the games themselves better (park factors, recency, surface, Elo
repairs, fatigue, bullpen availability, line movement) failed against
held-out data.

That is worth stating plainly rather than burying: on public data, at the
game level, this model is at or near its ceiling. The remaining money is in
selection and price.

---

# The price map: where each book's tax actually sits (2026-09-02)

The MLB underdog result raised an obvious question — does it generalise? It
does not, and finding that out mattered more than the original result.

Betting blind at closing prices and counting, across roughly 26,000 games
harvested from ESPN's core API (which retains odds after a game finalises,
unlike the scoreboard):

    sport    favourites   underdogs      gap        n
    WNBA       -7.16%       +3.91%    +11.07      620
    MLB        -5.24%       -1.19%     +4.05     1812
    NHL        -5.50%       -1.49%     +4.01     2935
    NFL        -5.65%       -7.10%     -1.45      627
    NBA        -4.01%       -7.90%     -3.89     2705
    soccer     -2.93%       -8.76%     -5.83     8193
    NCAAF      -3.33%      -14.46%    -11.13     1666

**Baseball is the exception, not the rule.** Generalising "take the underdog"
from MLB would lose 14.5 cents on the dollar in college football, and the
worst bucket in the whole study is NCAAF long dogs at +250 or worse:
**-22.49% over 834 games.** Soccer's equivalent bucket is -11.37% over 9,206.

The mechanism is consistent once the sports are lined up by scoring shape.
Where a longshot is genuinely hopeless — NCAAF dogs at +250 win 14.7% of the
time, soccer's win 20.2% — the public buys the lottery ticket anyway, and the
book prices the appetite rather than the probability. Where the "longshot" is
not really long, because the sport is low-scoring and the odds stay
compressed, dogs win often enough to be underpriced. Hockey and baseball sit
at that end; college football sits at the other, and basketball follows the
football pattern.

Worth being straight about the statistics. The best-powered findings are the
negative ones — soccer -5.83 at 3.4 standard errors, NCAAF -11.13 at 3.2 —
and those are the ones that protect money. The positive ones are weaker:
WNBA +11.07 is 1.9 s.e. on 620 games, NHL +4.01 is 1.5. So the confident
instruction is "do not buy the taxed longshots", and the speculative one is
"the hockey and women's-basketball dogs look cheap".

Per-league soccer numbers were computed too and are deliberately NOT used:
they range from EPL favourites at -16.99% to EFL League One favourites at
+15.83%, but on 150-480 matches each with ROI standard errors near 10 points,
that spread is mostly noise. Pooling is the honest read.

## Shipped

Every underdog leg now carries a chip cut from its own sport's table:
**VALUE** in MLB, NHL and the WNBA; **TAXED** in college football, the NBA,
the NFL, and on soccer dogs priced +250 or longer. Tennis has no prices on
this feed, so it carries no chip.

This is the second finding in a row that is about the price rather than the
game — and the first one that would have done real damage if it had been
generalised on instinct instead of measured.

## The badge audit: why "solid" was losing

Sky asked the obvious question — how is a leg labelled *strong* or *solid*
still losing? Pulling the ledger apart answered it, and the answer was not
variance.

116 settled picks, split by the tier each one was wearing:

```
sport   tier      n  won  actual    said     gap    +-
tennis  strong   42   36   85.7%   80.8%   +4.9    7.7
tennis  solid    17   13   76.5%   67.5%   +8.9   12.1
tennis  lean     12    7   58.3%   60.5%   -2.2   14.4
tennis  coin     17    9   52.9%   53.3%   -0.3   12.1
mlb     solid     4    3   75.0%   63.5%  +11.5   25.0
mlb     lean      7    3   42.9%   58.3%  -15.4   18.9
mlb     thin     16    8   50.0%   52.7%   -2.7   12.5
```

Tennis is not the problem. Both of its top tiers beat what they claimed.
By league: WTA 76.0% over 50, ATP 71.1% over 38, **MLB 51.9% over 27**.

The defect was that "solid" was defined per sport on the model's own
confidence scale, and those scales are not the same thing. Tennis needed 72%
to earn the word. MLB needed 61% — against a model that tops out at 66%. So
the same badge was being handed to a 76.5% pick and to a coin flip.

### MLB moneyline produces no independent information

Worse than mislabelled — the MLB model is a favourite-follower that adds
nothing over the price it is standing next to:

```
I took the book favourite   n=25  won 52.0%   book implied 58.9%   ROI -12.30%
blind "always book favourite" on the same 27 games:  51.9%
my model on the same 27 games:                       51.9%
```

Identical. It picks the book's side 25 times in 27. Its own confidence
carries nothing within the sport (under 57%: 50.0%, over 57%: 54.5%, ±13),
and the games where it claimed the biggest edge over the price won 50.0%.

Brier over those 27: model 0.2452, de-vigged book 0.2467, coin flip 0.2500.
Nobody — the book included — has demonstrated a read on this sample. Swapping
to a market-anchored number would not have helped, so it was not done.

### What shipped

Nothing was removed from the board. The full slate stays; the labels stopped
lying about it.

1. **A badge now means one thing everywhere.** Tiers are cut on the MEASURED
   hit rate, not on a per-sport confidence scale: 75% earns *strong*, 65%
   *solid*, 57% *lean*, 53% *thin*, below that *coin flip*.
2. **The backtest is a prior, not a verdict.** Every settled pick updates its
   band, weighted at `PRIOR_N = 40` backtest games per live game, so a band
   that stops working stops advertising. Tennis's top band has climbed
   0.784 → 0.821 on 36/42 live; MLB's has fallen 0.596 → 0.610 on n=4 and its
   two lower bands to 0.557 and 0.536.
3. **Every MLB leg that said *solid* now says *lean* or *thin*.** 17 legs
   moved down a tier; not one left the board.
4. **The card ranks by measured rate**, and prints the sample size behind it,
   so a number can be argued with instead of trusted.

The honest state of play: tennis at 64%+ is the part of this board that has
earned money. MLB moneyline has not, and now says so on its face.

## The unranked-opponent hole

Tennis confidence is built from the two rankings. When the opponent is
unranked the model has nothing to work from and substitutes a default — so
the number it prints there is manufactured, not measured. The ledger shows it
clearly. Holding the claimed confidence almost fixed at 72-84%:

```
                        n   won   actual    said
opponent RANKED        17    16    94.1%   77.4%
opponent UNRANKED      14     9    64.3%   78.7%
```

Near-identical claims, a 29.8-point gap in what they delivered. Across all 90
settled tennis picks the calibration error flips sign with it: +5.3 when the
opponent is ranked, −3.4 when they are not. Five of the six losses in the
whole 72%+ tier came against an unranked opponent.

At 1.65 standard errors this is suggestive, not proven, and the historical
sample cannot settle it — the archived backtest carries no point-in-time
rankings, only names and results, so testing it there would mean scoring past
matches with today's ranking list. That is look-ahead contamination and it
was not done.

So no penalty was hard-coded. The band was **split** instead, and each half
now earns its own rate off the record: 72%+ against a ranked opponent sits at
0.847 (22/23 live), against an unranked one at 0.769 (14/19). The gap widens
only as fast as the evidence supports, and both halves stay on the board.

## The arithmetic nobody wants to hear

The best single leg this board has ever produced measures in the mid-80s.
Ranked in order, a card of the strongest available legs runs:

```
1 leg  84.7%      4 legs 51.5%      8 legs 26.5%
2 legs 71.7%      5 legs 43.6%     14 legs  9.8%
```

Four legs is where it crosses a coin flip. No amount of model work changes
that — 0.847^4 is 51.5% however good the picks are. The card now leads with
1-2-3-4 rather than starting at 5, because that is the range where the board's
edge survives contact with the multiplication.
