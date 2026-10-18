# Master checklist

Every requirement from the conversation, its state, and the evidence. A line
is **done** only with evidence that can be re-checked; **open** lines name
what is missing and the next step. Updated 2026-10-18.

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
| O3b | "Winners I can parlay together and still win" (added 2026-10-18) | done (display) | Safe Locks legs 93-95% each, backed by 92-95c legs winning 93.2% and 95-98c winning 96.7%; the card now names the **Winners parlay** (largest top-N slice at 80%+ all-hit) and the Best play (50%+) | live check: Winners parlay hit rate vs its stated chance, tracked from the Safe Locks record |
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

* `tests/test_core.py` -- 17 unit tests (standard library, no network): Locks -400..-120 and
  Safe -2000..-500 windows, one leg per game and the kind cap, soccer limited to validated
  kinds, soccer grading (draw / void / live), soccer name matching and the reversed-fixture
  guard, NFL upper tail, wind scaling, ungradable props kept off tickets, every FanDuel prop
  name gradable, Kalshi bot refuses tickets without a provably fresh build time, bot in practice mode.
* `tests/ui_check.py` -- the real page in headless Chrome: stale banner on every tab when 20+
  minutes old and absent when fresh; Locks -> Safe Locks renders 11 legs, the Winners parlay
  (top 4, 80%) and Best play (top 10, 54%).
* `tests/mutation_check.py` -- breaks 7 protected rules one at a time (bytecode cache off) and
  requires each to be caught; 7/7 caught 2026-10-18.

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
| 10-18 | Kalshi bot would use tickets with no build time | age check skipped when `built` missing; bad timestamp would crash | `board_age()` treats missing/unreadable as stale; unit-tested |
