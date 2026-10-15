"""Feed probe, run on GitHub's runners. Round 10: Kalshi's RFQ documentation
(the sandbox cannot reach docs.kalshi.com)."""
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
D = "https://docs.kalshi.com"
PAGES = [
    "/getting_started/rfqs.md",
    "/api-reference/communications/create-rfq.md",
    "/api-reference/communications/get-quotes.md",
    "/api-reference/communications/get-rfq.md",
    "/api-reference/communications/accept-rfq-quote.md",
    "/api-reference/communications/accept-quote.md",
    "/api-reference/communications/delete-rfq.md",
    "/api-reference/communications/get-quote.md",
    "/llms.txt",
]


def get(url):
    time.sleep(0.4)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERROR {e}"


for p in PAGES:
    t = get(D + p)
    if p == "/llms.txt":
        t = "\n".join(l for l in t.splitlines() if re.search(r"(?i)rfq|quote|communicat", l))
    print(f"\n\n######## {p} ({len(t)} chars)\n{t[:9000]}")
