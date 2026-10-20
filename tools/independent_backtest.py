"""Chronological, reproducible private research on recorded soccer closing odds.

Run validation first, then final once. CSVs stay outside this repository.
This is a close-time study, not an executable morning/FanDuel backtest.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import softmax

SEASONS = ['2021', '2122', '2223', '2324', '2425', '2526']
LEAGUES = ['E0', 'E1', 'D1', 'I1', 'SP1', 'F1']
MODELS = ['proportional', 'power', 'calibrated', 'elo_residual']


def load(data_dir, final=False):
    frames, manifest = [], []
    for season in SEASONS if final else SEASONS[:-1]:
        for league in LEAGUES:
            path = data_dir / f'{league}_{season}.csv'
            if not path.exists():
                raise ValueError(f'Missing declared source: {path}')
            raw = path.read_bytes()
            manifest.append(dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest()))
            f = pd.read_csv(path, encoding='utf-8-sig')
            f['day'] = pd.to_datetime(f['Date'], dayfirst=True, errors='coerce')
            f['season'], f['league'] = season, league
            frames.append(f)
    f = pd.concat(frames, ignore_index=True).sort_values(['day', 'league', 'HomeTeam', 'AwayTeam'])
    before = len(f)
    for col in ['AvgCH','AvgCD','AvgCA','B365CH','B365CD','B365CA']:
        f[col] = pd.to_numeric(f[col], errors='coerce')
    cols = ['AvgCH','AvgCD','AvgCA','B365CH','B365CD','B365CA']
    f = f[f.FTR.isin(['H','D','A']) & f.day.notna() & (f[cols] > 1).all(axis=1)].copy()
    q = 1 / f[['AvgCH','AvgCD','AvgCA']].to_numpy()
    f = f[(q.sum(axis=1) >= 1) & (q.sum(axis=1) <= 1.3)].copy()
    f = f.drop_duplicates(['season','league','day','HomeTeam','AwayTeam']).reset_index(drop=True)
    f['y'] = f.FTR.map({'H':0,'D':1,'A':2})
    # Elo uses only earlier dates. All results on a date are applied after its forecasts.
    ratings, seen_seasons, features = {}, {}, np.zeros(len(f))
    for day, group in f.groupby('day', sort=True):
        updates = []
        for i, r in group.iterrows():
            keys = [(r.league,r.HomeTeam),(r.league,r.AwayTeam)]
            for key in keys:
                if seen_seasons.get(key) != r.season:
                    ratings[key] = 1500 + .75 * (ratings.get(key,1500) - 1500)
                    seen_seasons[key] = r.season
            h,a = [ratings[k] for k in keys]
            z = (h-a+60) * np.log(10) / 400
            features[i] = z
            result = 1 if r.y == 0 else .5 if r.y == 1 else 0
            delta = 20 * (result - 1/(1+np.exp(-z)))
            updates.append((keys,delta))
        for (hk,ak),delta in updates:
            ratings[hk] += delta
            ratings[ak] -= delta
    f['elo_z'] = features
    return f, dict(raw_rows=before, usable_rows=len(f), sources=manifest)


def market(f):
    q = 1 / f[['AvgCH','AvgCD','AvgCA']].to_numpy()
    return q / q.sum(axis=1,keepdims=True)


def power(f):
    q = 1 / f[['AvgCH','AvgCD','AvgCA']].to_numpy()
    lo,hi = np.ones(len(f)),np.full(len(f),5.)
    for _ in range(48):
        mid = (lo+hi)/2
        high = (q ** mid[:,None]).sum(axis=1)>1
        lo = np.where(high,mid,lo); hi = np.where(high,hi,mid)
    p = q ** ((lo+hi)/2)[:,None]
    return p / p.sum(axis=1,keepdims=True)


def predict(f, name, params):
    p = market(f)
    if name == 'proportional': return p
    if name == 'power': return power(f)
    v = np.asarray(params[name])
    logits = np.log(p) * (1+v[0]) + np.array([v[1],v[2],0.])
    if name == 'elo_residual':
        logits += v[3] * f.elo_z.to_numpy()[:,None] * np.array([1.,0.,-1.])
    return softmax(logits,axis=1)


def fit(train):
    params = {}
    y = train.y.to_numpy()
    for name,n in [('calibrated',3),('elo_residual',4)]:
        def objective(v):
            p = predict(train,name,{name:v})
            return -np.log(np.maximum(p[np.arange(len(y)),y],1e-12)).sum()+25*np.dot(v,v)
        r = minimize(objective,np.zeros(n),method='L-BFGS-B',bounds=[(-.5,1.)]+[(-1.,1.)]*(n-1))
        if not r.success: raise RuntimeError(r.message)
        params[name] = r.x.tolist()
    return params


def scores(f,p):
    y = f.y.to_numpy(); onehot = np.eye(3)[y]
    return dict(n=len(f),accuracy=float((p.argmax(axis=1)==y).mean()),
                logloss=float(-np.log(p[np.arange(len(y)),y]).mean()),
                brier=float(((p-onehot)**2).sum(axis=1).mean()))


def selected(f,p):
    # Fixed eligible same-market-favourite universe, equal coverage, no extra outcomes.
    fav = market(f).argmax(axis=1)
    odds = f[['B365CH','B365CD','B365CA']].to_numpy()
    o = odds[np.arange(len(f)),fav]
    s = f[['day','league','HomeTeam','AwayTeam','y']].copy()
    s['side'],s['odds'],s['prob'] = fav,o,p[np.arange(len(f)),fav]
    s['won'] = (fav==f.y.to_numpy()).astype(int)
    named = []
    # Pinnacle excluded: source warns its feed became stale in July 2025.
    for book in ['B365','BW','WH','BF']:
        cs = [book+'C'+x for x in ['H','D','A']]
        if all(c in f for c in cs):
            arr = f[cs].apply(pd.to_numeric,errors='coerce').to_numpy()
            named.append(arr[np.arange(len(f)),fav])
    s['best_odds'] = np.nanmax(np.array(named),axis=0)
    s = s[(s.odds>=1.25)&(s.odds<=1.834)]
    groups = [g.sort_values(['prob','league','HomeTeam'],ascending=[False,True,True]).head(3)
              for _,g in s.groupby('day') if len(g)>=3]
    return pd.concat(groups,ignore_index=True) if groups else s.iloc[:0]


def selection_summary(s):
    return dict(n=len(s),days=s.day.nunique(),wins=int(s.won.sum()),
                hit=float(s.won.mean()) if len(s) else None,
                mean_odds=float(s.odds.mean()) if len(s) else None,
                roi=float((s.won*s.odds-1).mean()) if len(s) else None,
                best_named_book_roi=float((s.won*s.best_odds-1).mean()) if len(s) else None)


def paired(a,b,draws=5000):
    d = pd.concat([a.groupby('day').agg(won=('won','sum'),pnl=('won',lambda x:0)),
                   b.groupby('day').agg(new_won=('won','sum'))],axis=1)
    # Recompute daily cash returns at the identical per-selection stake convention.
    d['pnl'] = (a.won*a.odds-1).groupby(a.day).sum()
    d['new_pnl'] = (b.won*b.odds-1).groupby(b.day).sum()
    if d.isna().any().any(): raise ValueError('Coverage mismatch')
    changes = d[['new_won','new_pnl']].to_numpy()-d[['won','pnl']].to_numpy()
    rng=np.random.default_rng(149)
    boot=changes[rng.integers(0,len(d),(draws,len(d)))].sum(axis=1)
    return dict(days=len(d),extra_wins=int(changes[:,0].sum()),
                extra_profit_units=float(changes[:,1].sum()),
                ci95_extra_wins=np.quantile(boot[:,0],[.025,.975]).tolist(),
                ci95_extra_profit_units=np.quantile(boot[:,1],[.025,.975]).tolist())


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--stage',choices=['validation','final'],required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    f,manifest=load(a.data_dir,a.stage=='final')
    if a.stage=='validation':
        train=f[f.season.isin(SEASONS[:4])]; val=f[f.season=='2425']
        params=fit(train)
        report={m:dict(forecast=scores(val,predict(val,m,params)),
                       top3=selection_summary(selected(val,predict(val,m,params)))) for m in MODELS}
        chosen=min(MODELS,key=lambda m:report[m]['forecast']['logloss'])
        frozen=dict(chosen=chosen,params=params,validation=report,train_n=len(train),validation_n=len(val),
                    rule='minimum validation log loss; no final-test outcomes inspected',manifest=manifest)
        (a.out/'frozen_model.json').write_text(json.dumps(frozen,indent=2))
        print(json.dumps({k:v for k,v in frozen.items()if k not in ['manifest']},indent=2))
    else:
        frozen=json.loads((a.out/'frozen_model.json').read_text());test=f[f.season=='2526']
        names=list(dict.fromkeys(['proportional',frozen['chosen']]))
        report={m:dict(forecast=scores(test,predict(test,m,frozen['params'])),
                       top3=selection_summary(selected(test,predict(test,m,frozen['params']))))for m in names}
        base=selected(test,predict(test,'proportional',frozen['params']))
        new=selected(test,predict(test,frozen['chosen'],frozen['params']))
        result=dict(chosen=frozen['chosen'],test_season='2526',report=report,paired=paired(base,new),manifest=manifest,
                    limitations=['recorded close-time quotes, not morning decisions or accepted fills',
                                 'European soccer outright markets, not site-specific props or double-chance odds',
                                 'best named-book return assumes access to the recorded quotes without slippage'])
        (a.out/'final_results.json').write_text(json.dumps(result,indent=2))
        base.to_csv(a.out/'baseline_test_picks.csv',index=False);new.to_csv(a.out/'candidate_test_picks.csv',index=False)
        print(json.dumps({k:v for k,v in result.items()if k!='manifest'},indent=2))


if __name__=='__main__':main()
