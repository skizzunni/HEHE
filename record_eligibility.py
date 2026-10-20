"""Quote evidence required for the performance record, including old rows.

Historical straight-win rows retain their captured numeric price even when
older schemas lacked provenance fields. A straight-win quote is never proof
of a double-chance quote. Exclusion flags are append-only audit metadata.
"""
import math


def valid_price(price):
    try:
        value = float(str(price).replace('+', ''))
        return math.isfinite(value) and abs(value) >= 100
    except (TypeError, ValueError):
        return False


def record_priced(e):
    if e.get('record_excluded'):
        return False
    if not valid_price(e.get('price')):
        return False
    if not e.get('dc'):
        return True
    from freshness import parse
    return (e.get('price_market') == 'double_chance' and bool(e.get('price_book'))
            and parse(e.get('price_at')) is not None)


def exclude_unpriced(book):
    for e in book.values():
        if not record_priced(e):
            e.setdefault('record_excluded', 'unpriced')


def selection_leg(r, side=None, dc=None):
    """Quote for the exact selected market, never another leg on the row."""
    side = r.get('myside') if side is None else side
    dc = bool(r.get('dc')) if dc is None else dc
    legs = r.get('dc_legs') if dc else r.get('legs')
    for leg in legs or []:
        if side is not None and leg.get('side') != side:
            continue
        if not valid_price(leg.get('price')):
            continue
        if dc and (leg.get('market') != 'double_chance' or not leg.get('book') or not leg.get('at')):
            continue
        if not dc and leg.get('market') not in (None, 'moneyline'):
            continue
        return leg
    return None


def quote_at(r):
    leg = selection_leg(r)
    return (leg or {}).get('at') or (None if r.get('dc') else r.get('price_at'))


def quote_book(r):
    leg = selection_leg(r)
    return (leg or {}).get('book') or (None if r.get('dc') else r.get('price_book'))
