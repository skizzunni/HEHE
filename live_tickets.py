"""Current, executable call recommendations at declared payout targets.

Original calls are forecasts, not quotes that remain executable all day.
This module uses separately refreshed exact-market snapshots. Payouts are
same-book price products, not sportsbook-accepted combination quotes.
"""
import datetime as dt
import itertools
import math
import re
import call_tickets as CT
import freshness
from record_eligibility import selection_leg, quote_at, quote_book, valid_price

VERSION='current-quotes-v1'
STANDARD=.75
TARGETS=(2.,3.,5.)


def book_name(name):
    key=re.sub('[^a-z0-9]','',str(name or '').lower())
    if key in ('', 'espnodds', 'espncore'):
        return None
    return {'draftkings':'DraftKings','fanduel':'FanDuel'}.get(key,str(name).strip())


def fresh(at,now):
    age=freshness.age_min(at,now)
    return age is not None and -1 <= age <= freshness.MAX_AGE_MIN


def current_quote(c,row,now):
    """New observation of the frozen call's own outcome; never change its bet."""
    import calls
    import calibration
    side=c.get('side')
    if side is None and c.get('pick','').removesuffix(' or draw')==row.get('mypick'):
        side=row.get('myside')
    exact=dict(row,myside=side,dc=bool(c.get('dc')))
    leg=selection_leg(exact) if side else None
    q={k:c.get(k) for k in ('id','league','pick','match','side','dc','start','rank')}
    q.update(checked_at=now.isoformat(timespec='seconds'),ready=False,gate=dict(c.get('gate') or {}))
    if not leg:
        q['reason']='exact selected market not quoted';return q
    at=quote_at(exact)
    # DC probabilities use the same-build 1X2 side and draw, separately
    # timestamped from the actual double-chance executable quote.
    if exact.get('dc'):
        times=[freshness.parse(x.get('at') or row.get('price_at')) for x in row.get('legs') or []
               if x.get('side') in (side,'draw')]
        prob_at=min(times).isoformat() if len(times)==2 and all(times) else None
    else:
        prob_at=at
    p=calls._row_chance(row,side,bool(c.get('dc')))
    if p is None and row.get('myside')==side and bool(row.get('dc'))==bool(c.get('dc')):
        p=row.get('myconf')
    conf,note=calibration.publisher(now.astimezone(calls._ET).date().isoformat()).publish(c['league'],p)
    q.update(side=side,price=leg.get('price'),book=book_name(quote_book(exact)),price_at=at,
             prob_at=prob_at,conf=conf,calib=note,price_market='double_chance' if c.get('dc') else 'moneyline',
             price_ref=leg.get('fd') or leg.get('dk'))
    if not q['gate'].get('ok'):
        q['reason']=q['gate'].get('what') or 'lineup/news inputs not confirmed'
    elif not fresh(at,now) or not fresh(prob_at,now):
        q['reason']='price or probability inputs are stale or untimed'
    elif not q['book']:
        q['reason']='sportsbook not identified'
    elif conf is None or not math.isfinite(conf) or not 0 < conf < 100:
        q['reason']='probability unavailable'
    else:
        news_at=freshness.parse(c.get('news_at'))
        if news_at and (freshness.parse(at)<=news_at or freshness.parse(prob_at)<=news_at):
            q['reason']='awaiting this game\'s price after its lineup/news change'
        else:
            q['ready']=True
    return q


def eligible(calls_today,now,standard=STANDARD):
    ready=[];excluded=[]
    for c in calls_today:
        q=dict(c.get('current') or {})
        why=[]
        if c.get('status') not in (None,'open','scheduled'):
            why.append('call is settled, void or pulled')
        start=freshness.parse(c.get('start'))
        if start is None or start<=now:
            why.append('game started or start unknown')
        if not q or not q.get('ready') or not (q.get('gate') or {}).get('ok'):
            why.append(q.get('reason') or 'current confirmed inputs unavailable')
        if not valid_price(q.get('price')) or not fresh(q.get('price_at'),now) or not fresh(q.get('prob_at'),now):
            why.append('fresh exact-market price/probability unavailable')
        if not book_name(q.get('book')):
            why.append('sportsbook not identified')
        if q.get('id')!=c.get('id') or (c.get('side') and q.get('side')!=c.get('side')) or bool(q.get('dc'))!=bool(c.get('dc')):
            why.append('quote outcome differs from the original call')
        p=q.get('conf')
        if not isinstance(p,(int,float)) or not math.isfinite(p) or not standard*100<=p<100:
            why.append(f'below {100*standard:g}% leg standard or probability invalid')
        if why:
            excluded.append(dict(id=c['id'],pick=c.get('pick'),reasons=list(dict.fromkeys(why))))
        else:
            q['book']=book_name(q['book']);ready.append(q)
    return ready,excluded


def choices(pool,max_legs=3):
    """Exhaustive search: the daily call pool has at most five events."""
    for n in range(2,min(max_legs,len(pool))+1):
        for legs in itertools.combinations(pool,n):
            books={L['book'] for L in legs}
            if len(books)!=1:
                continue
            seen=set();valid=True
            for L in legs:
                d=CT.drivers(L)
                if seen & d:
                    valid=False;break
                seen.update(d)
            if not valid:
                continue
            joint=math.prod(L['conf']/100 for L in legs)*CT.PENALTY**(n-1)
            payout=math.prod(CT.dec(L['price']) for L in legs)
            yield dict(legs=list(legs),joint=joint,payout=payout,value=joint*payout-1,
                       book=legs[0]['book'],penalty=CT.PENALTY)


def build(calls_today,now=None,standard=STANDARD,targets=TARGETS,max_legs=3):
    now=now or dt.datetime.now(dt.timezone.utc)
    pool,excluded=eligible(calls_today,now,standard)
    combos=list(choices(pool,max_legs))
    rows=[]
    for target in targets:
        valid=[t for t in combos if t['payout']>=target-1e-12]
        best=max(valid,key=lambda t:(t['joint'],t['value'],-len(t['legs']))) if valid else None
        rows.append(dict(target=target,ticket=best,ceiling=max((t['payout'] for t in combos),default=None)))
    return dict(version=VERSION,as_of=now.isoformat(timespec='seconds'),standard=standard,max_legs=max_legs,
                payout_basis='estimated same-book price product; not an accepted combo quote',
                ready=len(pool),excluded=excluded,targets=rows)


def strongest(pool,target,max_legs=3):
    """Declared comparison baseline: strongest first at the SAME payout."""
    candidates=[]
    for book in sorted({L['book'] for L in pool}):
        picked=[];seen=set()
        for L in sorted((x for x in pool if x['book']==book),key=lambda x:-x['conf']):
            if len(picked)>=max_legs:
                break
            d=CT.drivers(L)
            if seen & d:
                continue
            picked.append(L);seen.update(d)
            if len(picked)>=2 and math.prod(CT.dec(x['price']) for x in picked)>=target:
                candidates.extend(choices(picked,max_legs=len(picked)))
                # The baseline is this entire prefix, not its best subset.
                candidates=[t for t in candidates if t['book']!=book or len(t['legs'])==len(picked)]
                break
    candidates=[t for t in candidates if t['payout']>=target]
    return max(candidates,key=lambda t:t['joint']) if candidates else None
