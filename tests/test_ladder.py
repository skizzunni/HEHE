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
        with mock.patch.object(locks, "watch_kinds", lambda b: []), \
             mock.patch.object(locks, "watch_pool", lambda *a, **k: [dict(league="nfl", t="teamunder", won=311, n=402, said=82)]):
            self.assertEqual(daily_review.caution_line(), "Cautions in force: NFL teamunder on all saved lines 311/402 vs 82%.")
        with mock.patch.object(locks, "watch_kinds", lambda b: []), mock.patch.object(locks, "watch_pool", lambda *a, **k: []):
            self.assertIsNone(daily_review.caution_line())


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
        self.assertIn("run 1 ended (peak $7.59, lost on 2026-11-04|e); the next ticket starts again at $1", line)


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


    def test_pace_text(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review as d
        nba = dict(label="Over 214.5 points", league="nba", live="5:37 - 2nd", live_score="Atlanta Hawks 47 - Washington Wizards 45")
        self.assertEqual(d.pace_text(nba), "on pace for 240 (92 so far, line 214.5), on track")
        self.assertEqual(d.pace_text(dict(nba, label="Under 241.5 points")), "on pace for 240 (92 so far, line 241.5), on track")
        self.assertEqual(d.pace_text(dict(nba, live="8:00 - 1st", live_score="A 10 - B 8")), "18 so far, line 214.5, too early to project")
        self.assertEqual(d.pace_text(dict(nba, live="Halftime", live_score="A 60 - B 50")), "on pace for 220 (110 so far, line 214.5), on track")
        self.assertEqual(d.pace_text(dict(nba, live="2:00 - 4th", live_score="A 110 - B 106")), "already over (216, line 214.5)")
        self.assertEqual(d.pace_text(dict(label="Utah Mammoth under 4.5 goals", league="nhl", live="10:00 - 2nd",
                                          live_score="Montreal Canadiens 2 - Utah Mammoth 2")),
                         "on pace for 4 (2 so far, line 4.5), on track")
        self.assertIsNone(d.pace_text(dict(label="Alex Caruso: 2+ Assists", league="nba", live="1:00 - 1st", live_score="A 1 - B 2")))
        line = d.leg_text(dict(nba, match="WAS at ATL", status="open"))
        self.assertEqual(line, "Over 214.5 points (WAS at ATL; live 5:37 - 2nd, Atlanta Hawks 47 - Washington Wizards 45, "
                               "on pace for 240 (92 so far, line 214.5), on track)")


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


ladder._report = ladder.report


if __name__ == "__main__":
    unittest.main()
