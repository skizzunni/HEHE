"""Regression tests for the rules the board must never break.

    python3 -m unittest discover -s tests -v

Standard library only, no network: every feed is replaced with a fixed,
realistic stand-in. Each test names the rule it protects; a failure here
means a rule the owner set (or a fix already made once) has been broken.
"""
import datetime as dt
import os
import json
import tempfile
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]

import backtest as B          # noqa: E402
import fanduel                # noqa: E402
import locks                  # noqa: E402
import player_props           # noqa: E402
import props_ledger           # noqa: E402
import stacks                 # noqa: E402
import weather                # noqa: E402

H, A = "Brighton & Hove Albion", "Crystal Palace"


def soccer_board(start):
    o = dict(away_ml=500, home_ml=-210, draw_ml=360, total=2.5, spread=None, fav="home",
             over=-188, under=152)
    row, _ = B.build("epl", (dt.date(2026, 10, 18), "740001", H, A, 0, 0), o)
    row["mkt"]["start"] = start
    return row


def soccer_book(start):
    return {"epl": [dict(home="Brighton", away="Crystal Palace", id="9", start=start, soccer=True,
                         ml={"Brighton": "m:1", "Draw": "m:2", "Crystal Palace": "m:3"},
                         px={"m:1": "-210", "m:2": "+360", "m:3": "+500"}, spread={}, total={})]}


class LocksRules(unittest.TestCase):
    """S3: 11 legs, -400 .. -120 on the regular card; Safe Locks -2000 .. -500."""

    def setUp(self):
        self._alts, self._elig = fanduel.load_alts, locks._eligible
        locks._eligible = lambda r, d, n: True
        self.start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).isoformat()

    def tearDown(self):
        fanduel.load_alts, locks._eligible = self._alts, self._elig

    def build(self, alts, **kw):
        fanduel.load_alts = lambda g: alts
        return locks.build({"epl": [soccer_board(self.start)]}, {"epl"}, {},
                           soccer_book(self.start), day="20261018", **kw)["locks"]

    def test_regular_card_price_window(self):
        legs = self.build([("dc", "Brighton", None, None, "d:1", "-600", "DC")])
        for L in legs:
            d = locks._dec(L["price"])
            self.assertTrue(locks.DEC_MIN <= d <= locks.DEC_MAX, L)
        self.assertNotIn("-600", [L["price"] for L in legs])     # -600 is outside -400 .. -120

    def test_safe_card_price_window(self):
        legs = self.build([("dc", "Brighton", None, None, "d:1", "-600", "DC")],
                          dec=locks.SAFE_DEC, band=locks.SAFE_BAND)
        self.assertEqual([L["price"] for L in legs], ["-600"])
        self.assertEqual(legs[0]["spec"], dict(t="dc", team=H))  # board's name, so ESPN grades it

    def test_soccer_only_validated_kinds(self):
        legs = self.build([("total", None, "under", 4.5, "t:1", "-1000", "U4.5"),
                           ("spread", "Brighton", None, 1.5, "s:1", "-1800", "+1.5")],
                          dec=locks.SAFE_DEC, band=locks.SAFE_BAND)
        self.assertEqual(legs, [])          # soccer totals / handicaps are not tested yet

    @staticmethod
    def pool(kinds):
        out = []
        for k, (lg, t, p) in enumerate(kinds):
            out += [dict(gid=f"{lg}:{k}{i}", league=lg, p=p - i * 0.001, spec=dict(t=t, line=50.5),
                         label=f"{lg}{t}{i}") for i in range(10)]
        return out

    def test_kind_cap_while_other_kinds_remain(self):
        """Same-day college unders missed together 2.6x more than independent
        legs would: no kind passes MAX_SAME while other kinds can fill."""
        out = locks.choose(self.pool([("ncaaf", "under", 0.9), ("nfl", "win", 0.8),
                                      ("nhl", "over", 0.79)]), 11)
        self.assertEqual(len(out), 11)
        self.assertEqual(len({L["gid"] for L in out}), 11)        # one leg per game
        for lg in ("ncaaf", "nfl", "nhl"):
            self.assertLessEqual(sum(L["league"] == lg for L in out), locks.MAX_SAME)

    def test_one_leg_per_game_and_extras_apart(self):
        """A light day gives a short card, never a second leg from one game;
        other same-game ideas are listed apart and kept out of the ticket."""
        pool = [dict(gid=f"g{g}", league="nfl", p=0.9 - g * 0.01 - k * 0.001, kind=None, match="m",
                     spec=dict(t=t, line=44.5), label=f"g{g}{t}") for g in range(3)
                for k, t in enumerate(("under", "win", "over"))]
        pool += [dict(gid="g0", league="nfl", p=0.88, kind="prop", name="P", label="P 1+", match="m")]
        out = locks.choose(pool, 11)
        self.assertEqual(sorted(L["gid"] for L in out), ["g0", "g1", "g2"])
        ex = locks.extras(pool, out)
        self.assertTrue(ex and all(x["gid"] in {"g0", "g1", "g2"} and x["extra"] for x in ex))
        self.assertFalse({id(x) for x in out} & {id(x) for x in ex})
        self.assertTrue(all(sum(x["gid"] == g for x in ex) <= locks.EXTRA_PER_GAME for g in ("g0",)))
        tmp = tempfile.mkdtemp()
        book_path = os.path.join(tmp, "l.json")
        real = props_ledger.LEDGER
        props_ledger.LEDGER = os.path.join(tmp, "props.json")     # never the real ledger
        try:
            locks.record(dict(locks=out + ex), "2026-10-18", book_path)
        finally:
            props_ledger.LEDGER = real
        self.assertEqual(len(locks.load(book_path)["days"]["2026-10-18"]), 3)   # extras never recorded

    def test_replay_gives_the_same_card(self):
        """The chooser re-run on the saved decision-time pool gives exactly
        the card that was set; a changed input shows as a mismatch."""
        pool = [dict(gid=f"nfl:{g}", league="nfl", p=0.9 - g * 0.013 - k * 0.002, kind=None, match="m",
                     spec=dict(t=t, line=44.5), label=f"{g}{t}", price="-300")
                for g in range(14) for k, t in enumerate(("under", "win"))]
        card = sorted(locks.choose(pool, 11), key=lambda x: -x["p"])
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "l.json")
        real = props_ledger.LEDGER
        props_ledger.LEDGER = os.path.join(tmp, "props.json")
        try:
            locks.record(dict(locks=card, n=11, pool=[{k: L.get(k) for k in locks.POOL_KEYS} for L in pool]),
                         "2026-10-18", path)
        finally:
            props_ledger.LEDGER = real
        ok, got, rec = locks.replay("2026-10-18", path)
        self.assertTrue(ok)
        self.assertEqual(len(rec), 11)
        book = locks.load(path)
        book["pools"]["2026-10-18"]["legs"][0]["p"] = 0.1            # tamper with an input
        locks.save(book, path)
        self.assertFalse(locks.replay("2026-10-18", path)[0])

    def test_two_sided_devig(self):
        """A line's chance comes from its own price and its opposite's."""
        key = lambda sp: ("g", json.dumps(sp, sort_keys=True))
        refs = {key(dict(t="under", line=44.5)): ("r", "-150", None),
                key(dict(t="over", line=44.5)): ("r", "+120", None)}
        p, how = locks.two_sided(refs, "g", dict(t="over", line=44.5), H, A, "+120")
        self.assertEqual(how, "two-sided")
        a, b = 100 / 220, 150 / 250
        self.assertAlmostEqual(p, a / (a + b))
        p, how = locks.two_sided(refs, "g", dict(t="over", line=47.5), H, A, "+150")
        self.assertEqual(how, "assumed margin")
        self.assertEqual(locks.opposite(dict(t="spread", team=H, line=-3.5), H, A),
                         dict(t="spread", team=A, line=3.5))
        self.assertEqual(locks.opposite(dict(t="dc", team=H), H, A), dict(t="win", team=A))

    def test_alternate_lines_in_order(self):
        """Raising an Over line never raises its chance."""
        pool = [dict(gid="g", p=p, spec=dict(t="over", line=L)) for L, p in
                ((40.5, 0.80), (43.5, 0.83), (46.5, 0.70))]
        locks.monotone(pool)
        ps = [L["p"] for L in sorted(pool, key=lambda L: L["spec"]["line"])]
        self.assertTrue(all(a >= b for a, b in zip(ps, ps[1:])), ps)
        self.assertAlmostEqual(ps[0], 0.815)

    def test_fill_when_every_kind_is_capped(self):
        """With only two kinds on the slate the card still reaches 11 legs."""
        out = locks.choose(self.pool([("ncaaf", "under", 0.9), ("nfl", "win", 0.8)]), 11)
        self.assertEqual(len(out), 11)
        self.assertEqual(len({L["gid"] for L in out}), 11)


class Grading(unittest.TestCase):
    """Legs settle on ESPN's final score; draws, voids and live games handled."""

    def settle(self, spec, h, a, **res):
        L = dict(gid="epl:740001", home=H, away=A, spec=spec, status="open", label="x")
        locks.settle(L, lambda lg, c, e: dict(res, scores={H: h, A: a}) if not res.get("void")
                     else dict(void=True))
        return L["status"]

    def test_double_chance(self):
        self.assertEqual(self.settle(dict(t="dc", team=H), 1, 1), "won")
        self.assertEqual(self.settle(dict(t="dc", team=H), 2, 0), "won")
        self.assertEqual(self.settle(dict(t="dc", team=H), 0, 2), "lost")
        self.assertEqual(self.settle(dict(t="dc", team=A), 0, 1), "won")

    def test_win_loses_on_draw(self):
        self.assertEqual(self.settle(dict(t="win", team=H), 1, 1), "lost")

    def test_integer_lines_push(self):
        """Under/Over 44 at 24-20 and Home -3 at 24-21 push (FanDuel NY drops
        the leg); half-point lines never push; a stored loss is re-graded."""
        for spec, h, a in ((dict(t="under", line=44), 24, 20), (dict(t="over", line=44), 24, 20),
                           (dict(t="spread", team=H, line=-3), 24, 21),
                           (dict(t="spread", team=A, line=3), 24, 21),
                           (dict(t="teamover", team=H, line=24), 24, 21)):
            self.assertEqual(stacks.settle_score(spec, H, A, h, a), "push", spec)
            self.assertEqual(self.settle(spec, h, a), "void")
        self.assertEqual(stacks.settle_score(dict(t="under", line=44.5), H, A, 24, 20), "won")
        self.assertEqual(stacks.settle_score(dict(t="nomargin", team=H, line=3), H, A, 24, 21), "lost")
        old = dict(status="lost", spec=dict(t="under", line=44), home=H, away=A, score=f"{A} 20 - {H} 24")
        self.assertTrue(stacks.repush(old))
        self.assertEqual((old["status"], old["push"]), ("void", True))
        self.assertFalse(stacks.repush(old))

    def test_void_and_live(self):
        self.assertEqual(self.settle(dict(t="dc", team=H), 0, 0, void=True), "void")
        self.assertEqual(self.settle(dict(t="dc", team=H), 0, 0, live=True), "open")


class SoccerMatching(unittest.TestCase):
    """FanDuel's short names find the right fixture, never a wrong one."""

    def test_names(self):
        for fd, espn in [("Nottm Forest", "Nottingham Forest"), ("Man Utd", "Manchester United"),
                         ("Paris St-G", "Paris Saint-Germain"), ("Wolves", "Wolverhampton Wanderers"),
                         ("Atletico Madrid", "Atlético Madrid"), ("Mgladbach", "Borussia Mönchengladbach"),
                         ("FC Copenhagen", "F.C. København"), ("OB", "Odense Boldklub"),
                         ("Bodo/Glimt", "Bodø/Glimt")]:
            self.assertGreaterEqual(fanduel._team_score(fd, espn), 1.0, (fd, espn))

    def test_reversed_fixture_rejected(self):
        book = {"epl": [dict(home="Man Utd", away="Man City", start="2026-10-18T15:30:00.000Z")]}
        self.assertIsNotNone(fanduel.find(book, "epl", "Manchester City", "Manchester United",
                                          "2026-10-18T15:30Z"))
        self.assertIsNone(fanduel.find(book, "epl", "Manchester United", "Manchester City",
                                       "2026-10-18T15:30Z"))

    def test_kickoff_must_agree(self):
        book = {"epl": [dict(home="Nottm Forest", away="Arsenal", start="2026-10-18T15:30:00.000Z")]}
        self.assertIsNone(fanduel.find(book, "epl", "Arsenal", "Nottingham Forest", "2026-10-19T15:30Z"))

    def test_parse_soccer_markets(self):
        odds = lambda o: {"americanDisplayOdds": {"americanOdds": o}}
        mk = {"1": dict(marketType="DOUBLE_CHANCE", marketId="1", runners=[
                  dict(runnerName="Bournemouth And Draw", selectionId=1, winRunnerOdds=odds(-340)),
                  dict(runnerName="Bournemouth And Sunderland", selectionId=2, winRunnerOdds=odds(-320))]),
              "2": dict(marketType="HOME_TEAM_FIRST_HALF_OVER/UNDER_1.5", marketId="2", runners=[
                  dict(runnerName="Under", selectionId=3, winRunnerOdds=odds(-350))])}
        out = fanduel.parse_soccer(mk, dict(home="Bournemouth", away="Sunderland"))
        self.assertEqual([x[0] for x in out], ["dc"])     # first-half and no-draw markets skipped


class Models(unittest.TestCase):
    def test_nfl_totals_upper_tail(self):
        """NFL far unders overstated 8-12 points with a symmetric 10.5 (fixed 2026-10-17)."""
        o = dict(away_ml=150, home_ml=-175, draw_ml=None, total=45.5, spread=-3.5, fav="home",
                 over=-110, under=-110)
        row, soc = B.build("nfl", (dt.date(2025, 10, 1), "1", "H", "A", 24, 20), o)
        G = stacks.game_from_row(row, "nfl", soc)
        u10 = G.prob_specs([dict(t="under", line=55.5)])
        o10 = G.prob_specs([dict(t="over", line=35.5)])
        self.assertLess(u10, 0.78)           # was 0.83 on the old model
        self.assertLess(u10, o10)            # the upper tail is the fatter one

    def test_wind_edge_scales_with_line(self):
        self.assertAlmostEqual(weather._scale(0.5), 1.0, places=6)
        self.assertLess(weather._scale(0.77), 0.8)
        self.assertLess(weather._scale(0.95), 0.3)


class Props(unittest.TestCase):
    def test_ungradable_never_on_tickets(self):
        g = dict(id="mls:1", match="A v B", lg="MLS", props=[
            dict(name="X", market="Tackles", line="1+", p=0.85, price="-300", fd="1:1", label="X tackles")])
        self.assertFalse(props_ledger.gradable("mls", "Tackles"))
        self.assertEqual(player_props.prop_tickets([g], tiers=(1,)), {1: []})
        self.assertIsNone(player_props.mega_ticket([g]))

    def test_soccer_shots_off_in_every_soccer_league(self):
        for lg in ("uel", "efl1", "uecl", "sco", "ned"):
            self.assertFalse(props_ledger.offered(lg, "Shots"), lg)
        self.assertTrue(props_ledger.offered("nhl", "Shots on Goal"))
        self.assertTrue(props_ledger.offered("epl", "Goalkeeper Saves"))

    def test_audit_ignores_markets_taken_off(self):
        import daily_review as R
        props = {str(i): dict(league="uel", market="Shots", status="lost", p=0.85) for i in range(30)}
        self.assertEqual([a for a in R.audit([], props, {"legs": {}}) if "Shots" in a["name"]], [])

    def test_fanduel_prop_names_gradable(self):
        import fd_props
        for sport, pats in fd_props.STATS.items():
            lg = {"football": "nfl", "hockey": "nhl", "basketball": "nba", "baseball": "mlb"}.get(sport)
            if not lg:
                continue
            for _, name in pats:
                self.assertTrue(props_ledger.gradable(lg, name), (lg, name))


class UfcGrading(unittest.TestCase):
    """'Goes the distance' settles from the clock when ESPN's result line is
    missing (a prop was nearly voided for it on 2026-10-17)."""

    def settle(self, line, **res):
        import ufc_props
        return ufc_props.settle(dict(market="Goes the distance", line=line, name="Fight"),
                                dict(res, winner="X"))

    def test_clock_fallback(self):
        self.assertEqual(self.settle("No", method=None, minutes=3.5, rounds=3), "won")
        self.assertEqual(self.settle("Yes", method=None, minutes=15.0, rounds=3), "won")
        self.assertEqual(self.settle("Yes", method=None, minutes=24.9, rounds=5), "lost")
        self.assertEqual(self.settle("Yes", method="KO/TKO", minutes=15.0, rounds=3), "lost")
        self.assertIsNone(self.settle("No", method=None, minutes=None, rounds=3))
        self.assertIsNone(self.settle("No", method=None, minutes=4.0, rounds=None))

    def test_method_still_waits(self):
        import ufc_props
        self.assertIsNone(ufc_props.settle(dict(market="Method", line="KO/TKO", name="X"),
                                           dict(method=None, minutes=3.0, rounds=3, winner="X")))


class NamedPlays(unittest.TestCase):
    """The Winners parlay (top N at 80%+) and Best play (50%+) are graded as
    the slices the page showed, not only the full card."""

    def test_plays_graded(self):
        card = [dict(p=0.95, price="-2000", status=s) for s in
                ("won", "won", "void", "won", "lost", "won", "open", "won", "won", "won", "won")]
        got = locks.plays(card)
        n, prob, res = got["winners"]
        self.assertEqual(n, 4)                  # .95^4 = .815; .95^5 = .774
        self.assertEqual(res, "won")            # the void drops off the slip
        n, prob, res = got["best"]
        self.assertEqual((n, res), (11, "lost"))
        card[4]["status"] = "open"
        self.assertEqual(locks.plays(card)["best"][2], "open")


class PropIdentity(unittest.TestCase):
    """A player whose name is spelled differently by FanDuel and ESPN is
    graded, not voided as a DNP (2026-10-18: Aho (CAR), Stützle, Marner), and
    MLB batting props read ESPN's group from "type" (eight were ungradable)."""

    @staticmethod
    def box():
        def grp(abbr, players, keys, name=None, typ=None):
            return dict(team=dict(abbreviation=abbr), statistics=[dict(
                name=name, type=typ, keys=keys,
                athletes=[dict(athlete=dict(id=str(i), displayName=n), stats=v) for i, n, v in players])])
        return dict(boxscore=dict(players=[
            grp("CAR", [(1, "Sebastian Aho", ["0"]), (2, "Mitch Marner", ["1"])], ["shotsTotal"], name="forwards"),
            grp("NYI", [(3, "Sebastian Aho", ["4"]), (4, "Tim Stutzle", ["1"]),
                        (5, "John Smith", ["2"]), (6, "Jake Smith", ["3"])], ["shotsTotal"], name="forwards"),
            grp("TB", [(7, "Chandler Simpson", ["0-3", "0", "1"])], ["hits-atBats", "runs", "RBIs"],
                typ="batting")]))

    def test_names(self):
        import props_ledger as PL
        st = PL.box_stats(self.box())
        get = lambda n: PL.resolve(st, dict(name=n))
        self.assertEqual(get("Sebastian Aho (CAR)")[0]["shotsTotal"], 0)    # the CAR one, not NYI's 4
        self.assertEqual(get("Tim Stützle")[0]["shotsTotal"], 1)
        self.assertEqual(get("Mitchell Marner"), (st["2"], "fuzzy"))
        self.assertEqual(get("Sebastian Aho"), (None, "unresolved"))        # two of them, no hint
        self.assertEqual(get("J Smith")[1], "unresolved")
        self.assertEqual(get("Connor McDavid"), (None, "absent"))

    def test_mlb_group_from_type(self):
        import props_ledger as PL
        st, _ = PL.resolve(PL.box_stats(self.box()), dict(name="Chandler Simpson"))
        self.assertEqual(PL.MARKETS["mlb"]["Hits + Runs + RBIs"](st), 1)
        self.assertEqual(PL.MARKETS["mlb"]["Hits"](st), 0)

    def test_record_keys_unchanged(self):
        import props_ledger as PL
        self.assertEqual(PL.prop_key(dict(gid="nhl:1", name="Tim Stützle", market="Shots on Goal", line="1+")),
                         "nhl:1|n:tim sttzle|Shots on Goal|1+")


class Coherence(unittest.TestCase):
    """A leg's chance never drops as its price chance rises, and the two
    sides of a market still sum to 1 (the old band factor broke both)."""

    def test_market_chance(self):
        import lottery
        f = lottery.market_chance
        self.assertLessEqual(f(0.399999), f(0.4))
        self.assertAlmostEqual(f(0.5) + f(0.5), 1.0)
        xs = [i / 1000 for i in range(1, 990)]
        self.assertTrue(all(f(a) <= f(b) for a, b in zip(xs, xs[1:])))
        self.assertTrue(all(abs(f(x) + f(1 - x) - 1) < 1e-9 for x in xs if 0.011 <= x <= 0.989))


class RecommendationHistory(unittest.TestCase):
    """Every published version of a call is kept; a change of market is a new
    bet with its own entry price; nothing is revised after the start."""

    def run_record(self, path, pick, dc, price, conf, start):
        import ledger
        row = dict(id="efl1:1", mypick=pick, myside="home", dc=dc, myconf=conf, label="A @ B",
                   legs=[dict(side="home", price=price)], mkt=dict(start=start))
        state = dict(dates=("20261018", "20261019"), slots=dict(today={"efl1": [row]}, tomorrow={}))
        real = ledger.LEDGER
        ledger.LEDGER = path
        try:
            ledger.record(state)
            return ledger.load()["efl1:1"]
        finally:
            ledger.LEDGER = real

    def test_history(self):
        path = os.path.join(tempfile.mkdtemp(), "ledger.json")
        later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5)).isoformat()
        e = self.run_record(path, "Middlesbrough", False, "-210", 0.6, later)
        self.assertEqual((e["first_price"], len(e["history"])), ("-210", 1))
        e = self.run_record(path, "Middlesbrough", False, "-210", 0.6, later)
        self.assertEqual(len(e["history"]), 1)                      # unchanged: no new version
        e = self.run_record(path, "Middlesbrough", True, "-210", 0.8, later)
        self.assertIsNone(e["first_price"])                          # double chance: not the -210 bet
        self.assertEqual([h["dc"] for h in e["history"]], [False, True])
        self.assertEqual(e["first"]["pick"], "Middlesbrough")
        self.assertFalse(e["first"]["dc"])                           # what was first published stays
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        e = self.run_record(path, "Other", False, "+150", 0.4, past)
        self.assertEqual(e["pick"], "Middlesbrough")                 # frozen once started


class HonestRecords(unittest.TestCase):
    """Strong-call cut-offs come only from a qualifying record; the fitted
    model weight needs a held-out gain; market-only (w = 0) is a choice."""

    def picks(self, n, conf, hit_rate, lg="nhl", start=dt.date(2026, 9, 1)):
        out = []
        for i in range(n):
            won = (i * hit_rate) % 1 + hit_rate >= 1          # an even spread of wins
            out.append(dict(league=lg, conf=conf, status="won" if won else "lost",
                            played=(start + dt.timedelta(days=i // 5)).isoformat()))
        return out

    def test_no_fallback_cutoff(self):
        import daily_review as R
        cuts, detail = R.fit_calls(self.picks(80, 70.0, 0.6))      # 60% at 70%: never qualifies
        self.assertNotIn("nhl", cuts)
        self.assertIsNone(detail["nhl"]["cutoff"])
        cuts, _ = R.fit_calls(self.picks(80, 70.0, 0.8))
        self.assertEqual(cuts.get("nhl"), 0.55)          # the lowest cut that selects them

    def test_weights_need_held_out_gain(self):
        import daily_review as R
        self.assertEqual(R.W_GRID[0], 0.0)
        # legacy rows (no raw model/market pair) are never fitted
        self.assertIsNone(R.picks_view(dict(conf=70, price="-200", status="won")))
        rows = [dict(league="nfl", myside="home", p_model_away=0.5, p_market_away=0.4,
                     status="won" if i % 10 < 6 else "lost",
                     played=(dt.date(2026, 9, 1) + dt.timedelta(days=i)).isoformat()) for i in range(60)]
        w, d = R.refit(rows)      # the model adds nothing: home wins 60% = the market's 60%
        self.assertEqual(w["nfl"], 0.0)


class Freshness(unittest.TestCase):
    """Prices go to the right game, and nothing past its start is offered."""

    def test_doubleheader_by_start(self):
        book = {"mlb": [dict(away="Cleveland Guardians", home="Tampa Bay Rays", id="g1",
                             start="2026-10-18T17:10:00Z"),
                        dict(away="Cleveland Guardians", home="Tampa Bay Rays", id="g2",
                             start="2026-10-18T21:40:00Z")]}
        f = lambda t: (fanduel.find(book, "mlb", "Cleveland Guardians", "Tampa Bay Rays", t) or {}).get("id")
        self.assertEqual(f("2026-10-18T21:40Z"), "g2")
        self.assertEqual(f("2026-10-18T17:10Z"), "g1")
        self.assertIsNone(f("2026-10-19T17:10Z"))          # a different day's game: no match
        self.assertIsNone(f(None))                          # two candidates, no time: refuse to guess
        one = {"mlb": book["mlb"][:1]}
        self.assertEqual(fanduel.find(one, "mlb", "Cleveland Guardians", "Tampa Bay Rays", None)["id"], "g1")

    def test_stale_pregame_after_kickoff(self):
        import dashboard
        now = dt.datetime(2026, 10, 18, 13, 5, tzinfo=dashboard.ET)
        c = dict(date="2026-10-18T17:00Z", status=dict(type=dict(state="pre")))   # 1:00 PM ET
        self.assertFalse(dashboard.pregame(c, "20261018", now))   # cached "pre", but it has started
        self.assertTrue(dashboard.pregame(c, "20261018", now - dt.timedelta(hours=1)))
        c["status"]["type"]["state"] = "in"
        self.assertFalse(dashboard.pregame(c, "20261018", now - dt.timedelta(hours=1)))


class SelectionPolicy(unittest.TestCase):
    """One policy source; the regression cases from the 2026-10-18 slate."""

    def test_atlanta_follows_the_tested_policy(self):
        """CHI @ ATL: the market had Chicago 51.7%, the model Atlanta 56.4%. A
        hand-set NFL weight of 0.30 published Atlanta 50.7% (lost). With the
        tested policy (market only) the pick is Chicago."""
        import picks, policy
        real = policy._W
        try:
            policy._W = {"default": 0.0, "weights": {"ncaaf": 0.0}}
            p_away = picks.anchor(0.4365, 0.5174, policy.model_weight("nfl"))
            self.assertGreater(p_away, 0.5)                       # Chicago (away)
            policy._W = {"default": 0.0, "weights": {"nfl": 0.3}}   # only a tested file may say 0.3
            self.assertLess(picks.anchor(0.4365, 0.5174, policy.model_weight("nfl")), 0.5)
        finally:
            policy._W = real

    def test_strong_calls_only_where_qualified(self):
        """No league gets strong calls without a qualifying record: not soccer
        by exception, not a league with no record by default."""
        import calls
        real = calls._MIN
        try:
            calls._MIN = {"ncaaf": 0.575}
            self.assertFalse(calls.is_call("epl", 80.0))       # soccer group has not qualified
            self.assertFalse(calls.is_call("nba", 80.0))       # no record at all
            self.assertTrue(calls.is_call("ncaaf", 60.0))
            calls._MIN = {"soccer": 0.70}
            self.assertTrue(calls.is_call("epl", 72.0))        # qualified as the soccer group
            self.assertFalse(calls.is_call("epl", 69.0))
        finally:
            calls._MIN = real

    def test_no_hand_set_weights_in_live_code(self):
        import re
        for f in ("dashboard.py", "picks.py"):
            src = open(os.path.join(ROOT, f)).read()
            self.assertIsNone(re.search(r"ANCHOR_W\s*=|MLB_MKT_W\s*=|TENNIS_MKT_W\s*=", src), f)


class Participation(unittest.TestCase):
    """Goalkeeper backups (2026-10-17/18: five on the Lottery's DraftKings
    tickets, all void) and inactive players are never recommended."""

    def test_goalkeepers_need_a_confirmed_start(self):
        import participation as PT
        sm = dict(rosters=[dict(team=dict(abbreviation="SGE"), roster=[
            dict(athlete=dict(displayName="Noah Atubolu"), starter=True),
            dict(athlete=dict(displayName="Jens Grahl"), starter=False)])], injuries=[])
        st = lambda n: PT.status(sm, "ger", n, "Goalkeeper Saves")
        self.assertEqual(st("Noah Atubolu"), "starting")
        self.assertEqual(st("Jens Grahl"), "on the bench")
        self.assertEqual(st("Ron-Robert Zieler"), "not in the squad")
        self.assertEqual(PT.status(dict(rosters=[], injuries=[]), "ger", "Noah Atubolu",
                                   "Goalkeeper Saves"), "lineup not out")

    def test_injury_report(self):
        import participation as PT
        sm = dict(rosters=[], injuries=[dict(team=dict(abbreviation="DAL"), injuries=[
            dict(athlete=dict(displayName="KaVontae Turpin"), status="Out"),
            dict(athlete=dict(displayName="Dee Winters"), status="Questionable")])])
        self.assertEqual(PT.status(sm, "nfl", "KaVontae Turpin", "Receptions"), "listed out")
        self.assertEqual(PT.status(sm, "nfl", "Dee Winters", "Tackles"), "listed questionable")
        self.assertEqual(PT.status(sm, "nfl", "CeeDee Lamb", "Receptions"), "ok")

    def test_backup_keeper_never_reaches_a_ticket(self):
        """The archived 2026-10-18 DraftKings ticket's Jannik Huth 5+ saves:
        unconfirmed, so no Lottery leg, prop ticket or 25-leg ticket takes it."""
        import lottery
        P = dict(name="Jannik Huth", market="Goalkeeper Saves", line="5+", p=0.6, price="+150",
                 label="Jannik Huth: 5+ Goalkeeper Saves", play="on the bench", plays=False)
        games = [dict(id="ger:1", lg="Bundesliga", match="A v B", props=[P])]
        self.assertEqual(lottery._prop_legs(games, {"ger:1"}), [])
        self.assertIsNone(player_props.mega_ticket(games))
        P.update(play="starting", plays=True)
        self.assertEqual(len(lottery._prop_legs(games, {"ger:1"})), 1)


class LotteryFinish(unittest.TestCase):
    """The leg that completes a $10,000 ticket is the likeliest line of any
    unused game that reaches the payout (archived 2026-10-18: a 2.35 leg at
    41% was taken because only each game's top-ranked line was considered)."""

    def test_finish_with_the_likeliest_line(self):
        import lottery
        legs = []
        for g in range(9):                                   # nine legs reaching ~6,000
            legs.append(dict(gid=f"g{g}", p=0.456, dec=2.63, value=1.2, label=f"L{g}"))
        # the last game: its top-ranked line is the long one; a shorter line is likelier
        legs.append(dict(gid="h", p=0.447, dec=2.35, value=1.05, label="Hicks 2+"))
        legs.append(dict(gid="h", p=0.56, dec=1.78, value=0.9968, label="Short line"))
        tier = dict(lottery.TIERS[1], n=1)
        t = lottery._tickets(legs, "FanDuel", tier)[0]
        self.assertGreaterEqual(t["base"], lottery.TARGET)
        self.assertEqual(t["legs"][-1]["label"], "Short line")

    def test_archive_replays(self):
        import lottery
        legs = [dict(gid=f"g{g}", kind="game", fd="x", p=0.456, dec=2.63, value=1.2, label=f"L{g}",
                     price="+163") for g in range(12)]
        res = dict(tickets=lottery._tickets(legs, "FanDuel", dict(lottery.TIERS[1], n=1)), candidates=legs)
        tmp = tempfile.mkdtemp()
        real, realp = lottery.LEDGER, props_ledger.LEDGER
        lottery.LEDGER, props_ledger.LEDGER = os.path.join(tmp, "l.json"), os.path.join(tmp, "p.json")
        try:
            lottery.record(res, "2026-10-19")
            self.assertTrue(lottery.replay("2026-10-19"))
            b = lottery.load()
            b["pools"]["2026-10-19"]["legs"][0]["value"] = 0.5      # a changed input changes the ticket
            lottery.save(b)
            self.assertFalse(lottery.replay("2026-10-19"))
        finally:
            lottery.LEDGER, props_ledger.LEDGER = real, realp


class StuckSweep(unittest.TestCase):
    """Anything still open a week after its game is reported, not left silent."""

    def test_stuck(self):
        import daily_review as R
        led = {"a": dict(status="open", played="2026-10-01"), "b": dict(status="open", played="2026-10-17"),
               "c": dict(status="won", played="2026-10-01")}
        props = {"p": dict(status="open", date="2026-10-10"), "q": dict(status="open", date="2026-10-15")}
        got = R.stuck(led, props, {"legs": {}}, {"days": {}}, dt.date(2026, 10, 18))
        self.assertEqual(sorted(got), [("picks", "a"), ("props", "p")])

    def test_alarm_dropped_once_market_is_off(self):
        import rebuild_board as B
        self.assertFalse(B._still_offered("props uel Shots"))
        self.assertTrue(B._still_offered("props nfl Receiving Yards"))
        self.assertTrue(B._still_offered("locks nfl under"))


class Integrity(unittest.TestCase):
    """Every build checks its own data before publishing."""

    def test_catches_bad_values(self):
        import integrity
        bad = {"locks": {"today": {"locks": [
            dict(p=1.3, price="None", label=None),
            dict(p=0.8, price="-400", label="ok", kalshi=dict(price="0.97"))]}},
            "x": dict(note="None is fine in a note", tag="nan")}
        got = {(p, w) for p, w, _ in integrity.check(bad)}
        self.assertEqual(got, {("D.locks.today.locks[0].p", "chance outside 0-1"),
                               ("D.locks.today.locks[0].price", "price does not parse"),
                               ("D.locks.today.locks[0].label", "missing name"),
                               ("D.x.tag", "None/nan in text")})


class BotFreshness(unittest.TestCase):
    """The Kalshi bot never buys from tickets it cannot prove are fresh."""

    def test_board_age(self):
        sys.path.insert(0, os.path.join(ROOT, "bot"))
        import kalshi_bot as K
        now = dt.datetime.now(dt.timezone.utc)
        self.assertLess(K.board_age({"built": now.isoformat()}), 60)
        self.assertGreater(K.board_age({"built": (now - dt.timedelta(minutes=45)).isoformat()}),
                           K.BOARD_MAX_AGE)
        for bad in ({}, {"built": None}, {"built": "garbage"}, {"built": "2026-10-18T03:00:00"}):
            self.assertIsNone(K.board_age(bad), bad)      # treated as stale by the caller
        self.assertFalse(K.LIVE)                          # practice until the owner switches it

    def test_practice_tickets_never_block_forever(self):
        import kalshi_bot as K
        now = dt.datetime(2026, 10, 18, 4, 30, tzinfo=dt.timezone.utc)

        def settle(m, ts="2026-10-16T18:00:28+00:00"):
            h = dict(ts=ts, count=2, ask=0.638)
            K.settle_practice(h, m, now)
            return h.get("result"), h.get("profit")
        self.assertEqual(settle({"result": "yes"}), ("won", 0.72))
        self.assertEqual(settle({"result": "", "status": "settled", "settlement_value": 85}), ("settled", 0.42))
        self.assertEqual(settle({"result": "", "status": "closed"}), (None, None))
        self.assertEqual(settle({"result": "", "status": "closed"}, ts="2026-10-10T18:00:00+00:00"),
                         ("expired", None))
        s = K.summary([dict(profit=1.0, count=2, ask=.5), dict(result="expired", count=2, ask=.6)])
        self.assertEqual((s["settled"], s["profit"]), (1, 1.0))      # expired kept out of the record


if __name__ == "__main__":
    unittest.main()
