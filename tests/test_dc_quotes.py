"""A quoted moneyline cannot stand in for the selected double-chance bet."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import calls
import dashboard
import fanduel
import freshness
import ledger

NOW = dt.datetime.now(dt.timezone.utc)
AT = NOW.isoformat()
START = (NOW + dt.timedelta(hours=3)).isoformat()


def row():
    return dict(id='epl:700', mypick='Home FC', myside='home', myconf=.84,
                label='Away FC @ Home FC', dc=True, price_book='DraftKings', price_at=AT,
                mkt=dict(start=START, away='Away FC', home='Home FC'),
                legs=[dict(side='home', who='Home FC', price='-150', prob=.60, book='DraftKings', at=AT),
                      dict(side='draw', who='Draw', price='+300', prob=.24, book='DraftKings', at=AT)],
                dc_legs=[dict(side='home', who='Home FC', price='-500', prob=.84,
                              market='double_chance', book='FanDuel', at=AT, fd='m:1')])


class DCQuotes(unittest.TestCase):
    def test_dc_quote_reaches_ledger_and_append_only_history(self):
        r = row(); day = NOW.astimezone(ledger.ET).strftime('%Y%m%d')
        with tempfile.TemporaryDirectory() as d, patch.object(ledger, 'LEDGER', str(Path(d, 'ledger.json'))):
            ledger.record(dict(dates=[day, day], slots=dict(today={'epl': [r]}, tomorrow={})))
            e = ledger.load()['epl:700']
        self.assertEqual((e['price'], e['price_book'], e['price_at'], e['price_market']),
                         ('-500', 'FanDuel', AT, 'double_chance'))
        self.assertEqual(e['history'][-1]['price_market'], 'double_chance')
        self.assertEqual(e['first_price'], '-500')

    def test_missing_or_stale_dc_quote_cannot_borrow_fresh_moneyline(self):
        r = row(); r['dc_legs'] = []
        self.assertFalse(freshness.can_call(r, NOW))
        r = row(); r['dc_legs'][0]['at'] = (NOW-dt.timedelta(minutes=20)).isoformat()
        self.assertFalse(freshness.can_call(r, NOW))

    def test_priced_dc_can_enter_daily_calls(self):
        c = calls.candidates({'epl': [row()]}, NOW.strftime('%Y%m%d'), NOW)
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]['pick'], c[0]['price'], c[0]['dc']), ('Home FC or draw', '-500', True))

    def test_only_the_correct_side_and_market_can_price_a_dc_call(self):
        for changes in [dict(side='away'), dict(market='moneyline'), dict(book=None), dict(price='nan')]:
            r = row(); r['dc_legs'][0].update(changes)
            self.assertFalse(freshness.can_call(r, NOW))

    def test_dashboard_captures_real_fanduel_dc_and_provenance(self):
        r = row(); r['dc_legs'] = []
        game = dict(id='99', away='Away FC', home='Home FC', start=START, soccer=True)
        with patch.object(fanduel, 'load_alts', return_value=[('dc', 'Home FC', None, None, 'm:1', '-500', 'Double Chance')]), \
             patch.object(fanduel, 'quote_time', return_value=AT):
            dashboard.capture_dc(r, 'epl', {'epl': [game]})
        self.assertEqual((r['dc_legs'][0]['price'], r['dc_legs'][0]['book'], r['dc_legs'][0]['at']),
                         ('-500', 'FanDuel', AT))

    def test_wrong_fixture_or_missing_start_never_supplies_dc(self):
        r = row(); r['dc_legs'] = []
        with patch.object(fanduel, 'load_alts') as fetch:
            dashboard.capture_dc(r, 'epl', {'epl': [dict(id='99', away='Away FC', home='Home FC', start=None)]})
        self.assertEqual(r['dc_legs'], [])
        fetch.assert_not_called()

    def test_legacy_first_price_cleanup_keeps_real_dc_quote(self):
        e = dict(dc=True, price_market='double_chance', first_price='-500')
        ledger._fix_first_prices({'epl:1': e})
        self.assertEqual(e.get('first_price'), '-500')

if __name__ == '__main__': unittest.main()
