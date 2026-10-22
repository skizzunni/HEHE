"""Recommendations use confirmed current inputs; original calls stay intact."""
import copy
import datetime as dt
import math
import unittest
from unittest.mock import patch
import calls
import news

NOW=dt.datetime(2026,10,21,16,tzinfo=dt.timezone.utc)


def call(i,p=.82,price='-200',book='DraftKings',**kw):
    c=dict(id=f'nhl:{i}',league='nhl',pick=f'Team {i}',side='home',dc=False,
           match=f'Opponent {i} @ Team {i}',conf=round(p*100),price=price,book=book,
           start=(NOW+dt.timedelta(hours=2)).isoformat(),status='open',rank=i)
    q=dict(c,price_at=NOW.isoformat(),prob_at=NOW.isoformat(),checked_at=NOW.isoformat(),
           ready=True,gate=dict(ok=True,what='confirmed'))
    c['current']=q;c.update(kw);return c


class NoTicketDays(unittest.TestCase):
    def test_day_with_no_possible_ticket_is_recorded_not_silent(self):
        """2026-10-21: five ready 75%+ legs at -395 to -500; no 3 of them pay
        2x, so no snapshot was archived and nothing said why."""
        prices=['-500','-450','-425','-425','-395']
        cs=[call(i+1,p=.78,price=pr) for i,pr in enumerate(prices)]
        self.assertIsNone(calls.shadow_tickets(cs,NOW))
        w=calls.shadow_watch(None,cs,NOW)
        self.assertEqual((w['checks'],w['max_ready']),(1,5))
        self.assertLess(w['best_ceiling'],2.0)
        self.assertAlmostEqual(w['best_ceiling'],round((1+100/395)*(1+100/425)**2,3))
        w=calls.shadow_watch(w,cs[:1],NOW)
        self.assertEqual((w['checks'],w['max_ready']),(2,5))     # the best attempt is kept


class LivePickQuality(unittest.TestCase):
    def targets(self,cs,**kw):
        import live_tickets as L
        return L.build(cs,NOW,**kw)

    def test_failed_nba_fetch_is_not_an_injury_report(self):
        self.assertFalse(news.status('nba',{}, {})[0])
        self.assertFalse(news.status('wnba',{}, {'injuries':[]})[0])

    def test_started_settled_and_unconfirmed_do_not_enter_live_tickets(self):
        good=[call(1),call(2)]
        bad=[call(3,status='won'),call(4,start=(NOW-dt.timedelta(minutes=1)).isoformat()),call(5)]
        bad[2]['current']['ready']=False
        r=self.targets(good+bad)
        self.assertEqual(r['ready'],2)
        self.assertEqual(len(r['excluded']),3)

    def test_old_call_price_cannot_substitute_for_a_current_quote(self):
        cs=[call(1),call(2)]
        cs[0]['current']['price_at']=(NOW-dt.timedelta(minutes=20)).isoformat()
        self.assertEqual(self.targets(cs)['ready'],1)

    def test_no_current_snapshot_no_recommendation(self):
        c=call(1);del c['current']
        self.assertEqual(self.targets([c])['ready'],0)

    def test_probability_is_refreshed_with_the_price(self):
        cs=[call(1),call(2)]
        cs[0]['current'].update(conf=76,price='-150')
        r=self.targets(cs)['targets'][0]['ticket']
        self.assertEqual(r['legs'][0]['conf'],76)
        self.assertAlmostEqual(r['joint'],.76*.82*.982)
        self.assertEqual(cs[0]['conf'],82) # immutable original forecast

    def test_different_books_cannot_make_one_synthetic_parlay(self):
        r=self.targets([call(1),call(2,book='FanDuel')])
        self.assertIsNone(r['targets'][0]['ticket'])

    def test_target_selection_can_drop_a_useless_heavy_favourite(self):
        cs=[call(1,.92,'-2000'),call(2,.84,'-250'),call(3,.82,'-200')]
        r=self.targets(cs)['targets'][0]['ticket']
        self.assertEqual([x['id'] for x in r['legs']],['nhl:2','nhl:3'])
        self.assertGreaterEqual(r['payout'],2)
        old=.92*.84*.82*.982**2
        self.assertGreater(r['joint'],old)

    def test_probability_standard_is_never_lowered_for_a_target(self):
        r=self.targets([call(1,.74,'+100'),call(2,.74,'+100')])
        self.assertTrue(all(x['ticket'] is None for x in r['targets']))
        self.assertEqual(r['standard'],.75)

    def test_shared_game_or_team_never_enters_a_ticket_twice(self):
        cs=[call(1),call(2)]
        cs[1]['current']['match']=cs[0]['current']['match']
        self.assertIsNone(self.targets(cs)['targets'][0]['ticket'])

    def test_quote_future_timestamp_is_rejected(self):
        cs=[call(1),call(2)];cs[0]['current']['price_at']=(NOW+dt.timedelta(hours=1)).isoformat()
        self.assertEqual(self.targets(cs)['ready'],1)

class CurrentQuote(unittest.TestCase):
    def row(self,at,conf=.79):
        return dict(id='nhl:1',mypick='Team 1',myside='home',dc=False,myconf=conf,
                    price_at=at,price_book='Draft Kings',legs=[dict(side='home',price='-180',prob=conf,at=at)])

    def test_current_price_and_chance_do_not_rewrite_original_call(self):
        import live_tickets as L
        c=call(1,.90,'-900');c['gate']=dict(ok=True,what='confirmed')
        original=copy.deepcopy(c)
        q=L.current_quote(c,self.row(NOW.isoformat()),NOW)
        self.assertTrue(q['ready']);self.assertEqual((q['price'],q['conf']),('-180',79))
        self.assertEqual(c,original)

    def test_another_games_new_quote_cannot_clear_this_games_news(self):
        import live_tickets as L
        c=call(1);c['gate']=dict(ok=True);c['news_at']=NOW.isoformat()
        r=self.row((NOW-dt.timedelta(minutes=1)).isoformat())
        self.assertFalse(L.current_quote(c,r,NOW)['ready'])
        r=self.row((NOW+dt.timedelta(minutes=1)).isoformat())
        self.assertTrue(L.current_quote(c,r,NOW+dt.timedelta(minutes=2))['ready'])

    def test_quote_for_the_other_outcome_cannot_replace_the_frozen_call(self):
        import live_tickets as L
        c=call(1);c['gate']=dict(ok=True)
        r=self.row(NOW.isoformat());r['legs'][0]['side']='away'
        self.assertFalse(L.current_quote(c,r,NOW)['ready'])

class EvidenceSnapshots(unittest.TestCase):
    def test_valid_injury_report_survives_the_summary_cache(self):
        import participation as P
        import tempfile
        payload=dict(header=dict(competitions=[dict(id='7',competitors=[{},{}])]),injuries=[])
        with tempfile.TemporaryDirectory() as cache, patch.object(P,'CACHE',cache), patch.object(P.PL,'_get',return_value=payload):
            sm=P._summary('nba','7')
        self.assertTrue(news.status('nba',dict(id='nba:7'),sm)[0])
        self.assertFalse(news.status('nba',dict(id='nba:8'),sm)[0])

    def test_shadow_uses_frozen_prices_and_the_archived_market(self):
        import sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        import shadow
        cs=[call(1),call(2)]
        snap=calls.shadow_tickets(cs,NOW)
        original_price=snap['pool'][0]['price']
        cs[0]['price']='-9000';cs[0]['current']['price']='-9000'
        self.assertEqual(snap['pool'][0]['price'],original_price)
        rec=dict(calls=cs,shadow=snap)
        # The later board changed its side; the original selected Team 1 won.
        book={'nhl:1':dict(status='lost',pick='Other',winner='Team 1'),
              'nhl:2':dict(status='won',pick='Team 2',winner='Team 2')}
        rows=shadow.grade({'2026-10-21':rec},book)['optimizer_2x']
        self.assertEqual(rows[0],('2026-10-21',True,2.25))

    def test_gate_cannot_be_bypassed_by_a_ready_boolean(self):
        import live_tickets as L
        cs=[call(1),call(2)];cs[0]['current']['gate']['ok']=False
        self.assertEqual(L.build(cs,NOW)['ready'],1)

    def test_american_price_numeric_strings_are_supported(self):
        import live_tickets as L
        cs=[call(1,price='-200.0'),call(2,price='-200.0')]
        self.assertEqual(L.build(cs,NOW)['targets'][0]['ticket']['payout'],2.25)

class SlateCoverage(unittest.TestCase):
    def test_new_candidate_can_improve_tickets_without_rewriting_the_five_calls(self):
        import tempfile
        from pathlib import Path
        import live_tickets as L
        from test_daily_calls import row,state,NINE
        from test_news import goalies
        rows=[row(i,.76+i/100) for i in range(5)]
        for r in rows:
            r['comp']=goalies('confirmed','confirmed');r['legs'][0]['price']='-200'
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d,'calls.json'))
            first=calls.update_daily(state(rows),NINE,path,summary=lambda *a:None)
            original=[c['id'] for c in first['calls']]
            better=row(99,.92,price_age=-5);better['comp']=goalies('confirmed','confirmed');better['legs'][0]['price']='-200'
            later=calls.update_daily(state(rows+[better]),NINE+dt.timedelta(minutes=5),path,summary=lambda *a:None)
        self.assertEqual([c['id'] for c in later['calls']],original)
        pool=list(later['candidate_observations'].values())
        ticket=L.build(pool,NINE+dt.timedelta(minutes=5))['targets'][0]['ticket']
        self.assertIn('nhl:99',[c['id'] for c in ticket['legs']])

class TennisGateBridge(unittest.TestCase):
    def test_priced_tennis_can_leave_the_freeze_only_when_qualified(self):
        r=dict(myconf=.9,myside='home',legs=[dict(side='home',price='-900',book='DraftKings',at=NOW.isoformat())])
        with patch.object(calls,'is_call',return_value=False):
            self.assertFalse(news.status('wta',r,{})[0])
        with patch.object(calls,'is_call',return_value=True):
            self.assertTrue(news.status('wta',r,{})[0])
        r['legs']=[]
        with patch.object(calls,'is_call',return_value=True):
            self.assertFalse(news.status('wta',r,{})[0])
