"""Old research caches cannot bypass retroactive quote eligibility."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import clv
import devig_study


class CachedPriceStudies(unittest.TestCase):
    def test_old_unpriced_clv_cannot_influence_rule_or_weekly_record(self):
        cache=dict(picks={'wta:1':dict(day='2026-10-19', won=1, league='wta', published=.94, close=.8, clv=-14)})
        entries={'wta:1':dict(league='wta', status='won', conf=94, price=None, date='2026-10-19')}
        clv.update(entries,cache,limit=0)
        self.assertEqual(clv.rule(cache)['last']['n'],0)
        self.assertEqual(clv.weekly(cache),{})
        self.assertIn('wta:1',cache['picks']) # audit evidence stays available

    def test_missing_ledger_entry_cannot_validate_cached_pick(self):
        cache=dict(picks={'missing':dict(day='2026-10-19', won=1, published=.9, close=.8, clv=-10)})
        clv.update({},cache,limit=0)
        self.assertEqual(clv.report(cache['picks'].values())['n'],0)

    def test_devig_study_selects_only_original_priced_calls(self):
        entries={'wta:1':dict(status='won', price=None, date='2026-10-19'),
                 'epl:2':dict(status='lost', price='-200', dc=True, date='2026-10-19'),
                 'nhl:3':dict(status='won', price='-150', date='2026-10-19')}
        self.assertEqual([key for key,_ in devig_study.eligible(entries,'2026-10-15','2026-10-19')],['nhl:3'])

    def test_empty_priced_study_has_no_invented_estimate(self):
        self.assertEqual(devig_study.score([], 'new'),dict(n=0,brier=None,logloss=None,bands=[]))
        self.assertEqual(devig_study.boot([]),dict(mean=None,ci95=None))
