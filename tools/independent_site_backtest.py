"""Independent fixed-coverage comparison on archived exchange quotes.

This is historical quote research, not evidence of morning executable trades:
the archive joins pre-start hourly quotes with sportsbook closing features.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


def choose(rows, k, mode):
    keys = {
        'market': lambda r: r['mid'],
        'score_model': lambda r: r['p'],
        'model_value': lambda r: r['p']/r['all_cost'],
        'market_less_spread': lambda r: r['mid']-r['width']/2,
    }
    best={}
    for r in sorted(rows,key=lambda r:(-keys[mode](r),r['game'],r['ticker'],r['side'])):
        best.setdefault(r['game'],r)
    legs=list(best.values())[:k]
    return legs if len(legs)==k else []


def evaluate(days,k,mode):
    by={d:choose(rs,k,mode)for d,rs in days.items()}
    by={d:rs for d,rs in by.items()if rs}
    legs=[r for rs in by.values()for r in rs]
    if not legs:return dict(days=0,n=0),by
    stake=sum(r['all_cost']for r in legs);wins=sum(r['won']for r in legs)
    return dict(days=len(by),n=len(legs),wins=wins,hit=wins/len(legs),
                equal_contract_roi=(wins-stake)/stake,
                equal_cash_roi=sum(r['won']/r['all_cost']-1 for r in legs)/len(legs)),by


def paired(a,b):
    if set(a)!=set(b):raise ValueError('Coverage mismatch')
    changes=np.array([[sum(r['won']for r in b[d])-sum(r['won']for r in a[d]),
                       sum(r['won']/r['all_cost']-1 for r in b[d])-
                       sum(r['won']/r['all_cost']-1 for r in a[d])]for d in sorted(a)])
    if not len(changes):return {}
    rng=np.random.default_rng(71)
    boot=changes[rng.integers(0,len(changes),(5000,len(changes)))].sum(axis=1)
    return dict(extra_wins=int(changes[:,0].sum()),extra_profit_equal_cash=float(changes[:,1].sum()),
                ci95_extra_wins=np.quantile(boot[:,0],[.025,.975]).tolist(),
                ci95_extra_profit=np.quantile(boot[:,1],[.025,.975]).tolist())


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--archive',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    rows=json.loads(a.archive.read_text());dates=sorted({r['date']for r in rows})
    train_end=dates[len(dates)//2];test_from=dates[3*len(dates)//4]
    modes=['market','score_model','model_value','market_less_spread'];out={}
    for name,(lo,hi)in [('regular',(1/1.834,.8)),('safe',(1/1.20,1/1.05))]:
        days=defaultdict(list)
        for raw in rows:
            if not lo<=raw['cost']<=hi:continue
            r=dict(raw,all_cost=raw['cost']+raw['fee'],mid=raw['cost']-raw['width']/2)
            if 0<r['all_cost']<1:days[r['date']].append(r)
        validation={d:rs for d,rs in days.items()if train_end<=d<test_from}
        test={d:rs for d,rs in days.items()if d>=test_from}
        for k in [3,11]:
            val={m:evaluate(validation,k,m)[0]for m in modes}
            # Predeclared objective: higher fixed-coverage accuracy; ROI breaks ties.
            chosen=max(modes,key=lambda m:(val[m].get('hit',-1),val[m].get('equal_cash_roi',-100)))
            base,ab=evaluate(test,k,'market');new,bb=evaluate(test,k,chosen)
            out[f'{name}_{k}']=dict(chosen_by_validation=chosen,validation=val,
                                     test_market=base,test_candidate=new,paired=paired(ab,bb))
    result=dict(rows=len(rows),events=len({r['game']for r in rows}),dates=len(dates),
                validation_from=train_end,test_from=test_from,studies=out,
                limitation='Historical last pre-start hourly quotes plus sportsbook closing features; not a morning execution simulation')
    a.out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
