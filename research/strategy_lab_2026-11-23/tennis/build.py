"""Build point-in-time features for every ATP/WTA match in tennis-data.co.uk files.

Input : data/td_{atp,wta}_{2015..2026}.xlsx  (2015-2017 are warm-up history only)
        nat/{atp,wta}_players.csv              (nationality / hand, Sackmann archive)
Output: sides.pkl  -- two rows per bettable match (one per player), every feature
        computed from matches on EARLIER dates only.

No look-ahead: matches are processed one calendar date at a time; all features for
the date are read from state first, then the date's results update the state.
"""
import glob, math, os, re, sys, unicodedata
from collections import defaultdict
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))

LOC = {"'s-Hertogenbosch": "NED", "Abu Dhabi": "UAE", "Acapulco": "MEX", "Adelaide": "AUS", "Almaty": "KAZ",
       "Antalya": "TUR", "Antwerp": "BEL", "Athens": "GRE", "Atlanta": "USA", "Auckland": "NZL", "Austin": "USA",
       "Bad Gastein": "AUT", "Bad Homburg": "GER", "Baku": "AZE", "Banja Luka": "BIH", "Barcelona": "ESP",
       "Basel": "SUI", "Bastad": "SWE", "Beijing": "CHN", "Belgrade": "SRB", "Berlin": "GER", "Biel": "SUI",
       "Birmingham": "GBR", "Bogota": "COL", "Brisbane": "AUS", "Brussels": "BEL", "Bucharest": "ROU",
       "Budapest": "HUN", "Buenos Aires": "ARG", "Cagliari": "ITA", "Cancun": "MEX", "Casablanca": "MAR",
       "Charleston": "USA", "Chengdu": "CHN", "Chennai": "IND", "Chicago": "USA", "Cincinnati": "USA",
       "Cleveland": "USA", "Cluj-Napoca": "ROU", "Cologne": "GER", "Cordoba": "ARG", "Courmayeur": "ITA",
       "Dallas": "USA", "Delray Beach": "USA", "Doha": "QAT", "Dubai": "UAE", "Eastbourne": "GBR",
       "Estoril": "POR", "Florence": "ITA", "Florianopolis": "BRA", "Fort Worth": "USA", "Gdynia": "POL",
       "Geneva": "SUI", "Gijon": "ESP", "Granby": "CAN", "Gstaad": "SUI", "Guadalajara": "MEX",
       "Guangzhou": "CHN", "Halle": "GER", "Hamburg": "GER", "Hangzhou": "CHN", "Hiroshima": "JPN",
       "Hobart": "AUS", "Hong Kong": "HKG", "Houston": "USA", "Hua Hin": "THA", "Iasi": "ROU",
       "Indian Wells": "USA", "Istanbul": "TUR", "Jiujiang": "CHN", "Jurmala": "LAT", "Kaohsiung": "TPE",
       "Katowice": "POL", "Kitzbuhel": "AUT", "Kuala Lumpur": "MAS", "Lausanne": "SUI", "Lexington": "USA",
       "Linz": "AUT", "London": "GBR", "Los Cabos": "MEX", "Lugano": "SUI", "Luxembourg": "LUX", "Lyon": "FRA",
       "Madrid": "ESP", "Mallorca": "ESP", "Marbella": "ESP", "Marrakech": "MAR", "Marrakesh": "MAR",
       "Marseille": "FRA", "Melbourne": "AUS", "Memphis": "USA", "Merida": "MEX", "Metz": "FRA", "Miami": "USA",
       "Monastir": "TUN", "Monte Carlo": "MON", "Monterrey": "MEX", "Montpellier": "FRA", "Montreal": "CAN",
       "Moscow": "RUS", "Munich": "GER", "Nanchang": "CHN", "Napoli": "ITA", "New Haven": "USA",
       "New York": "USA", "Newport": "USA", "Nice": "FRA", "Ningbo": "CHN", "Nottingham": "GBR",
       "Nur-Sultan": "KAZ", "Astana": "KAZ", "Nürnberg": "GER", "Nurnberg": "GER", "Osaka": "JPN",
       "Ostrava": "CZE", "Palermo": "ITA", "Paris": "FRA", "Parma": "ITA", "Pattaya": "THA", "Portoroz": "SLO",
       "Prague": "CZE", "Pune": "IND", "Quebec": "CAN", "Queens Club": "GBR", "Quito": "ECU", "Rabat": "MAR",
       "Rio de Janeiro": "BRA", "Riyadh": "KSA", "Rome": "ITA", "Rotterdam": "NED", "Rouen": "FRA",
       "San Diego": "USA", "San Jose": "USA", "Santiago": "CHI", "Sao Paulo": "BRA", "Sardinia": "ITA",
       "Seoul": "KOR", "Shanghai": "CHN", "Shenzhen": "CHN", "Singapore": "SGP", "Sofia": "BUL",
       "St. Petersburg": "RUS", "Stanford": "USA", "Stockholm": "SWE", "Strasbourg": "FRA", "Stuttgart": "GER",
       "Sydney": "AUS", "Taipei": "TPE", "Tallinn": "EST", "Tashkent": "UZB", "Tel Aviv": "ISR",
       "Tenerife": "ESP", "Tianjin": "CHN", "Tokyo": "JPN", "Toronto": "CAN", "Turin": "ITA", "Umag": "CRO",
       "Valencia": "ESP", "Vienna": "AUT", "Warsaw": "POL", "Washington": "USA", "Winston-Salem": "USA",
       "Wuhan": "CHN", "Zagreb": "CRO", "Zhengzhou": "CHN", "Zhuhai": "CHN", "Hertogenbosch": "NED",
       "Sydney ": "AUS", "Perth": "AUS", "Rosmalen": "NED", "Mexico City": "MEX", "Bratislava": "SVK",
       "Cluj": "ROU", "Sapporo": "JPN", "Jeddah": "KSA", "Bengaluru": "IND", "Rio": "BRA", "Hamilton": "NZL",
       "Monte-Carlo": "MON", "Charlotte": "USA", "Oeiras": "POR", "Hertogenbosch ": "NED"}

ROUND = {"1st Round": 1, "2nd Round": 2, "3rd Round": 3, "4th Round": 4, "Quarterfinals": 5,
         "Semifinals": 6, "The Final": 7, "Round Robin": 5}


def tier_of(s):
    s = str(s)
    if s == "Grand Slam":
        return "GS"
    if s in ("Masters 1000", "Masters", "Premier Mandatory", "Premier 5", "WTA1000"):
        return "1000"
    if s in ("ATP500", "International Gold", "Premier", "WTA500"):
        return "500"
    if s in ("ATP250", "International") or s.startswith("WTA2"):   # 'WTA251'.. are typos in 2021 file
        return "250"
    if s in ("Masters Cup", "Tour Championships"):
        return "Finals"
    return "other"


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[-'`.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def td_key(name):
    """'Davidovich Fokina A.' -> ('davidovich fokina', 'a')"""
    name = str(name).strip()
    m = re.match(r"^(.*\S)\s+([A-Za-z][A-Za-z.\- ]*\.)$", name)
    if m:
        return norm(m.group(1)), norm(m.group(2))[:1]
    parts = name.split()
    return norm(" ".join(parts[:-1])) if len(parts) > 1 else norm(name), norm(parts[-1])[:1] if len(parts) > 1 else ""


def load_players(tour):
    df = pd.read_csv(os.path.join(HERE, "nat", f"{tour}_players.csv"), dtype=str)
    df = df[(df.dob.fillna("19800000").str[:4].astype(float) >= 1970)]
    idx = defaultdict(set)
    for r in df.itertuples():
        if not isinstance(r.name_last, str):
            continue
        fi = norm(r.name_first)[:1] if isinstance(r.name_first, str) else ""
        idx[(norm(r.name_last), fi)].add((r.ioc, r.hand))
    return idx


def lookup(idx, name):
    k = td_key(name)
    v = idx.get(k)
    if not v:   # Chinese-style 'Zhang Shuai' / swapped order fallback
        toks = k[0].split()
        if len(toks) >= 2:
            v = idx.get((" ".join(toks[1:]), toks[0][:1]))
    if v and len(v) == 1:
        return next(iter(v))
    if v and len({x[0] for x in v}) == 1:
        return (next(iter(v))[0], "U")
    return (None, None)


def load():
    frames = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "td_*_20*.xlsx"))):
        tour, yr = re.findall(r"td_(atp|wta)_(\d{4})", f)[0]
        d = pd.read_excel(f)
        d["tour"] = tour.upper()
        d["season"] = int(yr)
        if "Tier" in d and "Series" not in d:
            d["Series"] = d["Tier"]
        frames.append(d)
    m = pd.concat(frames, ignore_index=True)
    m["Date"] = pd.to_datetime(m["Date"])
    m["Location"] = m["Location"].astype(str).str.strip()
    m["rnd"] = m["Round"].map(ROUND).fillna(0).astype(int)
    m["tier"] = m["Series"].map(tier_of)
    # WTA 2018-20 file lumps Premier Mandatory / Premier 5 / Premier as "Premier": split by venue
    big = {"Indian Wells", "Miami", "Madrid", "Beijing", "Rome", "Montreal", "Toronto", "Cincinnati", "Wuhan",
           "Doha", "Dubai"}
    pm = (m.tour == "WTA") & (m.Series.astype(str) == "Premier") & m.Location.isin(big)
    m.loc[pm, "tier"] = "1000"
    for c in ["WRank", "LRank", "WPts", "LPts", "PSW", "PSL", "AvgW", "AvgL", "B365W", "B365L", "MaxW", "MaxL",
              "Wsets", "Lsets", "Best of"] + [f"{s}{i}" for s in "WL" for i in range(1, 6)]:
        if c in m:
            m[c] = pd.to_numeric(m[c], errors="coerce")
    m = m.sort_values(["Date", "tour", "rnd"], kind="stable").reset_index(drop=True)
    return m


def k538(n):
    return 250.0 / ((n + 5) ** 0.4)


def main():
    m = load()
    unm = sorted(set(m.Location) - set(LOC))
    if unm:
        print("unmapped locations:", unm)
    pidx = {"ATP": load_players("atp"), "WTA": load_players("wta")}
    natcache = {}

    def nat(tour, name):
        k = (tour, name)
        if k not in natcache:
            natcache[k] = lookup(pidx[tour], name)
        return natcache[k]

    elo = defaultdict(lambda: 1500.0)
    elon = defaultdict(int)
    hist = defaultdict(list)       # (tour,name) -> list of dicts (date, surface, won, sets, bo, games, retired_self, final_win, rank)
    rows = []
    for date, g in m.groupby("Date", sort=True):
        # ---- features (state as of before this date)
        for r in g.itertuples(index=False):
            comment = str(r.Comment)
            if comment != "Completed":
                continue
            ow, ol = (r.PSW, r.PSL) if (r.PSW > 1 and r.PSL > 1) else (r.AvgW, r.AvgL)
            src = "PS" if (r.PSW > 1 and r.PSL > 1) else "AVG"
            if not (ow > 1 and ol > 1):
                continue
            iw, il = 1 / ow, 1 / ol
            pw = iw / (iw + il)
            bw = bl = np.nan
            if r.B365W > 1 and r.B365L > 1:
                bw = (1 / r.B365W) / (1 / r.B365W + 1 / r.B365L)
            surf = str(r.Surface)
            cty = LOC.get(r.Location)
            side = {}
            for me, op, o, p, rk, ork, pts, opts, pb in (
                    (r.Winner, r.Loser, ow, pw, r.WRank, r.LRank, r.WPts, r.LPts, bw),
                    (r.Loser, r.Winner, ol, 1 - pw, r.LRank, r.WRank, r.LPts, r.WPts, 1 - bw if bw == bw else np.nan)):
                k = (r.tour, me)
                h = hist[k]
                n_all = len(h)
                w_all = sum(x["won"] for x in h)
                hs = [x for x in h if x["surface"] == surf]
                last = h[-1] if h else None
                e_all, e_s = elo[(k, "all")], elo[(k, surf)]
                ioc, hand = nat(r.tour, me)
                side[me] = dict(
                    tour=r.tour, season=r.season, date=date, player=me, opp=op, odds=o, p=p, src=src, pb365=pb,
                    won=int(me == r.Winner), surface=surf, tier=r.tier, rnd=r.rnd, bo=r[m.columns.get_loc("Best of")],
                    rank=rk, pts=pts, n_all=n_all, wr_all=(w_all / n_all) if n_all else np.nan,
                    n_surf=len(hs), wr_surf=(sum(x["won"] for x in hs) / len(hs)) if hs else np.nan,
                    days=(date - last["date"]).days if last else np.nan,
                    last_sets=last["sets"] if last else np.nan, last_bo=last["bo"] if last else np.nan,
                    last_games=last["games"] if last else np.nan,
                    last_ret_self=last["ret_self"] if last else 0,
                    last_final_win=last["final_win"] if last else 0,
                    last_month=last["date"].month if last else np.nan,
                    elo_all=e_all, elo_s=e_s, elo_n=elon[(k, "all")], elo_ns=elon[(k, surf)],
                    ioc=ioc, hand=hand, home=int(ioc is not None and ioc == cty), cty=cty,
                    # games over the 14 days before this date (workload)
                    load14=sum(x["games"] for x in h[-8:] if (date - x["date"]).days <= 14),
                    mid=f"{r.tour}|{date.date()}|{r.Winner}|{r.Loser}")
            a, b = side[r.Winner], side[r.Loser]
            for x, y in ((a, b), (b, a)):
                for c in ("rank", "pts", "n_all", "wr_all", "n_surf", "wr_surf", "days", "last_sets", "last_bo",
                          "last_games", "elo_all", "elo_s", "elo_n", "elo_ns", "ioc", "hand", "home", "load14",
                          "last_ret_self", "last_final_win"):
                    x["o_" + c] = y[c]
                rows.append(x)
        # ---- update state with this date's results
        for r in g.itertuples(index=False):
            comment = str(r.Comment)
            surf = str(r.Surface)
            sets = (r.Wsets if r.Wsets == r.Wsets else 0) + (r.Lsets if r.Lsets == r.Lsets else 0)
            games = 0
            for i in range(1, 6):
                for s in "WL":
                    v = getattr(r, f"{s}{i}", np.nan)
                    games += v if v == v else 0
            if "Walkover" in comment or games == 0:
                continue
            bo = r[m.columns.get_loc("Best of")]
            ret = comment.startswith("Retired") or comment.startswith("Ret")
            for me, won in ((r.Winner, 1), (r.Loser, 0)):
                hist[(r.tour, me)].append(dict(date=date, surface=surf, won=won, sets=sets, bo=bo, games=games,
                                               ret_self=int(ret and not won),
                                               final_win=int(won and r.rnd == 7)))
            if comment != "Completed":
                continue          # Elo only from completed matches
            kw, kl = (r.tour, r.Winner), (r.tour, r.Loser)
            for sk in ("all", surf):
                ew, el = elo[(kw, sk)], elo[(kl, sk)]
                ex = 1 / (1 + 10 ** ((el - ew) / 400))
                elo[(kw, sk)] = ew + k538(elon[(kw, sk)]) * (1 - ex)
                elo[(kl, sk)] = el - k538(elon[(kl, sk)]) * (1 - ex)
                elon[(kw, sk)] += 1
                elon[(kl, sk)] += 1
    s = pd.DataFrame(rows)
    s.to_pickle(os.path.join(HERE, "sides.pkl"))
    print(len(s), "side rows;", s.groupby(["tour", "season"]).size().to_dict())
    print("nationality matched:", round(s.ioc.notna().mean(), 3), " home rows:", int(s.home.sum()))
    print("price source:", s.groupby("season").src.apply(lambda x: round((x == "PS").mean(), 3)).to_dict())


if __name__ == "__main__":
    main()
