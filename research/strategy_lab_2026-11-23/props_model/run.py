"""Out-of-sample test of the player model vs. book implied chance on graded NBA
props in props.json. Split by date: H1 = dates < SPLIT, H2 = dates >= SPLIT.
Fit (minutes / usage coefficients for teammates out, Platt calibration) on one
half, test on the other, both directions."""
import collections, datetime as dt, json, math, os, re, sys
import numpy as np
from model import *

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)
import props_ledger as PL      # read-only: box_stats, resolve
SPLIT = "2026-11-06"           # median NBA graded-prop date (16 dates before, 17 on/after)

games = load_games(); db = DB(games)
print("games", len(games), "league msd", round(db.msd, 2), "phi", {k: round(v, 2) for k, v in db.phi.items()})

def gdate(start):  # ESPN UTC start -> US local game date
    return (dt.datetime.fromisoformat(start.replace("Z", "+00:00")) - dt.timedelta(hours=6)).date().isoformat()

# ---- join props to ESPN athlete ids
book = json.load(open(os.path.join(ROOT, "props.json")))
raw = {}
props, miss = [], collections.Counter()
for k, e in book.items():
    if e.get("league") != "nba" or e.get("status") not in ("won", "lost"): continue
    if e["market"] not in COMBO: miss["market"] += 1; continue
    m = re.match(r"^(\d+)\+$", str(e["line"]))
    if not m: miss["line"] += 1; continue
    gid = e["gid"]; G = games.get(gid)
    if not G: miss["no game"] += 1; continue
    if gid not in raw:
        raw[gid] = PL.box_stats(json.load(open(os.path.join(CUR, gid.replace(":", "-") + ".json"))))
    st, how = PL.resolve(raw[gid], e)
    aid = next((a for a, v in raw[gid].items() if v is st and not a.startswith(("name:", "_"))), None) if st is not None else None
    if aid is None: miss["unresolved"] += 1; continue
    rec = next((ro[aid] for ro in G["teams"].values() if aid in ro), None)
    if rec is None or not rec["played"]: miss["not played"] += 1; continue
    x = sum(rec[s] for s in COMBO[e["market"]])
    y = 1 if e["status"] == "won" else 0
    pr = float(e["price"]); dec = 1 + 100 / -pr if pr <= -100 else 1 + pr / 100
    imp = e.get("imp") if isinstance(e.get("imp"), (int, float)) else 1 / dec
    if not isinstance(e.get("imp"), (int, float)): miss["imp from price"] += 1
    if (x >= int(m.group(1))) != bool(y): miss["grade mismatch"] += 1
    props.append(dict(key=k, date=e["date"], aid=aid, team=rec["team"], pos=rec["pos"], start=G["start"], gid=gid,
                      market=e["market"], line=int(m.group(1)), imp=imp, price=e["price"], y=y, dec=dec,
                      p_bot=e.get("p")))
print("props joined", len(props), dict(miss))

# ---- per player-game raw features (adjustment-free) for fitting c1/c2
P0 = dict(c1=0.0, c2={s: 0.0 for s in BASE})
feat_cache = {}
def feats(aid, team, pos, start, gid):
    k = (aid, gid)
    if k not in feat_cache:
        cur, prev = db.history(aid, start)
        fm, fu = db.teammates_delta(aid, team, start, gid)
        feat_cache[k] = (cur, prev, fm, fu, project(cur, prev, pos, fm, fu, P0, db.pos_rate, db.phi, db.msd, db.low_share))
    return feat_cache[k]

pg = []   # current-season player-games with >= 3 prior games this season
for gid, G in games.items():
    if G["season"] != "2627": continue
    for team, ro in G["teams"].items():
        for aid, r in ro.items():
            if not r["played"]: continue
            cur, prev, fm, fu, pj = feats(aid, team, r["pos"], G["start"], gid)
            if len(cur) < 3: continue
            pg.append(dict(date=gdate(G["start"]), r=r, fm=fm, fu=fu, pj=pj))
print("player-games for fitting", len(pg))

def fit_adj(rows):
    x = np.array([q["fm"] * q["pj"]["m0"] / 240 for q in rows]); yv = np.array([q["r"]["min"] - q["pj"]["m0"] for q in rows])
    c1 = float((x * yv).sum() / (x * x).sum())
    c2 = {}
    for s in BASE:
        e = np.array([q["r"][s] - q["pj"]["rate"][s] * q["r"]["min"] for q in rows])
        z = np.array([q["pj"]["rate"][s] * q["r"]["min"] * q["fu"] for q in rows])
        c2[s] = float((e * z).sum() / (z * z).sum())
    return dict(c1=c1, c2=c2)

def logit(p): p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); return np.log(p / (1 - p))
def platt(p, y, iters=50):
    X = np.c_[np.ones(len(p)), logit(np.array(p))]; y = np.array(y, float); b = np.array([0.0, 1.0])
    for _ in range(iters):
        q = 1 / (1 + np.exp(-X @ b)); W = q * (1 - q)
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(2); b = b + np.linalg.solve(H, X.T @ (y - q))
    return b
def apply(b, p): return 1 / (1 + np.exp(-(b[0] + b[1] * logit(np.array(p)))))

def score(p, y):
    p = np.clip(np.array(p, float), 1e-4, 1 - 1e-4); y = np.array(y, float)
    return dict(brier=round(float(((p - y) ** 2).mean()), 4), logloss=round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4))

def rule_stat(rows, side="over"):
    n = len(rows)
    if not n: return dict(n=0)
    w = sum(r["y"] for r in rows); ex = sum(r["imp"] for r in rows); var = sum(r["imp"] * (1 - r["imp"]) for r in rows)
    roi = (sum(r["y"] * r["dec"] for r in rows) - n) / n
    return dict(n=n, hit=round(100 * w / n, 1), imp=round(100 * ex / n, 1), z=round((w - ex) / math.sqrt(var), 2) if var else None,
                roi=round(100 * roi, 1) if side == "over" else None)

halves = {"H1": [q for q in props if q["date"] < SPLIT], "H2": [q for q in props if q["date"] >= SPLIT]}
pgh = {"H1": [q for q in pg if q["date"] < SPLIT], "H2": [q for q in pg if q["date"] >= SPLIT]}
OUT = dict(split=SPLIT, joined=len(props), miss=dict(miss), halves={})
ALLTEST = []
for test, fit in (("H2", "H1"), ("H1", "H2")):
    P = fit_adj(pgh[fit])
    def model_p(q):
        cur, prev, fm, fu, _ = feats(q["aid"], q["team"], q["pos"], q["start"], q["gid"])
        pj = project(cur, prev, q["pos"], fm, fu, P, db.pos_rate, db.phi, db.msd, db.low_share)
        return p_reach(pj, q["market"], q["line"]), len(cur)
    for h in (fit, test):
        for q in halves[h]:
            q["p_raw_" + fit], q["ncur"] = model_p(q)
    F, T = halves[fit], halves[test]
    bm = platt([q["p_raw_" + fit] for q in F], [q["y"] for q in F])
    bk = platt([q["imp"] for q in F], [q["y"] for q in F])
    # stack: y ~ a + b*logit(imp) + c*logit(model_raw), fit on fit half
    Xf = np.c_[np.ones(len(F)), logit([q["imp"] for q in F]), logit([q["p_raw_" + fit] for q in F])]
    yf = np.array([q["y"] for q in F], float); bs = np.zeros(3)
    for _ in range(50):
        qq = 1 / (1 + np.exp(-Xf @ bs)); W = qq * (1 - qq)
        bs = bs + np.linalg.solve(Xf.T @ (Xf * W[:, None]) + 1e-6 * np.eye(3), Xf.T @ (yf - qq))
    for q in T:
        q["ps"] = float(1 / (1 + np.exp(-(bs[0] + bs[1] * logit([q["imp"]])[0] + bs[2] * logit([q["p_raw_" + fit]])[0]))))
    for q in T:
        q["pm"] = float(apply(bm, [q["p_raw_" + fit]])[0]); q["pk"] = float(apply(bk, [q["imp"]])[0]); q["test"] = test
    y = [q["y"] for q in T]
    res = dict(fit_on=fit, n_test=len(T), n_fit=len(F), adj=P, platt_model=[round(v, 3) for v in bm], platt_imp=[round(v, 3) for v in bk],
               hit=round(100 * np.mean(y), 1), mean_imp=round(100 * np.mean([q["imp"] for q in T]), 1),
               model_cal=score([q["pm"] for q in T], y), model_raw=score([q["p_raw_" + fit] for q in T], y),
               imp_withvig=score([q["imp"] for q in T], y), imp_recal=score([q["pk"] for q in T], y),
               stack_imp_model=score([q["ps"] for q in T], y), stack_coef=[round(float(v), 3) for v in bs],
               raw_calib=[(a, b, len(S), round(float(np.mean([q["y"] for q in S])), 3), round(float(np.mean([q["p_raw_" + fit] for q in S])), 3))
                          for a, b in [(0, .6), (.6, .8), (.8, .9), (.9, .95), (.95, .98), (.98, 1.01)]
                          for S in [[q for q in T if a <= q["p_raw_" + fit] < b]] if S],
               bot_p=score([q["p_bot"] for q in T], y),
               mean_model=round(100 * np.mean([q["pm"] for q in T]), 1),
               corr_model_imp=round(float(np.corrcoef([q["pm"] for q in T], [q["imp"] for q in T])[0, 1]), 3))
    # with >=5 current-season prior games only
    T5 = [q for q in T if q["ncur"] >= 5]
    res["n_test_hist5"] = len(T5)
    res["model_cal_hist5"] = score([q["pm"] for q in T5], [q["y"] for q in T5]); res["imp_hist5"] = score([q["imp"] for q in T5], [q["y"] for q in T5])
    rules = {}
    for thr in (0.03, 0.05, 0.08):
        rules[f"over edge>={int(thr*100)}"] = rule_stat([q for q in T if q["pm"] - q["imp"] >= thr])
        rules[f"under signal (model over < imp-{int(thr*100)})"] = rule_stat([q for q in T if q["imp"] - q["pm"] >= thr], side="under")
    res["rules"] = rules
    bym = {}
    for mk in COMBO:
        R = [q for q in T if q["market"] == mk]
        if not R: continue
        bym[mk] = dict(n=len(R), model=score([q["pm"] for q in R], [q["y"] for q in R]), imp=score([q["imp"] for q in R], [q["y"] for q in R]),
                       edge5=rule_stat([q for q in R if q["pm"] - q["imp"] >= 0.05]))
    res["by_market"] = bym
    OUT["halves"][test] = res
    ALLTEST += T

# line height: tercile of line within market (cut points from all props, line only, no outcomes)
cuts = {}
for mk in COMBO:
    ls = sorted(q["line"] for q in props if q["market"] == mk)
    if ls: cuts[mk] = (ls[len(ls) // 3], ls[2 * len(ls) // 3])
def lh(q):
    a, b = cuts[q["market"]]; return "low" if q["line"] <= a else ("mid" if q["line"] <= b else "high")
byl = {}
for h in ("H1", "H2"):
    for band in ("low", "mid", "high"):
        R = [q for q in ALLTEST if q["test"] == h and lh(q) == band]
        byl[f"{h} {band}"] = dict(n=len(R), model=score([q["pm"] for q in R], [q["y"] for q in R]), imp=score([q["imp"] for q in R], [q["y"] for q in R]),
                                  edge5=rule_stat([q for q in R if q["pm"] - q["imp"] >= 0.05]))
OUT["line_cuts"] = cuts; OUT["by_line"] = byl
# market x edge>=5 per half for "both halves" verdict, plus edge>=3 by market
verd = []
for name, pred in [(f"over edge>={t}", (lambda t: lambda q: q["pm"] - q["imp"] >= t / 100)(t)) for t in (3, 5, 8)] + \
        [(f"{mk} edge>={t}", (lambda mk, t: lambda q: q["market"] == mk and q["pm"] - q["imp"] >= t / 100)(mk, t)) for mk in COMBO for t in (3, 5, 8)] + \
        [(f"{b} line edge>={t}", (lambda b, t: lambda q: lh(q) == b and q["pm"] - q["imp"] >= t / 100)(b, t)) for b in ("low", "mid", "high") for t in (3, 5)]:
    s1 = rule_stat([q for q in ALLTEST if q["test"] == "H1" and pred(q)]); s2 = rule_stat([q for q in ALLTEST if q["test"] == "H2" and pred(q)])
    if not s1.get("n") or not s2.get("n"): v = "no sample"
    elif s1["z"] is not None and s2["z"] is not None and min(s1["z"], s2["z"]) >= 2.8 and s1["roi"] > 0 and s2["roi"] > 0: v = "ADOPTED"
    elif s1["roi"] > 0 and s2["roi"] > 0: v = "on watch"
    else: v = "rejected"
    verd.append(dict(rule=name, H1=s1, H2=s2, verdict=v))
OUT["verdicts"] = verd
json.dump(OUT, open(os.path.join(HERE, "results.json"), "w"), indent=1)
json.dump([{k: q[k] for k in ("key", "date", "market", "line", "imp", "price", "y", "pm", "test", "ncur")} for q in ALLTEST],
          open(os.path.join(HERE, "test_predictions.json"), "w"))

L = [f"NBA props model test. split {SPLIT}. joined {len(props)} {dict(miss)}. imp = with-vig (overs only; no under prices exist)."]
for h, r in OUT["halves"].items():
    L.append(f"\n== test {h} (fit on {r['fit_on']}, n_fit {r['n_fit']}, n_test {r['n_test']})  hit {r['hit']}%  mean imp {r['mean_imp']}%  mean model {r['mean_model']}%  corr(model,imp) {r['corr_model_imp']}")
    L.append(f"   adj c1={r['adj']['c1']:.3f} c2={ {k: round(v, 3) for k, v in r['adj']['c2'].items()} }  platt model {r['platt_model']} imp {r['platt_imp']}")
    L.append(f"   stack coef [a, b_imp, c_model] {r['stack_coef']}   raw-model calibration (lo, hi, n, hit, mean p_raw): {r['raw_calib']}")
    for k in ("model_cal", "model_raw", "imp_withvig", "imp_recal", "stack_imp_model", "bot_p"):
        L.append(f"   {k:<12} brier {r[k]['brier']:.4f}  logloss {r[k]['logloss']:.4f}")
    L.append(f"   >=5 cur-season games (n {r['n_test_hist5']}): model {r['model_cal_hist5']}  imp {r['imp_hist5']}")
    for k, s in r["rules"].items(): L.append(f"   {k:<40} {s}")
    for mk, s in r["by_market"].items():
        L.append(f"   {mk:<16} n {s['n']:<4} model {s['model']['brier']:.4f}/{s['model']['logloss']:.4f}  imp {s['imp']['brier']:.4f}/{s['imp']['logloss']:.4f}  edge5 {s['edge5']}")
L.append("\n== line height (terciles within market) " + str(cuts))
for k, s in byl.items():
    L.append(f"   {k:<8} n {s['n']:<4} model {s['model']['brier']:.4f}/{s['model']['logloss']:.4f}  imp {s['imp']['brier']:.4f}/{s['imp']['logloss']:.4f}  edge5 {s['edge5']}")
L.append("\n== rule verdicts (ADOPTED: z>=2.8 & ROI>0 both halves; on watch: ROI>0 both halves)")
for v in verd: L.append(f"   {v['verdict']:<10} {v['rule']:<28} H1 {v['H1']}  H2 {v['H2']}")
open(os.path.join(HERE, "results.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
