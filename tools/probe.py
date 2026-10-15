"""Feed probe, run on GitHub's runners (the dev sandbox cannot reach ESPN).
Round 4: can FanDuel's public content API give the market/selection ids a
bet-slip deep link needs? And does Fanatics expose anything comparable?"""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json"}


def get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except ValueError:
                return r.status, body[:300].decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


AK = "FhMFpcPWXMeyZxOx"
for state in ("nj", "ny", "pa", "va", "il"):
    for page, extra in (("CUSTOM", "&customPageId=nfl"), ("CUSTOM", "&customPageId=nhl"),
                        ("CUSTOM", "&customPageId=nba")):
        url = (f"https://sbapi.{state}.sportsbook.fanduel.com/api/content-managed-page"
               f"?page={page}{extra}&_ak={AK}&timezone=America%2FNew_York")
        st, d = get(url)
        if isinstance(d, dict):
            att = d.get("attachments") or {}
            ev = att.get("events") or {}
            mk = att.get("markets") or {}
            print(f"{state} {extra}: status {st} events={len(ev)} markets={len(mk)}")
            if ev:
                e = next(iter(ev.values()))
                print("   event", {k: e.get(k) for k in ("eventId", "name", "openDate")})
            if mk:
                m = next(iter(mk.values()))
                print("   market", {k: m.get(k) for k in ("marketId", "marketName", "marketType", "eventId")})
                r = (m.get("runners") or [{}])[0]
                print("   runner", {k: r.get(k) for k in ("selectionId", "runnerName", "handicap")},
                      json.dumps(r.get("winRunnerOdds") or {})[:200])
        else:
            print(f"{state} {extra}: status {st} {str(d)[:160]}")
    print()

for url in ("https://sportsbook.fanatics.com/",
            "https://sportsbook.fanduel.com/",
            "https://sportsbook.fanduel.com/addToBetslip?marketId=1.1&selectionId=1"):
    st, d = get(url)
    print(url, "->", st, str(d)[:120].replace("\n", " "))
