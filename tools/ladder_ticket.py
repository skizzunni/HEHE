"""Today's ladder ticket as plain lines, straight from ladder.report(), for the
8 AM message: run, stake, each leg (price, chance, game, start ET, what it
needs in plain words, the record of Locks like it), the 2x-5x pick against the
plain top 4 and the no-props option, and wins still needed. Every number comes
from the report; nothing is computed that the board does not already state.

    python tools/ladder_ticket.py
"""
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def needs(label):
    """What a leg needs, in plain words (the board's needLine, in Python)."""
    lab = str(label or "")
    unit = "goals" if re.search(r"goal", lab, re.I) else "runs" if re.search(r"\brun", lab, re.I) else "points"
    m = re.match(r"^(.+?):\s*(\d+(?:\.\d+)?)\+\s+(.+)$", lab)                     # "Franz Wagner: 6+ Assists"
    if m:
        return f"{m.group(1)} gets {m.group(2)} or more {m.group(3).lower()}"
    m = re.match(r"^(.+?)\s+(under|over)\s+([\d.]+)\s+\w+", lab, re.I)              # a team total
    if m and m.group(1).lower() not in ("over", "under"):
        x = float(m.group(3))
        return f"{m.group(1)} scores " + (f"{math.floor(x)} or fewer" if m.group(2).lower() == "under"
                                          else f"{math.ceil(x)} or more") + f" {unit}"
    m = re.match(r"^(Over|Under)\s+([\d.]+)", lab, re.I)
    if m:
        x = float(m.group(2))
        return "both teams together score " + (f"{math.floor(x)} or fewer" if m.group(1).lower() == "under"
                                               else f"{math.ceil(x)} or more") + f" {unit}"
    m = re.match(r"^(.+?)\s+([+-])([\d.]+)$", lab)                                   # a spread
    if m:
        x = float(m.group(3))
        return (f"{m.group(1)} wins by {math.ceil(x)} or more" if m.group(2) == "-"
                else f"{m.group(1)} wins or loses by {math.floor(x)} or fewer")
    m = re.match(r"^(.+?)\s+to win$", lab, re.I)
    if m:
        return f"{m.group(1)} wins outright"
    m = re.match(r"^(.+?)\s+or draw$", lab, re.I)
    if m:
        return f"{m.group(1)} wins or draws"
    return lab


def lines(R):
    """The ticket as a list of strings; [] when there is no ticket today."""
    T = (R or {}).get("today") or {}
    if not T.get("legs"):
        return []
    out = [f"Run {R.get('runs')}, stake ${T['stake']:.2f} (the whole bank) on {len(T['legs'])} legs at "
           f"{T['pays']:.2f}x -> ${T['stake'] * T['pays']:.2f}; {round(100 * T['prob'])}% est. all win."]
    for i, L in enumerate(T["legs"], 1):
        rec = L.get("kind_rec") or {}
        pr = L.get("prop_rec") or {}
        outs = "; ".join(f"{t} without {', '.join(p)}" for t, p in (L.get("outs") or {}).items())
        out.append(f"{i}. {L['label']} {L['price']} ({round(100 * L['p'])}%) -- {L.get('match')}, {L.get('lg')} "
                   f"{L.get('tip')} ET. Needs: {needs(L['label'])}."
                   + (f" Locks like it: {rec['won']} of {rec['n']}." if rec.get("n") else "")
                   + (f" Every {str(L.get('league') or '').upper()} {L.get('market')} line at a similar chance: "
                      f"{pr['won']} of {pr['n']} ({round(100 * pr['won'] / pr['n'])}% vs {pr['said']}% stated)." if pr.get("n") else "")
                   + (f" Out: {outs}." if outs else ""))
    v = T.get("vs_top4") or {}
    if v:
        out.append(f"Plain top 4 instead: {round(100 * v['prob'])}% at {v['pays']:.2f}x.")
    npr = T.get("no_props")
    if npr and any(L.get("kind") == "prop" for L in T["legs"]):
        out.append(f"Without props: {npr['n']} legs at {npr['pays']:.2f}x, {round(100 * npr['prob'])}% "
                   f"({', '.join(npr.get('labels') or [])}).")
    if R.get("wins_needed"):
        out.append(f"{R['wins_needed']} straight wins at this price reach the target"
                   + (f", about 1 in {round(1 / R['chance_to_target']):,}." if R.get("chance_to_target") else "."))
    return out


if __name__ == "__main__":
    import ladder
    print("\n".join(lines(ladder.report())) or "No ladder ticket today yet.")
