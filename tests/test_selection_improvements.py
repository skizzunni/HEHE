"""Decision constraints and historical-version invariants; no network."""
import json
import math
import os
import random
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import lottery
import parlays


def leg(gid,p,d,label=None):
    return dict(gid=gid,p=p,dec=d,value=p*d,label=label or gid,kind='game',fd='m:r')


class TicketPolish(unittest.TestCase):
    def test_swap_improves_both_chance_and_return(self):
        old=leg('a',.2,4,'old');new=leg('a',.4,2.5,'new')
        got=lottery.polish_ticket([old],[old,new],2)
        self.assertEqual(got,[new])

    def test_no_chance_gain_bought_with_worse_return(self):
        old=leg('a',.2,6,'old');new=leg('a',.3,3,'new')
        self.assertEqual(lottery.polish_ticket([old],[old,new],2),[old])

    def test_tiny_probabilities_still_cannot_decrease(self):
        old=leg('a',1e-15,2,'old');new=leg('a',.5e-15,6,'new')
        self.assertEqual(lottery.polish_ticket([old],[old,new],2),[old])

    def test_redundant_negative_value_leg_can_drop(self):
        a,b=leg('a',.6,2),leg('b',.4,2)
        self.assertEqual(lottery.polish_ticket([a,b],[a,b],2),[a])

    def test_preserves_event_and_previous_ticket_exclusions(self):
        a,b=leg('a',.4,3),leg('b',.5,2)
        blocked=leg('blocked',.99,3)
        duplicate=leg('a',.95,3,'other a')
        got=lottery.polish_ticket([a,b],[a,b,blocked,duplicate],5,used={'blocked'})
        self.assertEqual(len({x['gid']for x in got}),len(got))
        self.assertNotIn('blocked',{x['gid']for x in got})

    def test_randomized_pareto_invariant(self):
        rng=random.Random(33)
        for _ in range(100):
            pool=[leg(str(g),rng.uniform(.15,.9),rng.uniform(1.7,5),f'{g}-{i}')
                  for g in range(5)for i in range(3)]
            old=[pool[g*3]for g in range(4)]
            target=math.prod(x['dec']for x in old)*.7
            boost=rng.choice([0,.25,.5,1])
            new=lottery.polish_ticket(old,pool,target,boost)
            p0,p1=[math.prod(x['p']for x in ls)for ls in [old,new]]
            d0,d1=[math.prod(x['dec']for x in ls)for ls in [old,new]]
            self.assertGreaterEqual(p1+1e-12,p0)
            self.assertGreaterEqual(p1*lottery.boosted(d1,boost)+1e-12,p0*lottery.boosted(d0,boost))
            self.assertGreaterEqual(d1+1e-8,target)
            self.assertEqual(len(new),len({x['gid']for x in new}))

    def test_old_archives_keep_old_optimizer(self):
        a,b=leg('a',.2,4),leg('a',.4,2.5,'new')
        tier=dict(tier='test',dec=(1.25,6),rank=lambda x:x['dec'],pay=2,n=1)
        # Legacy reconstruction does not acquire a new post-selection step.
        self.assertEqual(lottery._tickets([a,b],'FanDuel',tier,legacy=True)[0]['legs'],[b])
        self.assertEqual(lottery.OPTIMIZER_VERSION,'pareto-polish-v1')


class SuggestedValueTickets(unittest.TestCase):
    def row(self,name,p=.8,price='-200',**kw):
        return ('nfl',dict(mp=name,hit=p,p=price,tk='strong',d=False,hd=False,
                           lg='NFL',t='1 PM',dk=None,fd=None,id=name,**kw))

    def test_no_negative_return_suggestions(self):
        rows=dict(nfl=dict(rows=[self.row('a',.7,'-400')[1],self.row('b',.7,'-400')[1]]))
        got=parlays.build(rows)
        self.assertEqual(got[2],[]);self.assertEqual(got[3],[])

    def test_final_probability_and_qualification_are_used(self):
        good=self.row('a',.8,'-200');unqualified=self.row('b',.8,'-200',nc=True)
        got=parlays.eligible([good,unqualified])
        self.assertEqual(len(got),1);self.assertEqual(got[0]['hit'],.8)

    def test_duplicate_event_cannot_enter_ticket(self):
        a,b=parlays.eligible([self.row('a'),self.row('b')])
        b['gid']=a['gid']
        self.assertEqual(parlays.tickets([a,b],2),[])


if __name__=='__main__':unittest.main()
