"""A UFC card, fight by fight, from ESPN: each fighter's record, KO and
submission wins-losses, last-5 significant strikes per fight and accuracy,
takedowns, knockdowns, days since the last fight, and the latest headline.
Research the user asked for before a card; information only -- on 2,850 past
fights these facts did not beat the price (README, 2026-11-08).

    python tools/ufc_card_research.py [YYYYMMDD]
"""
import datetime as dt
import json
import sys
import urllib.request

SB = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates={}"
ATH = "https://site.web.api.espn.com/apis/common/v3/sports/mma/athletes/"


def get(u):
    with urllib.request.urlopen(u, timeout=30) as r:
        return json.load(r)


def _num(x):
    try:
        return float(str(x).replace("%", ""))
    except (TypeError, ValueError):
        return None


def card(day, fetch=get):
    """[(name_a, id_a, name_b, id_b, weight class)] for the day's UFC bouts."""
    out = []
    for e in (fetch(SB.format(day)) or {}).get("events", []):
        for c in e.get("competitions", []):
            cs = c.get("competitors") or []
            if len(cs) == 2:
                a, b = (x.get("athlete") or {} for x in cs)
                out.append((a.get("displayName"), cs[0].get("id") or a.get("id"),
                            b.get("displayName"), cs[1].get("id") or b.get("id"),
                            (c.get("type") or {}).get("abbreviation", "")))
    return out


def summarize(profile, stats, events_map=None, today=None):
    """One fighter's numbers from ESPN's athlete profile and /stats payloads."""
    a = profile.get("athlete") or {}
    ss = {s["name"]: s["displayValue"] for s in (a.get("statsSummary") or {}).get("statistics", [])}
    rows = {}
    for c in stats.get("categories", []):
        lab = [str(l).strip() for l in c.get("labels", [])]
        for r in c.get("statistics", [])[:5]:
            rows.setdefault(r["eventId"], {}).update(dict(zip(lab, r["stats"])))
    R = list(rows.values())[:5]

    def avg(k):
        v = [_num(r.get(k)) for r in R if _num(r.get(k)) is not None]
        return sum(v) / len(v) if v else None
    ssl, ssa = avg("SSL"), avg("SSA")
    M = events_map if events_map is not None else (profile.get("eventsMap") or {})
    dates = sorted((e.get("gameDate") or "")[:10] for e in M.values() if e.get("gameResult") in ("W", "L", "D"))
    days_off = None
    if dates and today:
        days_off = (today - dt.date.fromisoformat(dates[-1])).days
    return dict(name=a.get("displayName"), age=a.get("age"), reach=a.get("displayReach"),
                rec=ss.get("wins-losses-draws"), ko=ss.get("tkos-tkoLosses"), sub=ss.get("submissions-submissionLosses"),
                ssl=ssl, acc=(100 * ssl / ssa if ssl and ssa else None), td=avg("TDL"), tda=avg("TDA"),
                kd=sum(_num(r.get("KD")) or 0 for r in R), n=len(R), days_off=days_off)


def line(s):
    f = lambda x, d=0: "-" if x is None else f"{x:.{d}f}"
    return (f"{s['name']}: {s['rec']}, age {s['age']}, reach {s['reach']} | KO W-L {s['ko']}, Sub W-L {s['sub']} | "
            f"last {s['n']}: {f(s['ssl'])} sig strikes/fight at {f(s['acc'])}%, takedowns {f(s['td'], 1)}/{f(s['tda'], 1)}, "
            f"knockdowns {int(s['kd'])}" + (f" | {s['days_off']} days since last fight" if s["days_off"] is not None else ""))


def main(day):
    today = dt.date(int(day[:4]), int(day[4:6]), int(day[6:]))
    for na, ia, nb, ib, wc in card(day):
        print(f"=== {na} vs {nb} ({wc})")
        for nm, i in ((na, ia), (nb, ib)):
            try:
                p = get(ATH + str(i))
                s = summarize(p, get(ATH + str(i) + "/stats"), today=today)
                print("   " + line(s))
                news = (get(ATH + str(i) + "/overview").get("news") or [])[:1]
                if news:
                    print(f"      news: {news[0]['headline']} ({news[0].get('lastModified', '')[:10]})")
            except Exception as e:
                print(f"   {nm}: unavailable ({type(e).__name__})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else dt.date.today().strftime("%Y%m%d"))
