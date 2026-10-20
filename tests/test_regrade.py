"""Item 9: explicit settlement states, policy version on every pick, and the
nightly independent re-grade from a second feed."""
import datetime as dt
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ledger                                             # noqa: E402
import regrade                                            # noqa: E402


def summary(a, sa, b, sb, name="STATUS_FINAL", completed=True, detail="FT", halves=None):
    def team(n, s, h):
        x = dict(team=dict(displayName=n), score=str(s))
        if h:
            x["linescores"] = [dict(value=v) for v in h]
        return x
    return dict(header=dict(competitions=[dict(
        status=dict(type=dict(name=name, completed=completed, shortDetail=detail)),
        competitors=[team(a, sa, (halves or {}).get(a)), team(b, sb, (halves or {}).get(b))])]))


def pick(**kw):
    e = dict(league="nhl", pick="Boston Bruins", status="won", date="2026-10-18")
    e.update(kw)
    return e


class Independent(unittest.TestCase):
    def run_one(self, e, sm, key="nhl:1"):
        return regrade.regrade({key: e}, "2026-10-01", "2026-10-31", fetch=lambda lg, cid: sm)

    def test_agrees_and_disagrees(self):
        r = self.run_one(pick(), summary("Boston Bruins", 3, "Toronto Maple Leafs", 2))
        self.assertEqual((r["checked"], r["mismatches"]), (1, []))
        r = self.run_one(pick(), summary("Boston Bruins", 2, "Toronto Maple Leafs", 3))
        self.assertEqual(r["mismatches"][0]["regrade"], "lost")

    def test_never_trusts_the_winner_flag_and_ignores_case(self):
        sm = summary("BOSTON BRUINS", 3, "Toronto Maple Leafs", 2)
        sm["header"]["competitions"][0]["competitors"][1]["winner"] = True     # a wrong flag
        self.assertEqual(self.run_one(pick(), sm)["mismatches"], [])

    def test_soccer_draws_and_ninety_minutes(self):
        d = summary("Viking FK", 1, "Fredrikstad", 1)
        e = pick(league="nor", pick="Viking FK", status="lost")
        self.assertEqual(self.run_one(e, d, "nor:1")["mismatches"], [])              # straight: lost on a draw
        self.assertEqual(self.run_one(dict(e, dc=True), d, "nor:1")["mismatches"][0]["regrade"], "won")
        aet = summary("Viking FK", 2, "Fredrikstad", 1, name="STATUS_FINAL_AET",
                      halves={"Viking FK": [0, 1, 1], "Fredrikstad": [1, 0, 0]})
        self.assertEqual(self.run_one(e, aet, "nor:1")["mismatches"], [])            # 1-1 after 90

    def test_explicit_void_states(self):
        pp = summary("Boston Bruins", 0, "Toronto Maple Leafs", 0, name="STATUS_POSTPONED", completed=False)
        r = self.run_one(pick(status="void", state="postponed"), pp)
        self.assertEqual(r["mismatches"], [])
        r = self.run_one(pick(status="won"), pp)
        self.assertEqual(r["mismatches"][0]["regrade"], "postponed")


class LedgerStates(unittest.TestCase):
    def grade(self, res):
        path = os.path.join(tempfile.mkdtemp(), "ledger.json")
        real_l, real_f = ledger.LEDGER, ledger._final
        ledger.LEDGER, ledger._final = path, (lambda lg, cid, e=None: res)
        try:
            ledger.save({"nhl:1": pick(status="open")})
            ledger.grade()
            return ledger.load()["nhl:1"]
        finally:
            ledger.LEDGER, ledger._final = real_l, real_f

    def test_states(self):
        e = self.grade(dict(live=False, void=True, scores={}, state="Postponed", kind="postponed"))
        self.assertEqual((e["status"], e["state"]), ("void", "postponed"))
        e = self.grade(dict(live=False, winner="Boston Bruins", scores={}, date="2026-10-18"))
        self.assertEqual((e["status"], e["state"]), ("won", "won"))

    def test_walkover_and_kinds(self):
        self.assertEqual(ledger._void_kind(dict(name="STATUS_CANCELED")), "cancelled")
        self.assertEqual(ledger._void_kind(dict(name="STATUS_FORFEIT")), "walkover")

    def test_policy_version_on_every_pick(self):
        import policy
        path = os.path.join(tempfile.mkdtemp(), "ledger.json")
        now = dt.datetime.now(dt.timezone.utc)
        row = dict(id="nhl:5", mypick="A", myside="home", myconf=0.6, label="B @ A", price_at=now.isoformat(),
                   legs=[dict(side="home", price="-150", at=now.isoformat())],
                   mkt=dict(start=(now + dt.timedelta(hours=3)).isoformat()))
        real = ledger.LEDGER
        ledger.LEDGER = path
        try:
            ledger.record(dict(dates=("20261020", "20261021"), slots=dict(today={"nhl": [row]}, tomorrow={})))
            e = ledger.load()["nhl:5"]
        finally:
            ledger.LEDGER = real
        self.assertEqual(e["policy_version"], policy.version())


if __name__ == "__main__":
    unittest.main()
