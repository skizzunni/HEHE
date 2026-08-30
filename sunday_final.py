"""Sunday 8/30 final board (10:48p snapshot), with line movement since 7:26p."""
from parlay_math import american_to_decimal, decimal_to_american
from statistics import median

def devig(a, b):
    pa, pb = 1/american_to_decimal(a), 1/american_to_decimal(b)
    t = pa+pb
    return pa/t, pb/t, t-1

# away, away_ml, home, home_ml, rl_fav, fav_rl, dog_rl, total, time, prior_ml_pair
G = [
 ("MIA Marlins",-110,"WSH Nationals",-110,"a",+145,-180,9.0,"12:15p",(-110,-110)),
 ("COL Rockies",+185,"ATL Braves",-225,"h",-105,-115,8.5,"1:35p",(+185,-225)),
 ("BOS Red Sox",-115,"NY Yankees",-105,"a",+145,-180,8.0,"1:35p",(-115,-105)),
 ("SEA Mariners",-130,"TOR Blue Jays",+110,"a",+130,-160,8.0,"1:37p",None),
 ("SD Padres",+145,"TB Rays",-175,"h",+130,-160,7.5,"1:40p",(+140,-170)),
 ("LA Dodgers",-165,"DET Tigers",+135,"a",+110,-135,7.5,"1:40p",(-165,+135)),
 ("KC Royals",+155,"CLE Guardians",-190,"h",+120,-145,7.5,"1:40p",(+155,-190)),
 ("CWS White Sox",+100,"MIN Twins",-120,"h",+160,-200,8.5,"2:10p",None),
 ("TEX Rangers",+140,"MIL Brewers",-170,"h",+125,-150,8.5,"2:10p",(+140,-170)),
 ("PIT Pirates",-115,"STL Cardinals",-105,"a",+140,-170,8.0,"2:15p",(-120,+100)),
 ("HOU Astros",+105,"NY Mets",-125,"h",+160,-200,9.0,"3:10p",(+100,-120)),
 ("BAL Orioles",-155,"Athletics",+130,"a",+100,-120,10.5,"4:05p",(-155,+130)),
 ("PHI Phillies",-195,"LA Angels",+160,"a",-110,-110,8.0,"4:07p",(-195,+160)),
 ("CIN Reds",+115,"CHI Cubs",-140,"h",+150,-185,9.0,"7:20p",(+120,-145)),
]

print("="*94)
print("LINE MOVEMENT, 7:26p -> 10:48p")
print("="*94)
moves = []
for a,aml,h,hml,rlf,frl,drl,tot,t,prior in G:
    if prior is None:
        print(f"  {a+' @ '+h:<34} NEW to the board")
        continue
    pa0,ph0,_ = devig(*prior)
    pa1,ph1,_ = devig(aml,hml)
    d = (pa1-pa0)*100
    if abs(d) < 0.3:
        print(f"  {a+' @ '+h:<34} unchanged")
    else:
        side = a if d>0 else h
        print(f"  {a+' @ '+h:<34} {abs(d):.1f} pts toward {side}"
              f"   ({prior[0]:+} -> {aml:+})")
        moves.append((a,h,side,abs(d)))

print("\n"+"="*94)
print("SUNDAY BOARD -- 14 GAMES")
print("="*94)
R=[]
for a,aml,h,hml,rlf,frl,drl,tot,t,_ in G:
    pa,ph,hold = devig(aml,hml)
    fav,dog,fp = (a,h,pa) if rlf=="a" else (h,a,ph)
    cov,_,_ = devig(frl,drl)
    R.append(dict(a=a,h=h,fav=fav,dog=dog,fp=fp,cov=cov,ratio=cov/fp,
                  tot=tot,t=t,hold=hold))

n=len(R)
def corr(xs,ys):
    mx,my=sum(xs)/n,sum(ys)/n
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/((sum((x-mx)**2 for x in xs)**.5)*(sum((y-my)**2 for y in ys)**.5))
ra=[r["ratio"] for r in R]; to=[r["tot"] for r in R]; fp=[r["fp"] for r in R]
mx1,mx2,my=sum(to)/n,sum(fp)/n,sum(ra)/n
x1=[v-mx1 for v in to]; x2=[v-mx2 for v in fp]; y=[v-my for v in ra]
s11=sum(v*v for v in x1); s22=sum(v*v for v in x2); s12=sum(p*q for p,q in zip(x1,x2))
s1y=sum(p*q for p,q in zip(x1,y)); s2y=sum(p*q for p,q in zip(x2,y))
det=s11*s22-s12*s12; b1=(s22*s1y-s12*s2y)/det; b2=(s11*s2y-s12*s1y)/det
res=[(r, r["ratio"]-(my+b1*(r["tot"]-mx1)+b2*(r["fp"]-mx2))) for r in R]
sd=(sum(d*d for _,d in res)/n)**.5

for r in sorted(R,key=lambda r:-r["fp"]):
    d=dict(res)[id(r)] if False else [x for rr,x in res if rr is r][0]
    tag=""
    if d>1.5*sd: tag="  ML cheap vs run line"
    elif d<-1.5*sd: tag=f"  grinder - {r['dog']} live"
    print(f"  {r['fav']:<16}{r['fp']*100:5.1f}%  {r['t']:>7}  resid {d:+.3f}{tag}")
print(f"\n  residual SD {sd:.3f}")
