"""Ladder challenge: the day's likeliest Locks as one parlay (2x-5x from Nov 7), bank rolled."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ladder                                             # noqa: E402


def leg(k, p, st, price="-200"):
    return k, dict(label=k, price=price, p=p, status=st)


def book(days):
    b = {"days": {}, "legs": {}}
    for d, legs in days.items():
        b["days"][d] = []
        for k, p, st in legs:
            kk, L = leg(f"{d}|{k}", p, st)
            b["legs"][kk] = L
            b["days"][d].append(kk)
    return b


W5 = [(c, 0.8, "won") for c in "abcde"]


class Ladder(unittest.TestCase):
    def test_top_five_roll_and_bust(self):
        b = book({"2026-11-03": W5 + [("f", 0.5, "lost")],            # f is 6th: not on the ticket
                  "2026-11-04": W5[:4] + [("e", 0.8, "lost")],
                  "2026-11-05": W5})
        runs = ladder.replay(b, start="2026-11-03")
        self.assertEqual([r["status"] for r in runs], ["lost", "live"])
        self.assertAlmostEqual(runs[0]["days"][1]["stake"], round(1.5 ** 5, 2))   # -200 x5 = 7.59x
        # from 2026-11-05 the leg count is chosen (3..8): with five 80% legs at
        # -200, three legs reach $10,000 as likely as four and more than five
        self.assertEqual(len(runs[1]["days"][0]["legs"]), 3)
        self.assertAlmostEqual(runs[1]["bank"], round(1.5 ** 3, 2))
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual(r["history"][0]["lost_on"], ["2026-11-04|e"])

    def test_legs_and_tickets_record(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "lost")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual((r["legs_record"]["won"], r["legs_record"]["n"]), (9, 10))
        self.assertEqual(r["tickets"], dict(won=1, n=2))

    def test_bank_path_across_runs(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "lost")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual([(p["day"], p["run"], p["bank"]) for p in r["path"]], [("2026-11-03", 1, 7.59), ("2026-11-04", 1, 0.0)])

    def test_a_lost_run_has_no_streak(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "lost")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual((r["streak"], r["bank"]), (0, 1.0))
        self.assertEqual(r["ended"]["lost_on"], ["2026-11-04|e"])

    def test_best_combo_from_nov_9(self):
        import math, locks
        legs = [dict(key=k, gid=k, label=k, price=pr, p=p, status="open") for k, pr, p in
                (("a", "-400", 0.8), ("b", "-400", 0.8), ("c", "-400", 0.8), ("d", "-400", 0.8), ("e", "-150", 0.6))]
        got = ladder.best_combo(legs)
        self.assertEqual(sorted(L["key"] for L in got), ["a", "e"])               # 2.08x at 48% beats 4 legs 2.44x at 41%
        self.assertTrue(2 <= math.prod(locks._dec(L["price"]) for L in got) <= 5)
        b = {"days": {"2026-11-09": [L["key"] for L in legs]}, "legs": {L["key"]: L for L in legs}}
        self.assertEqual(sorted(L["key"] for L in ladder.choose(b, "2026-11-09")), ["a", "e"])
        same_game = [dict(legs[0]), dict(legs[4], gid="a")]                       # one leg per game
        self.assertEqual(ladder.best_combo(same_game), [])

    def test_two_to_five_x_from_nov_7(self):
        import math, locks
        def bk(n, p, price):
            b = {"days": {"2026-11-07": []}, "legs": {}}
            for i in range(n):
                kk, L = leg(f"x{i}", p, "open", price)
                b["legs"][kk] = L
                b["days"]["2026-11-07"].append(kk)
            return b
        got = ladder.choose(bk(10, 0.95, "-200"), "2026-11-07")          # 1.5x a leg: 2 or 3 legs pay 2.25x / 3.38x
        pays = math.prod(locks._dec(L["price"]) for L in got)
        self.assertIn(len(got), (2, 3))
        self.assertTrue(2 <= pays <= 5)
        self.assertEqual(len(ladder.choose(bk(10, 0.6, "+150"), "2026-11-07")), 1)   # one +150 leg is 2.5x
        self.assertEqual(len(ladder.choose(bk(10, 0.97, "-2000"), "2026-11-07")), 8)  # none reach 2x: nearest is 8
        o = ladder.options(bk(10, 0.95, "-200"), "2026-11-07")
        self.assertEqual([x["legs"] for x in o], list(range(1, 9)))
        self.assertEqual([x["in_band"] for x in o][:4], [False, True, True, False])
        b6 = bk(10, 0.95, "-200")
        b6["days"]["2026-11-06"] = b6["days"].pop("2026-11-07")
        self.assertEqual(len(ladder.choose(b6, "2026-11-06")), 5)                     # 11-06 stays 5 legs

    def test_log_has_leg_count_and_lost_leg(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "lost")]})
        with mock.patch.object(ladder, "START", "2026-11-03"):
            r = ladder.report(b, start="2026-11-03")
        self.assertEqual([(g["n"], g["lost_on"]) for g in r["log"]], [(5, []), (5, ["2026-11-04|e"])])

    def test_best_combo_ties_and_pool(self):
        mk = lambda k, pr, p: dict(key=k, gid=k, label=k, price=pr, p=p)
        # two ways to 2.25x at the same chance: 2 legs (-200, -200) vs ... the first found (fewer legs) stays
        legs = [mk("a", "-200", 0.75), mk("b", "-200", 0.75), mk("c", "+125", 0.5625)]
        got = ladder.best_combo(legs)
        self.assertEqual(len(got), 1)                       # +125 alone pays 2.25x at 56.25%, same as a+b; fewer legs wins the tie
        # only the `pool` likeliest legs are considered
        many = [mk(str(i), "-400", 0.8) for i in range(14)] + [mk("x", "+150", 0.5)]
        self.assertNotIn("x", [L["key"] for L in ladder.best_combo(many, pool=12)])
        self.assertEqual(ladder.best_combo([mk("z", "-2000", 0.97)]), [])   # nothing reaches 2x

    def test_skip_kinds(self):
        nfl_prop = dict(league="nfl", kind="prop", market="Receiving Yards")
        self.assertFalse(ladder.skipped(nfl_prop))                                   # off by default
        self.assertTrue(ladder.skipped(nfl_prop, skip=(("nfl", "prop"),)))
        self.assertTrue(ladder.skipped(nfl_prop, skip=(("nfl", "prop:Receiving Yards"),)))
        self.assertFalse(ladder.skipped(dict(league="nfl", spec=dict(t="over")), skip=(("nfl", "prop"),)))
        legs = [dict(key=k, gid=k, label=k, price="-400", p=0.8, status="open", league="nfl",
                     kind="prop" if k in "ab" else None, market="Receiving Yards" if k in "ab" else None, spec=dict(t="over"))
                for k in "abcdef"]
        b = {"days": {"2026-11-10": [L["key"] for L in legs]}, "legs": {L["key"]: L for L in legs}}
        with mock.patch.object(ladder, "SKIP_KINDS", (("nfl", "prop"),)):
            got = ladder.choose(b, "2026-11-10")
        self.assertTrue(got and not any(L["key"] in "ab" for L in got))

    def test_miss_label(self):
        import props_ledger
        L = dict(label="Kyle Pitts: 25+ Receiving Yards", kind="prop", status="lost", market="Receiving Yards", line="25+",
                 gid="nfl:1", name="Kyle Pitts", aid="9")
        pb = {props_ledger.prop_key(L): dict(value=23.0)}
        self.assertEqual(ladder.miss_label(L, pb), "Kyle Pitts: 25+ Receiving Yards (23, missed by 2)")
        self.assertEqual(ladder.miss_label(dict(L, status="won"), pb), L["label"])
        self.assertEqual(ladder.miss_label(L, {}), L["label"])
        self.assertEqual(ladder.miss_label(dict(label="Over 214.5 points", status="lost"), pb), "Over 214.5 points")
        self.assertEqual(ladder.miss_label(dict(label="Over 208.5 points", status="lost",
                                                score="Orlando Magic 107 - Sacramento Kings 100")),
                         "Over 208.5 points (207, missed by 1.5)")
        self.assertEqual(ladder.miss_label(dict(label="Florida Atlantic Owls under 41.5 points", status="lost",
                                                score="Florida Atlantic Owls 45 - Rice Owls 10")),
                         "Florida Atlantic Owls under 41.5 points (45, missed by 3.5)")
        self.assertEqual(ladder.miss_label(dict(label="NC State Wolfpack +15.5", status="lost",
                                                score="Georgia Tech Yellow Jackets 41 - NC State Wolfpack 3")),
                         "NC State Wolfpack +15.5 (lost by 38, missed by 22.5)")
        self.assertEqual(ladder.miss_label(dict(label="Akron Zips -3.5", status="lost", score="Akron Zips 20 - Kent State 18")),
                         "Akron Zips -3.5 (won by 2, missed by 1.5)")

    def test_count_record_games_only(self):
        b = book({"2026-11-03": W5})
        b["legs"]["2026-11-03|a"]["kind"] = "prop"
        got = {c["legs"]: c["n"] for c in ladder.count_record(b, "", hi=5, games_only=True)}
        self.assertEqual(got, {1: 1, 2: 1, 3: 1, 4: 1})                  # four game lines; a 5-leg games ticket is short

    def test_count_record(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:2] + [("c", 0.8, "lost")] + W5[3:],
                  "2026-11-05": W5[:4] + [("e", 0.8, "open")]})
        got = {c["legs"]: (c["won"], c["n"]) for c in ladder.count_record(b, "", hi=5)}
        self.assertEqual(got[1], (3, 3))
        self.assertEqual(got[3], (2, 3))          # 11-04's 3rd leg lost
        self.assertEqual(got[5], (1, 2))          # 11-05's 5th leg is still open, so that card is left out
        self.assertEqual(got[4], (2, 3))
        self.assertEqual(got[5], (1, 2))
        self.assertEqual(ladder.count_record(b, "", hi=5)[0]["pays"], 1.5)

    def test_leg_count_chosen_from_three_to_eight(self):
        legs = [(c, 0.95, "open") for c in "abcdefghij"]
        b = book({"2026-11-05": legs})
        got = ladder.choose(b, "2026-11-05")
        self.assertTrue(3 <= len(got) <= 8)
        b = book({"2026-11-06": legs})
        self.assertEqual(len(ladder.choose(b, "2026-11-06")), 5)              # the user's call from 11-06: 5 legs
        b = book({"2026-11-04": [(c, 0.95, "open") for c in "abcdefg"]})
        self.assertEqual(len(ladder.choose(b, "2026-11-04")), 5)       # before the change: 5
        self.assertEqual(ladder.choose(book({"2026-11-05": W5[:2]}), "2026-11-05"), [])   # under 3: no ticket

    def test_options_list_every_count_and_the_choice_is_the_best(self):
        b = book({"2026-11-05": [(c, 0.8, "open") for c in "abcdefgh"]})
        o = ladder.options(b, "2026-11-05")
        self.assertEqual([x["legs"] for x in o], [3, 4, 5, 6, 7, 8])
        best = max(o, key=lambda x: x["reach"] + 1e-15 * (10 - x["legs"]))
        self.assertEqual(len(ladder.choose(b, "2026-11-05")), best["legs"])
        self.assertEqual(ladder.options(b, "2026-11-04"), [])

    def test_page_and_ladder_choose_the_same_count(self):
        # board.html's ladderK picks 7 of ten 97% legs at -1000 (tests/ui_check.py)
        b = {"days": {"2026-11-05": []}, "legs": {}}
        for i in range(10):
            b["legs"][f"k{i}"] = dict(label=f"k{i}", price="-1000", p=0.97, status="open")
            b["days"]["2026-11-05"].append(f"k{i}")
        self.assertEqual(len(ladder.choose(b, "2026-11-05")), 7)

    def test_void_leg_drops_out_and_open_day_stops(self):
        b = book({"2026-11-03": W5[:4] + [("e", 0.8, "void")], "2026-11-04": W5[:4] + [("e", 0.8, "open")]})
        runs = ladder.replay(b, start="2026-11-03")
        self.assertAlmostEqual(runs[0]["days"][1]["stake"], round(1.5 ** 4, 2))
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual(r["today"]["result"], "open")
        self.assertEqual(r["streak"], 1)
        self.assertIn("tip", r["today"]["legs"][0])                       # kickoff time carried to the card

    def test_short_card_skipped(self):
        b = book({"2026-11-03": W5[:3]})
        self.assertEqual(ladder.replay(b, start="2026-11-03"), [])


class Target(unittest.TestCase):
    def test_reaching_the_target_ends_the_run_and_the_next_day_restarts(self):
        # -200 x5 = 7.59x a day: $1 -> $7.59 -> $57.64 passes a $50 target on day 2
        b = book({"2026-11-03": W5, "2026-11-04": W5, "2026-11-05": W5[:4] + [("e", 0.8, "open")]})
        runs = ladder.replay(b, start="2026-11-03", target=50)
        self.assertEqual([r["status"] for r in runs], ["reached", "live"])
        self.assertEqual(runs[1]["days"][0]["stake"], 1.0)
        r = ladder.report(b, start="2026-11-03", target=50)
        self.assertEqual(r["reached"], 1)
        self.assertEqual(r["history"][0]["peak"], round(round(7.59375, 2) * 7.59375, 2))   # the bank is kept to the cent each day

    def test_wins_needed_and_chance_from_today(self):
        b = book({"2026-11-03": W5[:4] + [("e", 0.8, "open")]})
        r = ladder.report(b, start="2026-11-03")
        # 7.59x a day from $1: 7.59^4 = 3,325 < 10,000 <= 7.59^5
        self.assertEqual(r["wins_needed"], 5)
        self.assertAlmostEqual(r["chance_to_target"], round(round(0.8 ** 5, 4) ** 5, 8))   # from the displayed 4-dp chance

    def test_best_keeps_a_busted_runs_peak(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "lost")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual(r["best"], round(1.5 ** 5, 2))
        self.assertEqual(r["bank"], 1.0)                                   # a new run starts at $1


class Last(unittest.TestCase):
    def test_last_settled_ticket_and_run_log(self):
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "void")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual(r["last"]["day"], "2026-11-04")
        self.assertEqual(r["last"]["after"], round(round(1.5 ** 5, 2) * 1.5 ** 4, 2))   # void leg pays 1x
        self.assertEqual([g["result"] for g in r["log"]], ["won", "won"])
        self.assertIsNone(r["today"])

    def test_a_loss_is_the_last_ticket_until_the_next_card(self):
        b = book({"2026-11-03": W5[:4] + [("e", 0.8, "lost")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual((r["last"]["result"], r["last"]["after"]), ("lost", 0.0))
        self.assertEqual(r["bank"], 1.0)

    def test_open_ticket_is_not_in_the_log(self):
        b = book({"2026-11-03": W5[:4] + [("e", 0.8, "open")]})
        r = ladder.report(b, start="2026-11-03")
        self.assertEqual((r["last"], r["log"]), (None, []))


class Live(unittest.TestCase):
    def test_open_legs_carry_the_game_clock_and_score(self):
        from unittest import mock
        import ledger
        legs = [dict(gid="nhl:1", status="open"), dict(gid="nhl:2", status="won"), dict(gid="nhl:3", status="open")]
        book = {"nhl:1": dict(live="End of 2nd", live_score={"Utah": 2, "Toronto": 1}),
                "nhl:2": dict(live="Final", live_score={"A": 1, "B": 0})}
        with mock.patch.object(ledger, "load", lambda: book):
            ladder.live(legs)
        self.assertEqual((legs[0]["live"], legs[0]["live_score"]), ("End of 2nd", "Utah 2 - Toronto 1"))
        self.assertNotIn("live", legs[1])                                  # settled: no live line
        self.assertNotIn("live", legs[2])                                  # no live data yet


class SoFar(unittest.TestCase):
    def test_live_prop_value_from_box_score(self):
        import props_ledger
        box = {"boxscore": {"players": [{"team": {"abbreviation": "MEM"}, "statistics": [
            {"name": "", "keys": ["assists"], "athletes": [{"athlete": {"id": "7", "displayName": "Cameron Boozer"},
                                                           "stats": ["2"]}]}]}]}}
        props_ledger._LIVE[("nba", "1")] = props_ledger.box_stats(box)
        try:
            v = props_ledger.live_value(dict(gid="nba:1", name="Cameron Boozer", market="Assists", line="4+"))
        finally:
            props_ledger._LIVE.pop(("nba", "1"), None)
        self.assertEqual(v, 2.0)

    def test_player_not_yet_in_the_live_box_is_zero(self):
        import props_ledger
        props_ledger._LIVE[("nba", "2")] = props_ledger.box_stats({"boxscore": {"players": []}})
        props_ledger._LIVE[("nba", "2")]["_people"] = [("someone else", "mem", {"assists": 1.0})]
        try:
            v = props_ledger.live_value(dict(gid="nba:2", name="Cameron Boozer", market="Assists", line="4+"))
        finally:
            props_ledger._LIVE.pop(("nba", "2"), None)
        self.assertEqual(v, 0.0)


class LikeRecord(unittest.TestCase):
    def test_props_near_the_same_chance(self):
        import props_ledger
        book = {"a": dict(status="won", league="nfl", market="Receiving Yards", p=0.82),
                "b": dict(status="lost", league="nfl", market="Receiving Yards", p=0.84),
                "c": dict(status="won", league="nfl", market="Receiving Yards", p=0.60),
                "d": dict(status="open", league="nfl", market="Receiving Yards", p=0.80)}
        with mock.patch.object(props_ledger, "load", lambda: book):
            self.assertEqual(props_ledger.like_record("nfl", "Receiving Yards", 0.80),
                             dict(won=1, n=2, said=83))


class CautionLine(unittest.TestCase):
    def test_lists_cautions_or_none(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        import locks
        import ledger
        none = dict(bright=lambda *a, **k: [], calls=lambda b: [])
        with mock.patch.object(locks, "watch_kinds", lambda b: []), \
             mock.patch.object(locks, "watch_pool", lambda *a, **k: [dict(league="nfl", t="teamunder", won=311, n=402, said=82)]), \
             mock.patch.object(locks, "bright_pool", none["bright"]), mock.patch.object(ledger, "call_cautions", none["calls"]):
            self.assertEqual(daily_review.caution_line(), "Cautions in force: NFL teamunder on all saved lines 311/402 vs 82%.")
        with mock.patch.object(locks, "watch_kinds", lambda b: []), mock.patch.object(locks, "watch_pool", lambda *a, **k: []), \
             mock.patch.object(locks, "bright_pool", none["bright"]), mock.patch.object(ledger, "call_cautions", none["calls"]):
            self.assertIsNone(daily_review.caution_line())
        with mock.patch.object(locks, "watch_kinds", lambda b: []), mock.patch.object(locks, "watch_pool", lambda *a, **k: []), \
             mock.patch.object(locks, "bright_pool", lambda *a, **k: [dict(league="nhl", t="over", won=131, n=149, said=84)]), \
             mock.patch.object(ledger, "call_cautions", lambda b: [dict(league="ncaaf", band=70, won=28, n=47, said=75)]):
            self.assertEqual(daily_review.caution_line(), "Cautions in force: NCAAF calls at 70-80% 28/47 vs 75%."
                                                          " Running ahead: NHL over on all saved lines 131/149 vs 84%.")


class ReviewLine(unittest.TestCase):
    def test_daily_review_reports_the_ladder(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        b = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "open")]})
        from unittest import mock
        with mock.patch.object(ladder, "START", "2026-11-03"), \
             mock.patch.object(ladder, "report", lambda bk=None: ladder.__dict__["_report"](b, start="2026-11-03")):
            line = daily_review.ladder_line()
        self.assertIn("run 1, bank $7.59, 1 win(s) in a row", line)
        self.assertIn("today stakes $7.59", line)
        self.assertIn("legs: 2026-11-04|a (won), 2026-11-04|b (won), 2026-11-04|c (won)", line)
        self.assertIn("2026-11-04|e (open)", line)
        self.assertIsNone(daily_review.ladder_line(book({})))
        b2 = book({"2026-11-03": W5, "2026-11-04": W5[:4] + [("e", 0.8, "lost")]})
        with mock.patch.object(ladder, "report", lambda bk=None: ladder.__dict__["_report"](b2, start="2026-11-03")):
            line = daily_review.ladder_line()
        self.assertIn("run 1 ended (peak $7.59, lost on 2026-11-04|e); the next ticket starts again at $1 with the 8 AM card", line)
        self.assertEqual(daily_review.rule_text("2026-11-07"),
                         "the top Locks paying 2x-5x, leg count 1-8 by the best chance of reaching $10,000")
        self.assertEqual(daily_review.rule_text("2026-11-06"), "the top 5 Locks")


    def test_leg_text_live_and_settled(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        self.assertEqual(daily_review.leg_text(dict(label="Over 214.5 points", match="WAS at ATL", tip="7:00 PM", status="open")),
                         "Over 214.5 points (WAS at ATL; 7:00 PM, open)")
        self.assertEqual(daily_review.leg_text(dict(label="Over 214.5 points", match="WAS at ATL", status="open",
                                                    live="Q2 5:12", live_score="ATL 55 - WAS 50")),
                         "Over 214.5 points (WAS at ATL; live Q2 5:12, ATL 55 - WAS 50)")
        self.assertEqual(daily_review.leg_text(dict(label="Alex Caruso: 2+ Assists", match="OKC @ MEM", status="open",
                                                    live="Q1 2:00", live_score="OKC 20 - MEM 18", so_far=1.0)),
                         "Alex Caruso: 2+ Assists (OKC @ MEM; live Q1 2:00, OKC 20 - MEM 18, 1 so far)")
        self.assertEqual(daily_review.leg_text(dict(label="Alex Caruso: 2+ Assists", match="OKC @ MEM", status="open", line="2+",
                                                    live="Q1 2:00", live_score="OKC 20 - MEM 18", so_far=1.0)),
                         "Alex Caruso: 2+ Assists (OKC @ MEM; live Q1 2:00, OKC 20 - MEM 18, 1 so far, needs 1 more)")
        self.assertEqual(daily_review.leg_text(dict(label="Alex Caruso: 2+ Assists", match="OKC @ MEM", status="open", line="2+",
                                                    live="Halftime", live_score="OKC 71 - MEM 49", so_far=3.0)),
                         "Alex Caruso: 2+ Assists (OKC @ MEM; live Halftime, OKC 71 - MEM 49, 3 so far, line reached)")
        self.assertEqual(daily_review.leg_text(dict(label="Under 241.5 points", match="UTA at DAL", status="lost")),
                         "Under 241.5 points (UTA at DAL; LOST)")
        self.assertEqual(daily_review.leg_text(dict(label="Kyle Pitts: 25+ Receiving Yards", match="CIN @ ATL", tip="9:30 AM", status="open",
                                                    prop_rec=dict(won=144, n=176, said=82))),
                         "Kyle Pitts: 25+ Receiving Yards (CIN @ ATL; 9:30 AM, open; props like it 144/176)")


    def test_prop_pace(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review as d
        L = dict(league="nfl", line="25+", so_far=8.0, live="3:19 - 2nd", label="Kyle Pitts: 25+ Receiving Yards", status="open",
                 live_score="ATL 10 - CIN 21", match="CIN @ ATL")
        self.assertEqual(d.prop_pace(L), "on pace for 18, behind the pace it needs")      # 8 in 26.7 of 60 minutes
        self.assertIsNone(d.prop_pace(dict(L, live="10:00 - 1st")))                  # too early
        self.assertIsNone(d.prop_pace(dict(L, so_far=30.0)))                         # already met
        self.assertEqual(d.prop_pace(dict(L, so_far=20.0)), "on pace for 45, on track")
        self.assertIn("8 so far, needs 17 more, on pace for 18, behind the pace it needs", d.leg_text(L))

    def test_pace_text(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review as d
        nba = dict(label="Over 214.5 points", league="nba", live="5:37 - 2nd", live_score="Atlanta Hawks 47 - Washington Wizards 45")
        self.assertEqual(d.pace_text(nba), "on pace for 240 (92 so far, line 214.5, needs 123 more), on track")
        self.assertEqual(d.pace_text(dict(nba, label="Under 241.5 points")), "on pace for 240 (92 so far, line 241.5, room for 149 more), on track")
        self.assertEqual(d.pace_text(dict(nba, live="8:00 - 1st", live_score="A 10 - B 8")), "18 so far, line 214.5, too early to project")
        self.assertEqual(d.pace_text(dict(nba, live="Halftime", live_score="A 60 - B 50")), "on pace for 220 (110 so far, line 214.5, needs 105 more), on track")
        self.assertEqual(d.pace_text(dict(nba, live="2:00 - 4th", live_score="A 110 - B 106")), "already over (216, line 214.5)")
        self.assertEqual(d.pace_text(dict(label="Utah Mammoth under 4.5 goals", league="nhl", live="10:00 - 2nd",
                                          live_score="Montreal Canadiens 2 - Utah Mammoth 2")),
                         "on pace for 4 (2 so far, line 4.5, room for 2 more), on track")
        self.assertIsNone(d.pace_text(dict(label="Alex Caruso: 2+ Assists", league="nba", live="1:00 - 1st", live_score="A 1 - B 2")))
        line = d.leg_text(dict(nba, match="WAS at ATL", status="open"))
        self.assertEqual(line, "Over 214.5 points (WAS at ATL; live 5:37 - 2nd, Atlanta Hawks 47 - Washington Wizards 45, "
                               "on pace for 240 (92 so far, line 214.5, needs 123 more), on track)")


    def test_now_text(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review as d
        legs = [dict(status="won", p=0.8)] * 4 + [dict(status="open", p=0.76)]
        self.assertEqual(d.now_text(legs), "; 4 of 5 won, the ticket now rests on 1 leg, 76% on its stated chance before play")
        legs = [dict(status="won", p=0.8)] * 3 + [dict(status="open", p=0.8), dict(status="open", p=0.5)]
        self.assertEqual(d.now_text(legs), "; 3 of 5 won, the ticket now rests on 2 legs, 40% on their stated chance before play")
        self.assertEqual(d.now_text([dict(status="won", p=0.8), dict(status="lost", p=0.8), dict(status="open", p=0.8)]),
                         "; 1 of 3 won, a leg lost -- the ticket is lost")
        self.assertEqual(d.now_text([dict(status="open", p=0.8)]), "")


    def test_form_line(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        import locks
        F = [dict(league="ncaaf", t="spread", won=185, n=252, said=82.0), dict(league="nba", t="over", won=80, n=100, said=82.0),
             dict(league="nhl", t="over", won=40, n=60, said=83.0)]                     # too few legs
        with mock.patch.object(locks, "pool_form", lambda *a, **k: F), \
             mock.patch.object(locks, "cold_check", lambda *a, **k: {"cold": [80, 100, 81.0], "rest": [410, 500, 81.0]}):
            self.assertEqual(daily_review.form_line(),
                             "Running cold (last 7 days, all saved lines at 70-95%): NCAAF spread 185/252 (73% vs 82%)."
                             " Walk-forward: legs of a type running cold won 80.0% the next day vs 82.0% for the rest"
                             " (100 and 500 legs), so a cold week is noise, not a signal.")
        with mock.patch.object(locks, "pool_form", lambda *a, **k: F[1:]):
            self.assertIsNone(daily_review.form_line())


    def test_card_check(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review as d
        import datetime as dt
        at = lambda h, m: dt.datetime(2026, 11, 8, h, m, tzinfo=d.ET)
        self.assertIsNone(d.card_check(at(7, 59), {"days": {}}))                    # before the card is due
        ok = lambda b: dict(today=dict(legs=[1]))
        self.assertIsNone(d.card_check(at(9, 0), {"days": {"2026-11-08": []}}, report_fn=ok))     # saved, ticket built
        settled = lambda b: dict(today=None, last=dict(day="2026-11-08"))
        self.assertIsNone(d.card_check(at(23, 0), {"days": {"2026-11-08": []}}, report_fn=settled))
        none = lambda b: dict(today=None, last=dict(day="2026-11-07"))
        self.assertTrue(d.card_check(at(9, 0), {"days": {"2026-11-08": []}}, report_fn=none).startswith("MISSING today's ladder ticket"))
        self.assertTrue(d.card_check(at(8, 20), {"days": {"2026-11-07": []}}).startswith("MISSING today's 8 AM Locks card (2026-11-08)"))


ladder._report = ladder.report


class LegsByType(unittest.TestCase):
    def test_types(self):
        import ladder
        T = ladder.leg_type
        self.assertEqual([T(dict(label="Over 208.5 points")), T(dict(label="Akron Zips under 23.5 points")),
                          T(dict(label="NC State Wolfpack +15.5")), T(dict(label="San Antonio Spurs to win")),
                          T(dict(label="Kuzma: 2+ Assists", kind="prop")), T(dict(label="Chelsea or draw"))],
                         ["total", "team total", "spread", "win", "prop", "win"])
        G = [dict(label="Over 1.5", status="won", p=0.8), dict(label="Over 2.5", status="lost", p=0.7),
             dict(label="A +3.5", status="won", p=0.75), dict(label="B to win", status="open", p=0.7)]
        self.assertEqual(ladder.legs_by_type(G), {"total": dict(won=1, n=2, said=75.0), "spread": dict(won=1, n=1, said=75.0)})


class SkipCompare(unittest.TestCase):
    def test_compare(self):
        import ladder
        legs = {"a": dict(label="Over 200.5", p=0.8, price="-400", gid="g1", status="won"),
                "b": dict(label="Over 210.5", p=0.8, price="-400", gid="g2", status="won"),
                "c": dict(label="Over 220.5", p=0.8, price="-400", gid="g3", status="won"),
                "d": dict(label="P: 2+ Assists", kind="prop", p=0.9, price="-400", gid="g4", status="lost"),
                "e": dict(label="Over 230.5", p=0.78, price="-400", gid="g5", status="won")}
        out = ladder.skip_compare(dict(days={"2026-11-01": list(legs)}, legs=legs))
        self.assertEqual((out["all"][:2], out["without"][:2], out["kinds"]), ([0, 1], [1, 1], ["prop"]))


class LegsByKind(unittest.TestCase):
    def test_split(self):
        import ladder
        G = [dict(kind="prop", status="won", p=0.8), dict(kind="prop", status="lost", p=0.8),
             dict(kind="game", status="won", p=0.75), dict(status="won", p=0.75), dict(kind="game", status="open", p=0.7)]
        self.assertEqual(ladder.legs_by_kind(G), {"prop": dict(won=1, n=2, said=80.0), "game": dict(won=2, n=2, said=75.0)})


if __name__ == "__main__":
    unittest.main()


class CallsStudy(unittest.TestCase):
    def test_calls_study(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import ladder_study
        book = {f"{d}{i}": dict(date=f"2026-11-0{d}", conf=80 - i, status="won" if (d, i) != (1, 1) else "lost", price="-200")
                for d in (1, 2, 3, 4) for i in range(3)}
        r = ladder_study.calls_study(book, sizes=(2,))
        self.assertEqual(r[(2, "first")], dict(won=1, n=2, pays=2.25))
        self.assertEqual(r[(2, "second")], dict(won=2, n=2, pays=2.25))


class ComboStudy(unittest.TestCase):
    def test_combo_study(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import ladder_study
        legs = {f"d{i}": dict(gid=f"g{i}", label=str(i), price="-200", p=0.75, status="won") for i in range(3)}
        b = {"days": {"2026-11-01": list(legs)}, "legs": legs}
        r = ladder_study.combo_study(b, pools=(3,), maxes=(2,))
        self.assertEqual(r[(3, 2)], dict(won=1, n=1))        # two -200 legs: 2.25x, both won


class ReviewVsTop4(unittest.TestCase):
    def test_vs_top4_in_ladder_line(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        rep = dict(runs=5, bank=1.0, streak=0, best=9.57, wins_needed=14, target=10000.0,
                   today=dict(stake=1.0, pays=2.08, prob=0.48, legs=[dict(label="A", status="open"), dict(label="B", status="open")],
                              vs_top4=dict(prob=0.41, pays=2.44)))
        with mock.patch.object(ladder, "report", lambda bk=None: rep):
            line = daily_review.ladder_line()
        self.assertIn("today stakes $1.00 at 2.08x (48% est.), the best-chance 2x-5x combination (2 legs) against 41% at 2.44x"
                      " for the plain top 4", line)


class RunsLine(unittest.TestCase):
    def test_runs_line(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        H = [dict(start="2026-11-03", status="lost", days=3, peak=9.57, lost_on=["FAU under 41.5"]),
             dict(start="2026-11-09", status="live", days=1, peak=2.08, lost_on=[])]
        with mock.patch.object(ladder, "report", lambda bk=None: dict(history=H)):
            self.assertEqual(daily_review.runs_line(), "Ladder runs: 1) 2026-11-03, 3 days, peak $9.57, lost on FAU under 41.5;"
                                                       " 2) 2026-11-09, 1 day, peak $2.08, live.")
        with mock.patch.object(ladder, "report", lambda bk=None: dict(history=[])):
            self.assertIsNone(daily_review.runs_line())
