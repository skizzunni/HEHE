"""Tennis strong labels need genuine quotes and prior priced evidence."""
import datetime as dt
import unittest
from unittest.mock import patch
import calls
import ledger

AT = '2026-10-19T12:00:00+00:00'
QUOTE = dict(price='-500', book='DraftKings', at='2026-10-20T12:00:00+00:00')


def results(w=200, n=200, league='wta', priced=True, day='2026-10-19'):
    return [dict(league=league, pick=f'Player {i}', date=day, played=day, conf=85, strong=True,
                 status='won' if i < w else 'lost', price='-500' if priced else None,
                 price_book='DraftKings' if priced else None, price_at=AT if priced else None)
            for i in range(n)]


class TennisFreeze(unittest.TestCase):
    def setUp(self):
        self.p = patch.dict(calls._MIN, {'atp': .65, 'wta': .65}); self.p.start()

    def tearDown(self): self.p.stop()

    def strong(self, rows, quote=QUOTE, league='wta'):
        return calls.is_call(league, 94, quote=quote, as_of='2026-10-20', entries=rows)

    def test_a_high_confidence_alone_cannot_unlock_tennis(self):
        self.assertFalse(calls.is_call('wta', 94))

    def test_no_evidence_and_69_percent_record_stay_frozen(self):
        self.assertFalse(self.strong([]))
        self.assertFalse(self.strong(results(20, 29)))

    def test_only_verified_dk_or_fd_prices_can_unlock(self):
        rows = results()
        self.assertTrue(self.strong(rows))
        self.assertTrue(self.strong(rows, dict(QUOTE, book='FanDuel')))
        for q in [dict(QUOTE, book='Kalshi'), dict(QUOTE, book=None), dict(QUOTE, at=None),
                  dict(QUOTE, price=None), dict(QUOTE, price='nan')]:
            self.assertFalse(self.strong(rows, q))

    def test_unpriced_winners_cannot_unlock(self):
        self.assertFalse(self.strong(results(priced=False)))

    def test_future_and_same_day_outcomes_never_unlock(self):
        self.assertFalse(self.strong(results(day='2026-10-20')))
        self.assertFalse(self.strong(results(day='2026-10-21')))

    def test_atp_and_wta_do_not_borrow_each_others_evidence(self):
        self.assertFalse(self.strong(results(league='atp')))
        self.assertTrue(self.strong(results(league='atp'), league='atp'))

    def test_results_separate_priced_and_unpriced_tennis(self):
        rows = results(20, 29, priced=False) + results(8, 10)
        with patch.object(ledger, 'load', return_value={f'wta:{i}': e for i, e in enumerate(rows)}):
            rec = ledger.board_payload()['tennis_record']
        self.assertEqual((rec['priced']['n'], rec['priced']['won']), (10, 8))
        self.assertEqual((rec['unpriced']['n'], rec['unpriced']['won']), (29, 20))
        self.assertEqual(rec['unpriced_strong']['n'], 29)
        self.assertFalse(rec['leagues']['wta']['qualified'])

if __name__ == '__main__': unittest.main()

class TemporalAndPublication(unittest.TestCase):
    def test_late_grading_does_not_retroactively_unlock(self):
        import tennis_eligibility as T
        rows = [dict(e, settled='2026-10-20T15:00:00-04:00') for e in results()]
        self.assertFalse(T.gate('wta', rows, '2026-10-20')['qualified'])

    def test_current_published_tennis_calls_are_close_until_qualified(self):
        import freshness
        now = dt.datetime.now(dt.timezone.utc)
        row = dict(id='wta:1', mypick='Player', myside='home', myconf=.94,
                   mkt=dict(start=(now+dt.timedelta(hours=2)).isoformat()),
                   legs=[dict(side='home', price='-500', book='DraftKings', at=now.isoformat())])
        with patch.dict(calls._MIN, {'wta': .65}), patch.object(ledger, 'load', return_value={}):
            self.assertTrue(freshness.can_call(row, now))
            candidates = calls.candidates({'wta': [row]}, now.strftime('%Y%m%d'), now)
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]['close'])

    def test_results_show_tennis_freeze(self):
        from pathlib import Path
        page = Path(ledger.HERE, 'board.html').read_text()
        self.assertIn('Tennis evidence', page)
        self.assertIn('Wilson 95% lower bound', page)
