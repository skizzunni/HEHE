"""TOUR Championship R4 two-balls: 10:49p board vs the 7:53p open."""
import math
from parlay_math import american_to_decimal

def devig(a,b):
    pa,pb=1/american_to_decimal(a),1/american_to_decimal(b)
    t=pa+pb
    return pa/t,pb/t,t-1

def probit(p):
    a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,
       1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00]
    b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,
       6.680131188771972e+01,-1.328068155288572e+01]
    q=p-0.5; r=q*q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/ \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

SIGMA=4.10
# tee, A, B, (openA,openB), (nowA,nowB)
M=[
 ("11:02a","Patrick Cantlay","Kristoffer Reitan",(-175,+140),(-175,+125)),
 ("11:14a","Hideki Matsuyama","Robert Macintyre",(-140,+100),(-140,+100)),
 ("11:26a","Gary Woodland","Akshay Bhatia",(-150,+115),(-150,+115)),
 ("11:38a","Xander Schauffele","Ryan Fox",(-250,+185),(-250,+185)),
 ("11:56a","Collin Morikawa","Tom Kim",(-150,+115),(-150,+115)),
 ("12:08p","Tommy Fleetwood","Alex Fitzpatrick",(-185,+140),(-185,+140)),
 ("12:20p","Wyndham Clark","Matt Fitzpatrick",(-115,-115),(-125,-105)),
 ("12:32p","Si Woo Kim","Justin Rose",(-150,+110),(-150,+120)),
 ("12:44p","Sam Burns","Jacob Bridgeman",(-175,+140),(-175,+140)),
 ("1:02p","Russell Henley","Min Woo Lee",(-150,+115),(-150,+115)),
 ("1:14p","Rory McIlroy","Cameron Young",(-140,+100),(-150,+115)),
 ("1:26p","Scottie Scheffler","Chris Gotterup",(-230,+165),(-230,+165)),
 ("1:38p","Ludvig Aberg","Adam Scott",(-165,+115),(-165,+115)),
 ("1:50p","Viktor Hovland","Ryan Gerard",(-140,+105),(-125,-105)),
]

print("="*92)
print("LINE MOVEMENT 7:53p -> 10:49p")
print("="*92)
for tee,A,B,op,nw in M:
    p0,_,h0=devig(*op); p1,_,h1=devig(*nw)
    d=(p1-p0)*100
    if abs(d)<0.4:
        continue
    who=A if d>0 else B
    print(f"  {A} v {B:<20} {abs(d):5.1f} pts -> {who:<18}"
          f"  ({A} {op[0]:+} -> {nw[0]:+})")

print("\n"+"="*92)
print("FINAL BOARD")
print("="*92)
print(f"  {'FAVORITE':<20}{'DOG':<20}{'FAIR%':>7}{'SG/RD':>8}{'HOLD':>7}{'MOVE':>8}")
rows=[]
for tee,A,B,op,nw in M:
    pa,pb,hold=devig(*nw)
    fav,fp,dog=(A,pa,B) if pa>=pb else (B,pb,A)
    p0a,_,_=devig(*op)
    mv=(pa-p0a)*100
    gap=probit(fp)*SIGMA
    rows.append((fav,dog,fp,gap,hold,mv,tee,A))
    print(f"  {fav:<20}{dog:<20}{fp*100:6.1f}%{gap:+8.2f}{hold*100:6.1f}%{mv:+8.1f}")

print("\n"+"="*92)
print("RANKED")
print("="*92)
for fav,dog,fp,gap,hold,mv,tee,A in sorted(rows,key=lambda r:-r[2]):
    print(f"  {fav:<20}{fp*100:5.1f}%  SG{gap:+5.2f}  hold {hold*100:4.1f}%  {tee:>7}")

hs=[r[4] for r in rows]
o=1+sum(hs)/len(hs)
print(f"\n  average hold now {(o-1)*100:.2f}%")
p=1.0
for i,r in enumerate(sorted(rows,key=lambda r:-r[2]),1):
    p*=r[2]
    if i in (1,2,3,14):
        print(f"  top {i:>2}: {p*100:.4f}%")


def decompose():
    """Separate a genuine line move from a hold change.

    If the favorite's own price shortens, money came in on the favorite.
    If only the dog's price moves, the book re-cut its margin and the
    de-vigged probability shifts as an artifact -- no information in it.
    """
    print("\n" + "=" * 92)
    print("REAL MOVES vs HOLD ARTIFACTS")
    print("=" * 92)
    for tee, A, B, op, nw in M:
        fav_moved = op[0] != nw[0]
        dog_moved = op[1] != nw[1]
        if not (fav_moved or dog_moved):
            continue
        _, _, h0 = devig(*op)
        _, _, h1 = devig(*nw)
        p0, _, _ = devig(*op)
        p1, _, _ = devig(*nw)
        print(f"\n  {A} v {B}")
        print(f"    {A}: {op[0]:+} -> {nw[0]:+}    {B}: {op[1]:+} -> {nw[1]:+}")
        print(f"    hold {h0*100:.1f}% -> {h1*100:.1f}%     "
              f"fair {p0*100:.1f}% -> {p1*100:.1f}%")
        if fav_moved:
            direction = A if nw[0] < op[0] else B
            print(f"    REAL MOVE -- money on {direction}")
        else:
            print(f"    HOLD CHANGE ONLY -- book re-cut its margin, no signal")


decompose()
