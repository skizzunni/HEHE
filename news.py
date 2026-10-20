"""News and lineup gates for the day's calls (calls.update_daily).

What has to be confirmed before a called game's price can be trusted, read
from ESPN's scoreboard (probables, with their status) and game summary
(rosters with starters, the injury report):

    NHL      both starting goalies CONFIRMED -- "Expected"/"Probable" is not
    MLB      both starting pitchers confirmed and both lineups posted
    NBA      the latest injury report, checked this build
    soccer   both starting XIs posted (ESPN posts them about an hour out)
    tennis   never a call (no sportsbook price: README item 2)

status() gives (confirmed, what is missing or confirmed, fingerprint). The
fingerprint covers everything the gate reads plus the injury list, so any
change -- a goalie confirmed or swapped, a lineup posted, a player added to
the injury report -- is NEWS. On news, the league's calls freeze (no top-up,
no re-derivation) until a price captured after the news exists; then any call
whose market chance moved more than MOVE_PTS from its published chance is
re-derived at the new chance, or pulled if its side is no longer the
favourite. Every such decision is logged on the call in calls.json.
"""
import hashlib
import json

MOVE_PTS = 3.0


def _ab(x):
    return ((x.get("team") or {}).get("abbreviation") or x.get("homeAway") or "?")


def _probables(row):
    """[(team, role, name, status type)] from the board row's competitors."""
    out = []
    for x in ((row.get("comp") or {}).get("competitors") or []):
        for p in x.get("probables") or []:
            out.append((_ab(x), p.get("name") or "", (p.get("athlete") or {}).get("displayName") or "",
                        ((p.get("status") or {}).get("type") or "").lower()))
    return out


def _starters(sm):
    """{team: [starter names]} from the summary's rosters."""
    out = {}
    for t in (sm or {}).get("rosters") or []:
        out[_ab(t)] = sorted((p.get("athlete") or {}).get("displayName") or "" for p in t.get("roster") or []
                             if p.get("starter"))
    return out


def _injuries(sm):
    return sorted([_ab(t), (i.get("athlete") or {}).get("displayName") or "", (i.get("status") or "")]
                  for t in (sm or {}).get("injuries") or [] for i in t.get("injuries") or [])


def _gate(league, row, sm):
    import ledger
    pr, st = _probables(row), _starters(sm)
    if league == "nhl":
        g = [p for p in pr if "goalie" in p[1].lower()]
        conf = [p for p in g if p[3] == "confirmed"]
        if len({p[0] for p in conf}) >= 2:
            return True, "both goalies confirmed"
        return False, "awaiting confirmed goalies" + (f" ({len(conf)} of 2)" if g else "")
    if league == "mlb":
        sp = {p[0] for p in pr if "pitcher" in p[1].lower() and p[3] == "confirmed"}
        lu = [t for t, v in st.items() if len(v) >= 9]
        if len(sp) >= 2 and len(lu) >= 2:
            return True, "starters confirmed, lineups posted"
        return False, "awaiting " + " and ".join(x for x, ok in (("confirmed starters", len(sp) >= 2),
                                                                  ("lineups", len(lu) >= 2)) if not ok)
    if league == "nba" or league == "wnba":
        if sm is None:
            return False, "injury report not fetched"
        return True, f"injury report checked ({len(_injuries(sm))} listed)"
    if league in ("atp", "wta"):
        return False, "tennis is never a call"
    if league in ledger.SOCCER:
        xi = [t for t, v in st.items() if len(v) >= 11]
        if len(xi) >= 2:
            return True, "both XIs confirmed"
        return False, "awaiting confirmed XIs"
    return True, "no lineup gate for this league"


def status(league, row, sm):
    """(confirmed, what, fingerprint) for one game."""
    ok, what = _gate(league, row, sm)
    fp = hashlib.sha1(json.dumps([_probables(row), _starters(sm), _injuries(sm)],
                                 sort_keys=True).encode()).hexdigest()[:12]
    return ok, what, fp


def summary(league, gid):
    """ESPN's game summary for a board game id (cached 10 minutes)."""
    import participation
    return participation._summary(league, gid.split(":", 1)[1])
