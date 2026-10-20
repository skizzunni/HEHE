"""Tennis strong eligibility requires real quotes and prior priced results."""
import datetime as dt
import math
from zoneinfo import ZoneInfo
from record_eligibility import record_priced, valid_price
from freshness import parse

LEAGUES = ('atp', 'wta')
BOOKS = {'draftkings', 'fanduel'}
ET = ZoneInfo('America/New_York')


def captured_quote(e):
    book = e.get('price_book') or e.get('book') or ''
    return (str(book).replace(' ', '').lower() in BOOKS and valid_price(e.get('price'))
            and parse(e.get('price_at') or e.get('at')) is not None)


def stats(rows):
    n = len(rows); w = sum(e['status'] == 'won' for e in rows)
    lower = None
    if n:
        z = 1.959963984540054; p = w/n
        lower = (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)))/(1+z*z/n)
    return dict(n=n, won=w, lost=n-w, hit=round(100*w/n, 2) if n else None,
                wilson95_lower=round(100*lower, 2) if lower is not None else None,
                lower_fraction=lower)


def gate(league, entries, as_of=None, target=.75):
    """No same-day or future outcomes. A league cannot borrow the other tour's
    evidence. The full-precision Wilson lower bound must reach the target.
    """
    if isinstance(as_of, dt.datetime):
        boundary = as_of.astimezone(ET).date().isoformat()
    else:
        boundary = str(as_of or dt.datetime.now(ET).date())[:10]
    cutoff = dt.datetime.combine(dt.date.fromisoformat(boundary), dt.time(), ET)
    rows = []
    for e in entries:
        day = e.get('played') or e.get('date') or ''
        if (e.get('league') != league or e.get('status') not in ('won', 'lost')
                or not day or day >= boundary or not record_priced(e) or not captured_quote(e)):
            continue
        captured = parse(e.get('price_at'))
        if captured is None or captured.astimezone(ET).date().isoformat() > day:
            continue
        # Late-graded old games were not known before the selection day.
        settled = e.get('settled')
        if settled:
            try:
                st = dt.datetime.fromisoformat(settled.replace('Z', '+00:00'))
                st = st if st.tzinfo else st.replace(tzinfo=ET)
                if st >= cutoff:
                    continue
            except (TypeError, ValueError):
                continue
        rows.append(e)
    result = stats(rows)
    result.update(target=100*target, before=boundary,
                  qualified=result['lower_fraction'] is not None and result['lower_fraction'] >= target)
    return result


def report(entries, as_of=None, target=.75):
    rows = [e for e in entries if e.get('league') in LEAGUES and e.get('status') in ('won', 'lost')]
    priced = [e for e in rows if record_priced(e) and captured_quote(e)]
    unpriced = [e for e in rows if not record_priced(e)]
    other = [e for e in rows if record_priced(e) and not captured_quote(e)]
    return dict(priced=stats(priced), unpriced=stats(unpriced), other_priced=stats(other),
                unpriced_strong=stats([e for e in unpriced if e.get('strong')]),
                leagues={lg: gate(lg, rows, as_of, target) for lg in LEAGUES})
