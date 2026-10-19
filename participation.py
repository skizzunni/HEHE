"""Will the player take part? A prop on someone who does not play can only
void, so it is never recommended on a guess.

Books list saves for every keeper in a squad, starters and backups alike: on
2026-10-17/18 the Lottery's DraftKings tickets carried five backup keepers'
saves (Huth, Leroy, Batz, McGill, dos Santos) -- all void, because a backup
keeper's line looks like the best value on the board right up to kick-off.
44% of soccer goalkeeper props recorded so far voided this way.

From ESPN's pregame game summary:

  soccer, and any saves market   ESPN's lineup lists the player as a STARTER
                                 (lineups appear about an hour before kick-off;
                                 until then: 'lineup not out', not recommended)
  every other sport              not on the injury report as Out, Doubtful,
                                 Questionable, injured reserve or suspended

Props that fail stay on the Props tab with the reason; they are kept off the
Locks, Safe Locks, Lottery and every prop ticket.
"""
import json
import os
import time

import props_ledger as PL

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "participation")
TTL = 600
OUT_STATUS = ("out", "doubtful", "questionable", "injured reserve", "ir", "suspended",
              "suspension", "not active", "inactive")


def _summary(league, eid):
    f = os.path.join(CACHE, f"{league}-{eid}.json")
    try:
        if time.time() - os.path.getmtime(f) < TTL:
            with open(f) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    sport, lg = PL.SPORT.get(league, (None, None))
    if not sport:
        return None
    try:
        d = PL._get(f"{PL.SITE}/{sport}/{lg}/summary?event={eid}")
    except Exception:
        return None
    keep = dict(rosters=d.get("rosters") or [], injuries=d.get("injuries") or [])
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(f, "w") as fh:
            json.dump(keep, fh)
    except OSError:
        pass
    return keep


def _needs_lineup(league, market):
    return league not in PL.NOT_SOCCER or "save" in (market or "").lower()


def _match(people, name):
    """The entry for `name` among [(norm name, team abbr, value)]: exact,
    then same surname + compatible first name, team tag breaking ties."""
    nm, hint = PL.norm_name(name), PL.team_hint(name)

    def one(c):
        if hint and len(c) > 1:
            c = [x for x in c if x[1] == hint]
        return c[0][2] if len(c) == 1 else None

    got = one([x for x in people if x[0] == nm])
    if got is not None:
        return got
    w = nm.split()
    if not w:
        return None
    return one([x for x in people if x[0].split()[-1:] == w[-1:]
                and PL._first_ok(x[0].split()[0], w[0])])


def status(sm, league, name, market):
    """'ok' / 'starting' (may be recommended) or the reason it may not."""
    if sm is None:
        return "no game summary"
    if _needs_lineup(league, market):
        people = []
        for t in sm.get("rosters") or []:
            ab = ((t.get("team") or {}).get("abbreviation") or "").lower()
            for p in t.get("roster") or []:
                people.append((PL.norm_name((p.get("athlete") or {}).get("displayName")), ab,
                               bool(p.get("starter"))))
        if not people:
            return "lineup not out"
        s = _match(people, name)
        if s is None:
            return "not in the squad"
        return "starting" if s else "on the bench"
    people = []
    for t in sm.get("injuries") or []:
        ab = ((t.get("team") or {}).get("abbreviation") or "").lower()
        for i in t.get("injuries") or []:
            people.append((PL.norm_name((i.get("athlete") or {}).get("displayName")), ab,
                           (i.get("status") or "").strip().lower()))
    s = _match(people, name)
    if s and any(s.startswith(x) for x in OUT_STATUS):
        return "listed " + s
    return "ok"


def annotate(games):
    """Sets P['play'] (the reason) and P['plays'] (may be recommended) on
    every prop of every game, one summary per game."""
    for g in games or []:
        league, _, eid = g["id"].partition(":")
        if league == "ufc":
            for P in g.get("props") or []:
                P["play"], P["plays"] = "ok", True     # a fight card has no lineup
            continue
        sm = _summary(league, eid)
        for P in g.get("props") or []:
            if not P.get("name") or P["name"] == "Fight":
                P["play"], P["plays"] = "ok", True
                continue
            st = status(sm, league, P["name"], P.get("market"))
            P["play"], P["plays"] = st, st in ("ok", "starting")
    return games


def eligible(P):
    """May this prop be recommended? Unannotated props are not."""
    return bool(P.get("plays"))
