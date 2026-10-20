"""What was known before selection, kept with a timestamp.

The chooser today uses only the same-time market (policy.py), but any input
that might one day earn a place has to be tested on exactly what was known
before the game -- so it is collected now, never reconstructed later:

    probables   ESPN's probable starters: MLB pitchers, NHL goalies
    injuries    each team's injury report entries with status (NFL QBs among them)
    starters    confirmed lineups where ESPN posts them (soccer, about an hour out)

snapshot() returns {game id: {...}}; archive() appends a game's record to
frontier.json only when it changed, each with the time it was seen. No
closing information or result can enter: games that have started are skipped.
"""
import datetime as dt

import participation


def _probables(comp):
    out = {}
    for t in comp.get("competitors") or []:
        ab = (t.get("team") or {}).get("abbreviation") or t.get("homeAway")
        ps = [[(p.get("athlete") or {}).get("displayName"), p.get("name")]
              for p in t.get("probables") or [] if (p.get("athlete") or {}).get("displayName")]
        if ps:
            out[ab] = ps
    return out


def snapshot(slot_rows, now=None):
    """{gid: dict(start, probables, injuries, starters)} for games not yet started."""
    import dashboard
    now = now or dt.datetime.now(dt.timezone.utc)
    out = {}
    for lg, rows in (slot_rows or {}).items():
        path = dashboard.PATHS.get(lg) if hasattr(dashboard, "PATHS") else None
        for r in rows or []:
            gid = r.get("id")
            if not gid or ":" not in gid:
                continue
            st = (r.get("mkt") or {}).get("start")
            try:
                t = dt.datetime.fromisoformat(str(st).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=dt.timezone.utc)
            except (TypeError, ValueError):
                continue
            if t <= now:
                continue                           # started: nothing after this point
            rec = dict(start=st, probables=_probables(r.get("comp") or {}))
            sm = participation._summary(lg, gid.split(":", 1)[1])
            if sm:
                rec["injuries"] = [[(t_.get("team") or {}).get("abbreviation"),
                                    (i.get("athlete") or {}).get("displayName"), i.get("status"),
                                    ((i.get("athlete") or {}).get("position") or {}).get("abbreviation")]
                                   for t_ in sm.get("injuries") or [] for i in t_.get("injuries") or []]
                rec["starters"] = [[(t_.get("team") or {}).get("abbreviation"),
                                    (p.get("athlete") or {}).get("displayName")]
                                   for t_ in sm.get("rosters") or [] for p in t_.get("roster") or []
                                   if p.get("starter")]
            out[gid] = rec
    return out


def archive(snap, day, path=None):
    """Append each game's inputs to frontier.json when they change."""
    import tickets
    book = tickets.load(path)
    d = book["days"].setdefault(day, dict(versions=[]))
    inp = d.setdefault("inputs", {})
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for gid, rec in snap.items():
        hist = inp.setdefault(gid, [])
        if not hist or {k: v for k, v in hist[-1].items() if k != "t"} != rec:
            hist.append(dict(rec, t=now))
    tickets.save(book, path)
