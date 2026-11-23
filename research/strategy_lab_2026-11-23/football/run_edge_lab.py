"""Run tools/edge_lab.py unchanged for NFL and college football only, with its
cache and output redirected into this folder (nothing written under tools/ or
data/). Run with PYTHONDONTWRITEBYTECODE=1 so no __pycache__ lands in tools/.

    PYTHONDONTWRITEBYTECODE=1 python run_edge_lab.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
import backtest as B  # noqa: E402

from concurrent.futures import ThreadPoolExecutor  # noqa: E402

def _pool(*a, **k):                     # 4 workers: keeps total requests in flight <= 8
    return ThreadPoolExecutor(max_workers=4)

B.CACHE = os.path.join(HERE, "cache_edge_lab")
B.ThreadPoolExecutor = _pool
import edge_lab as E  # noqa: E402
E.ThreadPoolExecutor = _pool

E.OUT = os.path.join(HERE, "edge_lab.json")
E.LEAGUES = ("nfl", "ncaaf")
E.main()
