# Master checklist

Every requirement from the conversation, its state, and the evidence. A line
is **done** only with evidence that can be re-checked; **open** lines name
what is missing and the next step. Updated 2026-10-18 (after the external review).

## Standing rules (never change without the owner)

| # | Rule | State | Evidence / where enforced |
|---|------|-------|---------------------------|
| S1 | Website is the deliverable; no daily reports in chat | done | `board.yml` rebuilds every 5 min; daily review is written to `review/` and shown on the site |
| S1b | Rebuild chain survives a failed hand-off | done | 100-run audit 2026-10-18: 68 successes in 6 h, longest gap 5.2 min, 0 failed builds. Hand-off now retries 6x with backoff (cron backstop is throttled to 100-270 min); run 1287 on the change handed off to 1288 at exactly +5:07 |
| S2 | Never fabricate numbers; every chance is the market's or a tested model's | done | `locks._market_p`, `lottery.market_chance`, labs score on unseen halves |
| S3 | Locks: 11 FanDuel legs, card set 8 AM ET, games after 8 AM, -400 to -120 | done | `locks.py` `DEC_MIN/DEC_MAX`, `CARD_HOUR`, `_eligible`; unchanged by Safe Locks |
| S4 | Keys never in chat; bot stays in practice mode until owner runs `touch ~/.hehe-bot/LIVE` | done | bot code unchanged; nothing remote can switch it |
| S5 | No geo workarounds for Kalshi | done | bot runs only on the owner's Mac |

## Objectives

| # | Objective | State | Evidence | Next step |
|---|-----------|-------|----------|-----------|
| O1 | Higher win % without faking | ongoing | picks 185-70 (72.5% vs 70.9% said), strong calls 102-26 (79.7%) on 2026-10-17 review | weekly labs; act only on both-halves results |
| O2 | Better 10-leg tickets | done (backtest) | NFL totals split normal: backtest NFL 10-leg 7/29 -> 18/29; all NFL markets within 2 SE | confirm on live NFL Sundays (scheduled review 2026-10-19 05:30 UTC) |
| O3 | Locks that "all win" | partly | regular card is ~8% all-hit by arithmetic (replay 7.7% vs 7.2%); **Safe Locks** (-2000 to -500) added: 90-100c legs won 92.0% vs 93.1c; replays show all-hit at or above stated | first live Safe Locks results (scheduled review) |
| O3b | "Winners I can parlay together and still win" (added 2026-10-18) | done (display) | Safe Locks legs 93-95% each, backed by 92-95c legs winning 93.2% and 95-98c winning 96.7%; the card now names the **Winners parlay** (largest top-N slice at 80%+ all-hit) and the Best play (50%+) | **tracked** (2026-10-18): each card's Winners parlay and Best play are graded as the exact slice shown (`locks.plays`, voids drop off as at FanDuel) and the record shows hit rate vs promised. Regular Locks so far: Winners parlay 1/1 (80% promised), Best play 1/3 (64%) -- far too few days to judge. Replay of Safe-style cards on 11 past days (Kalshi-settled legs -500..-2000, one per game, top 11, 2026-09-05..10-11): Winners parlay hit 9/11 (82%) vs 82% stated, avg 6.8 legs; Best play 7/11 vs 66% -- consistent with the stated chance, sample small | compare at 20+ settled days per card |
| O4 | Bigger, better leg pool | done | soccer added to Locks/Safe Locks from FanDuel's soccer page, limited to the result and double chance (the two the soccer lab validated). Live run 2026-10-18 02:36 UTC matched every listed game in EPL 4/4, La Liga 4/4, Ligue 1 5/5, Bundesliga 2/2, Austria 3/3, Scotland, MLS, South Africa; Safe Locks took "Cruz Azul or draw" -1500. Grading tested offline: draw, away double chance, void, live | first soccer legs settle Sunday; unmatched rows are games FanDuel does not list (Colombia, Uruguay, NWSL) |
| O5 | Props fixed | done | ungradable markets removed from locks/tickets/mega; every FanDuel prop name gradable (checked NFL/NBA/WNBA/NHL/MLB) | first NFL props grade Sunday |
| O6 | NFL TD scorers, every game, realistic | done (NFL) | 12 games logged; chances sum to the total's expected TDs | TD lab at 20 graded games |
| O6b | College TD scorers | **blocked (regulatory)** | probe 34: Nebraska @ Oregon 15 min before kickoff had no touchdown market on FanDuel NY at all (4 receiving props only). New York bars player props on college games; another state's feed would be geo-routing, which the rules forbid; inventing chances without prices breaks S2 | lifts only if NY allows college player props |
| O7 | UFC fixed | done | UFC lab, 613 fights: market price calibrated (67.6/67.8% favourites won), no method beat it on unseen fights | weekly lab |
| O8 | No bad combo legs (Purdue) | done | combo-safe filter (>=90%) on the page | - |
| O9 | Site lag | done | no reload while in use; view restored | - |
| O10 | Every split studied | ongoing | labs: totals, NHL, UFC, soccer, TD, ladder, edge, backtest, weather; daily audit flags splits >2 SE behind | ladder lab needs ~30 graded games |

## Regression tests

Run by `.github/workflows/tests.yml` on every code or page push:

* `tests/test_core.py` -- 52 unit tests (standard library, no network): Locks -400..-120 and
  Safe -2000..-500 windows, one leg per game and the kind cap, soccer limited to validated
  kinds, soccer grading (draw / void / live), soccer name matching and the reversed-fixture
  guard, NFL upper tail, wind scaling, ungradable props kept off tickets, every FanDuel prop
  name gradable, Kalshi bot refuses tickets without a provably fresh build time, bot in practice mode,
  practice tickets settle on partial/never-finished markets, UFC clock fallback, stuck-record sweep,
  soccer shots off in every soccer league, build integrity check.
* `tests/ui_check.py` -- the real page in headless Chrome: stale banner on every tab when 20+
  minutes old and absent when fresh; Locks -> Safe Locks renders 11 legs, the Winners parlay
  (top 4, 80%) and Best play (top 10, 54%); Results health box lists a trailing split, a
  never-settled record and bad data, and reads "All checks passing" when clean.
* `tests/mutation_check.py` -- breaks 38 protected rules one at a time (bytecode cache off) and
  requires each to be caught; 38/38 caught 2026-10-18.

## Monitoring (on the site, every build)

* Results tab **Checks** box: splits trailing their stated chance by 2+ SE (daily audit, only markets
  still offered), records open 6+ days (stuck sweep), and bad values in the build (integrity check:
  chances outside 0-1, unparseable prices, missing names, None/nan in text). Live payload: 0 issues.
* Stale banner on every tab when the page is 20+ minutes old.

## Out of scope

* Job-search system: dropped by the owner (2026-10-18). Not part of this project.

## Tested and rejected (do not retry without new data)

Hockey empty-net shift (halves disagree), tennis stretch (older-half streak),
UFC power de-vig / stretch (no gain on unseen fights), NFL weight shrink
(halves disagree), NCAAF under correction (not significant, symmetric in 2025),
drift/form/rest/travel/team bias, Kalshi+book average.

## Pre-game verification of Sunday 2026-10-18 (read from the live site, 12:01 AM ET build)

* Regular Locks preview: 11 legs from 41 available games, all -370..-400, 4 NFL unders (cap), soccer leg "Monaco or draw"; all-hit 6.6%.
* Safe Locks preview: 11 legs from 24 games, all -1800..-2000, 4 NFL unders (cap), "Real Madrid or draw"; all-hit 52.8%, Winners parlay top 4 at 81%.
* Props: 2,005 across 35 games; 94 ticket legs, 0 ungradable. 24 NFL TD picks (2 x 12 games) and 59 NFL props recorded in props.json, 0 ungradable.
* 10-leg stack: all soccer legs at 97%; backtest 95-100% soccer stack legs said ~97.4, hit 97.1-98.8 (3,100+ legs). Watch: Ligue 1 legs 95.2 vs 97.4 on 393.

## Checked and left alone (2026-10-18)

* Props at Locks prices: 155 graded; 70-80% band hit 74.4 vs 73.4 said; 80-90% band 78.4 vs 84.7, but the
  whole gap is soccer "Shots" (uel 8/20 vs 84%), already off. Without it the band hits ~90 vs ~85 (NHL shots
  on goal 41/47 vs 84.8). No change to prop chances.

## Selection pipeline (2026-10-19)

One path from candidates to the recommended card, each step tested or plainly marked as a
correctness fix (not an accuracy claim). Rule for any change to what is picked
(`tools/paired.py`, run every build, shown on Results -> "Changes tested"): the same candidates,
the same number of picks, the same price window and pregame inputs, scored on later games
neither chooser was designed on. It lists both directions (new right / old wrong and the
reverse) and is promoted only if the day-bootstrap 95% range of the difference is above zero.
Pregame inputs beyond the price need a net gain of two standard errors on the lab's untouched half.

| Step | What changed | Evidence / regression case |
|------|--------------|----------------------------|
| Policy | `policy.py` is the only source of model weights and pregame shifts; hand-set NFL/WNBA 0.30, MLB 0.20, tennis 0.05 and the review's 0.20 fallback removed | Atlanta: market Chicago 51.7%, model Atlanta 56.4%, published Atlanta 50.7% on the hand-set 0.30 (lost); tested policy picks Chicago. Paired, untouched half: market-only 320 vs published 305 wins on 476 games (53 vs 38 discordant), range -6..+42: **not proven better** -- the market is the baseline and the overrides were never promoted. By league: NCAAF +17, NHL +6, MLB -3, NFL -1, WNBA -4 (22 games) |
| Qualification | strong calls only where a record qualified; soccer qualifies as one group by the same test, no defaults | soccer: 530 graded picks qualify at 70% (184 calls, 76.6%, both halves); NBA / college basketball no longer get 60% without a record |
| Participation | props recommended only for players confirmed to play (soccer and saves: ESPN lineup lists a starter; others: not on the injury report) | goalkeeper backups: 25 of 57 recorded keeper props voided; the 2026-10-17/18 DraftKings Lottery tickets carried five (Huth, Leroy, Batz, McGill, dos Santos) |
| One probability | the Card prices, ranks and sweeps on the published chance; the band's past rate is history only; Card rows carry the game id | a 72.2% tennis pick was priced at 81.7% |
| Pregame inputs | edge lab's significance fixed to 2 SE (it was 1); home edge via `policy.home_edge`; wind nudge needs 2 SE on the untouched half | NCAAF home edge: 12-7 on 19 changed picks (+1 later) -> off; wind: 1.6 SE / 0.9 SE -> off. No input beyond the price is promoted today |
| Ties | ties break by a fixed order; legs within a price's uncertainty of the first leg left out are tagged "tied at the cut" | Colts +1.5 75.73% vs Under 46.5 75.65% (Colts lost). Ranking by chance minus uncertainty: -1 on 11-leg cards, range incl. 0 -> not used |
| Lottery | finishing leg = likeliest line of any unused game reaching the payout; candidates + policy archived and replayed each build; voided tickets keep a 'settled' record | archived 10-18 ticket needed x1.70 and took a 2.35 leg at 41% (paid 13,846). Stored tickets never changed after recording (78 revisions checked) |
| Recommended card | only qualified picks; none is a valid answer; all forecasts still listed | -- |
| Archive | each pick version stores both prices, market and model chances, the weight, the policy fingerprint and the commit; Locks and Lottery store their full candidate pools | Locks 10-18 replay exact under its own chooser version |

Not promoted / open: no pregame input beats the same-time price yet; the hand-set Card tiers ("lock"
badges) are descriptive only; the WNBA weight did better on its 22 newer games (+4) but lost on the
older half -- it must win a fresh paired test before it returns.

## External review 2026-10-18 (snapshot 34ff1f3): findings and what was done

| # | Finding | State | Evidence |
|---|---------|-------|----------|
| 1 | Props voided / ungradable by name and MLB-group bugs | **fixed + reconciled** | Accents folded, FanDuel team tag used as a hint, surname + compatible first name (Mitchell/Mitch); an unmatched name stays open for retry (`unresolved`) and is never graded as a DNP; MLB groups read from `type`. Regraded against ESPN: Aho (CAR) 0 shots **lost**, Stützle 1 **won**, Marner 1 **lost**; the 8 MLB props **6 won, 2 lost** -- exactly the review's figures, confirmed in the live ledger after the pipeline re-checked all 65 past void/ungradable records once |
| 2 | Integer-line pushes graded as losses | **fixed** | `stacks.settle_score` -> won/lost/push; Under/Over 44 at 24-20 and Home -3 at 24-21 push; a push leaves the slip (stored as void + `push`); used by Locks, Safe Locks, Stacks, Lottery and the backtest. Past ledgers scanned: 0 such losses (nearly every line was a half point) |
| 3 | Recommendations overwritten; ML price kept on a double-chance call | **fixed** | Append-only `history` per pick (time, pick, market, price, chance, reason, strong label, commit); `first` = call as first published; team+market is the bet identity; no revision after the scheduled start; 3 contaminated first prices cleared (kept as `first_price_cleared`) |
| 4 | Same-game legs multiplied as independent | **fixed (owner's rule)** | Owner chose: at most one leg per game per ticket, up to 11; light days show fewer at the same standards; other same-game ideas listed apart and excluded from chance, payout, Winners parlay, Best play; never recorded. Also Stacks (no same-game fill) and the 25-leg props ticket. Live 08:26 UTC: tomorrow's Locks 6 legs / 6 games (was 10 / 6), Safe 3 / 3 (was 7 / 3) |
| 5 | Objective implicit; "best" not best value | **partly** | Each card states it maximises the chance of winning, not value, and shows the estimated return (chance x payout - 1) for the Winners parlay, Best play and full card; no Winners parlay named when nothing reaches 80%. A separate value mode is not built (no validated edge exists to build it on) |
| 6 | Price-band calibration jumps, breaks complements | **fixed** | Tested by date halves on the Kalshi legs (204 games, 32 dates, no game in both halves): the band factor (even in-sample) and a smooth logit stretch both failed to beat the plain price out of sample (stretch b 0.91 vs 1.20; gain CI -0.006..-0.002). Chances are now the de-vigged price: monotone and complement-preserving by construction; unit-tested |
| 7 | Single-side 1.045 de-vig on game lines | **fixed** | `locks.two_sided`: FanDuel's price de-vigged against its own opposite side (over/under, spread +/-, team totals, dc vs win, 2-way ML); fallback marked `assumed margin`. Live: 10/11, 6/6, 11/11, 2/3 legs two-sided. Nested alternate lines pooled into order (PAV) |
| 8 | Strong-call record measured a re-scored policy; fallback cut-offs | **fixed** | Cut-offs fitted on published chances; no fallback (unqualified leagues get no strong calls); label frozen at publication; holdout on published picks with a date-boundary split: 75.6% on 283 calls over 18 days (simulated market-favourite version kept apart, 69.5% of all) |
| 9 | Stacks aim chosen on the "unseen" half | **fixed** | Holdout days split again: aims chosen on `select` days only, `test` days reported. Until the next weekly backtest the fixed default aims apply |
| 10 | Weight fit on legacy rows; no true market-only | **fixed** | Fit only on rows with the saved raw model/market pair (NCAAF 52, NHL 17; MLB/NFL had 0); grid includes 0; a weight above 0 needs a gain on the newer half it was not fitted on. Result today: NCAAF fitted 0.35 but did not hold -> 0 (market only) |
| 11 | Rows treated as independent; ROI interval mismatched | **fixed** | `tools/resample.py`: stake-weighted ROI with a bootstrap over whole games; Kalshi backtest splits by date. Lottery legs ROI -11.8%, CI -44..+22 on 71 games (honestly wide) |
| 12 | Freshness, fixture matching, Card consistency | **fixed** | FanDuel match by teams + nearest start within 3 h (doubleheaders), ambiguous -> no match; `dashboard.pregame` drops anything past its start whatever a cached status says; old scoreboards listed in Checks; Card sweep/top-3 follow the table's order; soccer marked "market est."; "floor" wording removed, every chance labelled est. |
| -- | Replay = live chooser | **done (Locks)** | The pool each card was chosen from is saved; each build re-runs `choose()` on it and flags any mismatch. Stacks' backtest already calls the live `candidates`/`build_tickets` |

Still open from the review: a value mode with a margin for error; per-market venue rules for Kalshi
contracts that settle differently from a sportsbook line (Kalshi lines in the data are half points,
so no case exists yet); props de-vig uses each market's tuned margin rather than a paired opposite where
FanDuel lists only one side.

## Sunday 2026-10-18 8 AM cards (checked 12:20 UTC)

* Both cards set at 12:02 UTC (8:02 AM ET), the first under the one-leg-per-game rule: Locks 11 legs / 11
  games, all -360..-400; Safe Locks 11 / 11, all -1800..-2000, one soccer leg ("Real Madrid or draw", dc).
  Earliest start 9:30 AM ET (Jaguars, London). Kind cap held (4 NFL unders each).
* Decision-time pools saved; the chooser re-run on them gives both cards exactly (replay True).
* 30 NFL touchdown props recorded across 12 games. Tests green on the latest code (run 20, 95638d7).

## First live Safe Locks card (2026-10-17), graded 2026-10-18 07:15 UTC

* **11/11 won, all hit** (stated 49.8%). Winners parlay top 4 (80%) hit; Best play top 10 (54%) hit.
* Every leg checked by hand against its final score, and the scores agree with ledger.json's own pick
  results (Utah 27-24, Oregon 17-14, Fresno State 23-26 loss, New Mexico 21-10, Wake Forest 41-7, Cruz Azul 5-0).
  None stuck open. Chain: 12 commits in the hour before the check, last build 07:13 UTC.
* One card is one draw from a ~50% event: it shows the grading works, not that the stated chance is too low.

## Waiting on data

* NCAAB unders lean (one season only) -> recheck November.
* NFL far overs vs far unders at the same FanDuel price -> `ladder_lab` (logging since 2026-10-18).
* Soccer totals / team totals / handicaps -> not on any card until tested.

## Failures and fixes

| When | What failed | Root cause | Fix |
|------|-------------|------------|-----|
| 10-18 | ladder-lab workflow failed | lab exited without writing its result; commit step had nothing to add | labs always write a result (ladder, TD) |
| 10-18 | first soccer run found no FanDuel games | FanDuel cache (10 min) written by the old code | next run refetched; soccer present |
| 10-18 | derby test matched reversed fixture | 0.5/0.5 token scores both ways | swap guard rejects reversed fixtures |
| 10-18 | NFL test failed after an unrelated change | stale .pyc: a same-length mutation restored within the same second kept running | mutation checks run with -B / PYTHONDONTWRITEBYTECODE; cache never committed |
| 10-18 | page gave no warning when out of date outside Results | staleness shown only in the in-play list | page-wide banner at 20+ minutes, browser-tested |
| 10-18 | UFC "goes the distance" prop (-1200) stuck open, would void after 3 days | grader waited for ESPN's result line, which arrives late or never | settles from final round + clock when the line is missing; live: settled **won** (ended 5.78 min); unit + mutation tested |
| 10-18 | bot reported "open-position limit reached" | an Oct 16 practice ticket on a never-finished MLB game held a slot forever | partial settlement read; practice tickets expire after 4 days; unit + mutation tested |
| 10-18 | health box flagged "props uel Shots" trailing | audit counted a market already switched off | audit ignores markets no longer offered, and the build drops such alarms at once (review log is daily); shots off in every soccer league |
| 10-18 | the Winners parlay the page tells you to play had no record | record graded only legs and all-11 days | `locks.plays` grades the named slices; record table + summary on the page; unit, browser and mutation tested |
| 10-18 | integrity check first flagged 253 prices | Kalshi prices are dollars (0-1), not American odds | `.kalshi.` paths checked as 0-1; live payload clean |
| 10-18 | Kalshi bot would use tickets with no build time | age check skipped when `built` missing; bad timestamp would crash | `board_age()` treats missing/unreadable as stale; unit-tested |
