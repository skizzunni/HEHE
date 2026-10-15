"""Feed probe, run on GitHub's runners. Round 11: which side an RFQ requester
gets on accept, and what price they pay."""
import html
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
PAGES = [
    "https://docs.kalshi.com/websockets/communications.md",
    "https://docs.kalshi.com/api-reference/communications/create-quote.md",
    "https://docs.kalshi.com/fix/rfq-messages.md",
    "https://blog.predictefy.com/kalshi-rfq-api",
    "https://www.oddpool.com/research/kalshi-rfq-market-makers",
]
KEY = re.compile(r"(?i)yes_bid|no_bid|accepted_side|accept|side|requester|parlay|combo|price|pay|vig|fair|seconds|quotes per")


def get(url):
    time.sleep(0.4)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERROR {e}"


for u in PAGES:
    t = get(u)
    if not u.endswith(".md"):
        t = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", t)
        t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    keep = set()
    for i, l in enumerate(lines):
        if KEY.search(l):
            keep.update(range(max(0, i - 2), i + 3))
    out = "\n".join(lines[i] for i in sorted(keep))
    print(f"\n\n######## {u} ({len(t)} chars, {len(out)} kept)\n{out[:12000]}")
