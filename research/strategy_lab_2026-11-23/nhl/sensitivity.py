"""Sensitivity checks for the two on-watch strategies (re-runs analyze.py's
state build by importing it, then re-slices its bet lists)."""
import sys, collections, io, contextlib
sys.argv = ["analyze.py", "games.json", "raw/box.json"]
with contextlib.redirect_stdout(io.StringIO()):
    import analyze as A
def line(name, rows):
    by = {s: A.stats([r for r in rows if r[0] == s]) for s in A.SEAS}
    h1 = A.stats([r for r in rows if r[0] in (2022, 2023)]); h2 = A.stats([r for r in rows if r[0] in (2024, 2025)])
    print(f"{name:45s} " + " ".join(f"{s%100}:{by[s]['n']}/{by[s]['roi']*100:+.1f}%" for s in A.SEAS)
          + f" | z H1 {h1['z']:+.2f} H2 {h2['z']:+.2f}")
