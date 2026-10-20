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
    return not e.get('dc') or e.get('price_market') == 'double_chance'


def exclude_unpriced(book):
    for e in book.values():
        if not record_priced(e):
            e.setdefault('record_excluded', 'unpriced')
