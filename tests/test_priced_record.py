"""Retroactive quote eligibility applies equally to winners and losers."""
import unittest
from unittest.mock import patch
import ledger
import calibration
import rebuild_board


def entry(status='won', **kw):
    e = dict(league='wta', pick='Player', conf=94, p_raw=94, strong=True,
             price=None, status=status, date='2026-10-20', played='2026-10-20')
    e.update(kw)
    return e


class PricedRecord(unittest.TestCase):
    def test_report_and_payload_exclude_both_outcomes_and_dc_moneyline(self):
        book = {'a': entry(), 'b': entry('lost'),
                'c': entry(league='epl', dc=True, price='-200'),
                'd': entry(league='nhl', price='-150')}
        with patch.object(ledger, 'load', return_value=book):
            r, _ = ledger.report()
            p = ledger.board_payload()
        self.assertEqual((r['graded'], r['won'], r['lost']), (1, 1, 0))
        self.assertEqual(p['excluded_unpriced'], 3)
        self.assertEqual(sum(x['n'] for x in p['calibration']), 1)
        self.assertFalse(ledger._strong(book['a']))

    def test_calibration_and_bands_never_rehabilitate_unpriced_dc(self):
        rows = [entry(), entry(league='epl', dc=True, history=[dict(prices={'home': '-200'})]), entry(league='wta', price='-150')]
        self.assertEqual(len(calibration.graded(rows)), 1)
        bands = rebuild_board.live_bands(rows, ledger.SOCCER)
        self.assertEqual(sum(v[0] for v in bands.values()), 1)

    def test_grade_marks_old_settled_rows_without_erasing_results(self):
        book = {'wta:1': entry(), 'wta:2': entry('lost')}
        with patch.object(ledger, 'load', return_value=book), patch.object(ledger, 'save'):
            ledger.grade()
        self.assertEqual([e.get('record_excluded') for e in book.values()], ['unpriced', 'unpriced'])
        self.assertEqual([e['status'] for e in book.values()], ['won', 'lost'])

    def test_exclusion_is_permanent_even_if_a_price_is_later_attached(self):
        e = entry(price='-500', record_excluded='unpriced')
        with patch.object(ledger, 'load', return_value={'wta:1': e}):
            self.assertEqual(ledger.report()[0]['graded'], 0)
        self.assertFalse(ledger._strong(e))

    def test_results_notice_is_visible(self):
        from pathlib import Path
        page = Path(ledger.HERE, 'board.html').read_text()
        self.assertIn('unpriced picks excluded from the record', page)

if __name__ == '__main__':
    unittest.main()
