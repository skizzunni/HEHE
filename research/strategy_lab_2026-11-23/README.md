# Overnight strategy lab, 2026-11-23

Scripts and result tables behind the README's 2026-11-23 strategy-lab notes:
NBA (49 rules), NHL (25), NFL + college football (51), Locks/ladder tickets and
staking, player props, soccer (364), college basketball + MLB (103). Tennis did
not finish.

Every rule uses only pre-game information and is graded at the real closing price,
season by season. Adoption needs a profit every season and z >= 2.8 in both date
halves. One rule cleared it (two props on one player in one game fail together),
and every ticket already prevents it.

The data the scripts download (ESPN odds and scores, NHL boxscores, football-data.co.uk
CSVs, Open-Meteo weather) is not committed. The scripts were run from
work/strategy_lab/<family>/, so paths may need adjusting to re-run them. These are
research only: nothing here is imported by the board.
