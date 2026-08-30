"""Data audit: sanity-check every transcribed price before trusting the picks."""
from parlay_math import american_to_decimal
from mlb_sunday import GAMES, devig

print("=" * 94)
print("TRANSCRIPTION AUDIT -- 12 games")
print("=" * 94)
bad = 0
for a, asp, aml, h, hsp, hml, rlf, fav_rl, dog_rl, tot, t in GAMES:
    ml_o = 1/american_to_decimal(aml) + 1/american_to_decimal(hml)
    rl_o = 1/american_to_decimal(fav_rl) + 1/american_to_decimal(dog_rl)
    flags = []
    # A two-way book market lands between 2% and 9% overround. Outside that
    # means a mistyped price, not a generous book.
    if not (1.02 <= ml_o <= 1.09):
        flags.append(f"ML overround {ml_o:.4f} IMPLAUSIBLE"); bad += 1
    if not (1.02 <= rl_o <= 1.09):
        flags.append(f"RL overround {rl_o:.4f} IMPLAUSIBLE"); bad += 1
    # The -1.5 side must be the shorter ML price, or the run-line favorite
    # was tagged on the wrong team.
    pa, ph, _ = devig(aml, hml)
    fav_is_away = (rlf == "a")
    ml_fav_away = pa > ph
    if pa != ph and fav_is_away != ml_fav_away:
        flags.append("RL favorite disagrees with ML favorite"); bad += 1
    # Run-line favorite must be priced longer than its own moneyline.
    if american_to_decimal(fav_rl) <= american_to_decimal(aml if fav_is_away else hml):
        flags.append("RL price not longer than ML -- check"); bad += 1
    status = "  ".join(flags) if flags else "ok"
    print(f"  {a+' @ '+h:<32} ML {ml_o:.4f}  RL {rl_o:.4f}   {status}")

print(f"\n  {bad} problems found")

print("\n" + "=" * 94)
print("PITCHERS ON RECORD")
print("=" * 94)
for a, asp, aml, h, hsp, hml, rlf, fav_rl, dog_rl, tot, t in GAMES:
    print(f"  {t:>7}  {a:<16}{asp:<22}{h:<16}{hsp}")

print("\n" + "=" * 94)
print("MISSING FROM THE BOARD")
print("=" * 94)
have = set()
for g in GAMES:
    have.add(g[0]); have.add(g[3])
full = ["SEA Mariners","TOR Blue Jays","CWS White Sox","MIN Twins",
        "ARI Diamondbacks","SF Giants"]
for tm in full:
    print(f"  {tm:<20} no odds received")
