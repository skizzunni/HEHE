"""Regression tests for the rules the board must never break.

    python3 -m unittest discover -s tests -v

Standard library only, no network: every feed is replaced with a fixed,
realistic stand-in. Each test names the rule it protects; a failure here
means a rule the owner set (or a fix already made once) has been broken.
"""
import datetime as dt
import os
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
