"""Collect every UFC fight ESPN lists (calendar per year, then each event's
scoreboard): date, both fighters (ESPN athlete id + name), winner, round,
clock, scheduled rounds and the result text. Saved to ufc_history.json, keyed
by competition id, so a re-run only adds new fights.

    python tools/ufc_history.py 2015 2026
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "ufc_history.json")
SB = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates={}"


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def fights(sb):
    """[(competition id, record)] from one scoreboard payload."""
    out = []
    for ev in sb.get("events") or []:
        for c in ev.get("competitions") or []:
            cs = c.get("competitors") or []
            st = c.get("status") or {}
            if len(cs) != 2 or not (st.get("type") or {}).get("completed"):
                continue
            a = [dict(id=x.get("id"), name=(x.get("athlete") or {}).get("displayName"),
                      won=bool(x.get("winner")),
                      record=next((r.get("summary") for r in x.get("records") or [] if r.get("type") == "total"), None))
                 for x in cs]
            res = next((d.get("type", {}).get("text") for d in c.get("details") or []
                        if d.get("type", {}).get("text", "").startswith(("KO", "TKO", "Sub", "Dec", "U-Dec", "S-Dec", "M-Dec"))), None)
            out.append((c.get("id"), dict(date=(c.get("date") or ev.get("date") or "")[:10], event=ev.get("name"),
                                         a=a[0], b=a[1], round=st.get("period"), clock=st.get("displayClock"),
                                         rounds=((c.get("format") or {}).get("regulation") or {}).get("periods"),
                                         result=res)))
    return out


def main(y0, y1):
    try:
        with open(OUT) as fh:
            book = json.load(fh)
    except (OSError, ValueError):
        book = {}
    for y in range(y0, y1 + 1):
        cal = (get(SB.format(y)).get("leagues") or [{}])[0].get("calendar") or []
        import datetime as dt
        days = set()
        for c in cal:                  # a late card's UTC date is often the day after the US one
            if c.get("startDate"):
                d0 = dt.date.fromisoformat(c["startDate"][:10])
                days |= {d0.strftime("%Y%m%d"), (d0 - dt.timedelta(days=1)).strftime("%Y%m%d")}
        days = sorted(days)
        for d in days:
            for cid, rec in fights(get(SB.format(d))):
                book[cid] = rec
            time.sleep(0.2)
        print(y, len(days), "events,", len(book), "fights so far", flush=True)
        with open(OUT, "w") as fh:
            json.dump(book, fh)
    return book


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
