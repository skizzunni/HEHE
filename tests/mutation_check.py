"""Do the tests actually catch what they claim to? Break each protected rule
on purpose and require the suite to fail -- then put the code back.

    python3 tests/mutation_check.py

Runs every check with Python's bytecode cache off (-B). Without that, a
mutation that keeps a line's length (10.5 -> 12.0) restored within the same
second can leave the mutated .pyc in use: found 2026-10-18, when a restored
stacks.py still ran with the broken NFL split.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (file, original text, broken text, the check that must catch it)
MUTATIONS = [
    ("locks.py", 'SOCCER_KINDS = {"dc"}', 'SOCCER_KINDS = {"dc", "total", "spread"}',
     "test_soccer_only_validated_kinds"),
    ("fanduel.py", 'if min(_team_score(g["home"], away), _team_score(g["away"], home)) > s:',
     "if False:", "test_reversed_fixture_rejected"),
    ("stacks.py", 'SPLIT_TOTAL = {"nfl": (12.0, 14.5)}', 'SPLIT_TOTAL = {"nfl": (10.5, 10.5)}',
     "test_nfl_totals_upper_tail"),
    ("locks.py", "DEC_MIN, DEC_MAX = 1.25, 1.834", "DEC_MIN, DEC_MAX = 1.05, 1.834",
     "test_regular_card_price_window"),
    ("bot/kalshi_bot.py", "    if built.tzinfo is None:\n        return None\n", "",
     "test_board_age"),
    ("ufc_props.py", "    return m >= r * ROUND_MIN - 0.01\n", "    return None\n", "test_clock_fallback"),
    ("tools/daily_review.py", "STUCK_DAYS = 6 ", "STUCK_DAYS = 99 ", "test_stuck"),
    ("bot/kalshi_bot.py", 'h["result"] = "expired"', "pass", "test_practice_tickets_never_block_forever"),
    ("board.html", "(HL.stuck || []).map(x => '<li>Never settled: ' + esc(x) + '</li>').join(\"\")", "''", "health box"),
    ("props_ledger.py", "return not (league not in NOT_SOCCER and", "return not (league in SOCCER and",
     "test_soccer_shots_off_in_every_soccer_league"),
    ("rebuild_board.py", "return props_ledger.offered(w[1], w[2])", "return True",
     "test_alarm_dropped_once_market_is_off"),
    ("locks.py", 'res = "lost" if "lost" in st else', 'res = "won" if "lost" in st else', "test_plays_graded"),
    ("board.html", "+ playsLine(R.plays)", "", "Winners parlay's own record"),
    ("stacks.py", '    if push and push(h, a):\n        return "push"\n', "", "test_integer_lines_push"),
    ("props_ledger.py", 'g = grp.get("name") or grp.get("type") or ""', 'g = grp.get("name") or ""',
     "test_mlb_group_from_type"),
    ("props_ledger.py", 'return (None, "unresolved") if same_last else (None, "absent")',
     'return (None, "absent")', "test_names"),
    ("props_ledger.py", 'n = unicodedata.normalize("NFKD", n', 'n = ("NFKD", n', "test_names"),
    ("lottery.py", "return min(max(float(price_p), 0.0), 0.99)",
     "return min(price_p * BAND_VALUE.get(min(int(price_p * 10), 9), 1.0), 0.99)", "test_market_chance"),
    ("locks.py", "        if any(x.split(\"|\", 1)[0] == L[\"gid\"] for x in keys):\n            continue\n", "",
     "test_one_leg_per_game_and_extras_apart"),
    ("locks.py", 'return a / (a + b), "two-sided"', 'return (1 / d) / lottery.FD_HOLD, "two-sided"',
     "test_two_sided_devig"),
    ("locks.py", "while len(blocks) > 1 and blocks", "while False and blocks", "test_alternate_lines_in_order"),
    ("ledger.py", 'and bool(prev.get("dc")) == entry["dc"])', ')', "test_history"),
    ("tools/daily_review.py", "W_GRID = [i / 20 for i in range(0, 9)]", "W_GRID = [i / 20 for i in range(1, 9)]",
     "test_weights_need_held_out_gain"),
    ("tools/daily_review.py", "        if not ok:\n            detail[lg]", "        if False:\n            detail[lg]",
     "test_no_fallback_cutoff"),
    ("fanduel.py", "return g if gap <= START_SLACK_H * 3600 else None", "return cands[0]",
     "test_doubleheader_by_start"),
    ("dashboard.py", "    return t > (now or dt.datetime.now(ET))", "    return True", "test_stale_pregame_after_kickoff"),
    ("locks.py", "legs=res[\"pool\"], card=list(keys),", "legs=res[\"pool\"][1:], card=list(keys),",
     "test_replay_gives_the_same_card"),
    ("policy.py", 'w = (_W.get("weights") or {}).get(league)', 'w = {"nfl": 0.30}.get(league)',
     "test_atlanta_follows_the_tested_policy"),
    ("calls.py", "    return _MIN.get(_group(league))", "    return _MIN.get(_group(league), 0.75 if _group(league) == 'soccer' else 0.60)",
     "test_strong_calls_only_where_qualified"),
    ("participation.py", 'return "starting" if s else "on the bench"', 'return "starting"',
     "test_goalkeepers_need_a_confirmed_start"),
    ("lottery.py", "            if not participation.eligible(P):\n                continue\n            pf", "            pf",
     "test_backup_keeper_never_reaches_a_ticket"),
    ("lottery.py", "fin = [x for x in inband if", "fin = [x for x in pool if", "test_finish_with_the_likeliest_line"),
    ("policy.py", "return bool(n and g >= 2 * n ** 0.5 and r.get(\"better\"))",
     "return bool(n and g >= n ** 0.5 and r.get(\"better\"))", "test_pregame_inputs_need_two_standard_errors"),
    ("locks.py", "        if L[\"p\"] - nxt[\"p\"] < max(uncert(L), uncert(nxt)):", "        if False:",
     "test_colts_near_tie"),
    ("board.html", "<th class=\"num\">New right, old wrong</th><th class=\"num\">Old right, new wrong</th>", "",
     "Results must list each tested change"),
    ("props_ledger.py", "return float(sum(st.get(k) or 0.0 for k in keys))",
     "return None if any(st.get(k) is None for k in keys) else float(sum(st[k] for k in keys))",
     "test_football_missing_group_is_zero"),
    ("integrity.py", "not 0 <= v <= 1:", "False:", "test_catches_bad_values"),
    ("board.html", "z.prob >= 0.8", "z.prob >= 0.95", "Winners parlay"),
    ("board.html", "if (mins < 20) { if (el) el.remove(); return; }", "return;",
     "stale copy must show the banner"),
]


def run_suite():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    unit = subprocess.run([sys.executable, "-B", "-W", "ignore", "-m", "unittest", "discover",
                           "-s", "tests"], cwd=ROOT, capture_output=True, text=True, env=env)
    ui = subprocess.run([sys.executable, "-B", "tests/ui_check.py"], cwd=ROOT,
                        capture_output=True, text=True, env=env)
    return unit.stdout + unit.stderr + ui.stdout + ui.stderr, unit.returncode == 0 and ui.returncode == 0


def main():
    out, ok = run_suite()
    if not ok:
        print(out)
        sys.exit("the suite fails on unmodified code; fix that first")
    bad = 0
    for path, old, new, expect in MUTATIONS:
        full = os.path.join(ROOT, path)
        keep = tempfile.mktemp()
        shutil.copy2(full, keep)
        try:
            src = open(full).read()
            if src.count(old) != 1:
                print(f"STALE MUTATION {path}: text not found once -- update this list")
                bad += 1
                continue
            open(full, "w").write(src.replace(old, new, 1))
            out, ok = run_suite()
            caught = (not ok) and expect in out
            print(("caught " if caught else "MISSED ") + f"{path}: {expect}")
            bad += not caught
        finally:
            shutil.copy2(keep, full)
            os.unlink(keep)
    out, ok = run_suite()
    print("suite after restore:", "OK" if ok else "FAILING")
    sys.exit(1 if bad or not ok else 0)


if __name__ == "__main__":
    main()
