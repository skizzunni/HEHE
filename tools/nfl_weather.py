"""Kickoff weather for a day's outdoor NFL games (information only).

User, 2026-11-25: "on top of just data and stuff, u need to see what other side
brings". Thanksgiving's KC @ BUF was forecast to rain all game, and the ticket
had three passing / receiving legs there; nothing on the ticket said so. This
prints, for each NFL game of a day: indoor (no weather) or the National Weather
Service hourly forecast for the kickoff hours -- temperature, wind, sky and
chance of rain.

It changes no pick. Props were never tested against weather (no reachable
source keeps game-time weather; ESPN keeps none), and indoor vs outdoor showed
nothing (README, 770 legs). It is there so a rain or wind game is seen before
the ticket is placed.

  python3 tools/nfl_weather.py [today|tomorrow|YYYY-MM-DD]
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={}"
VENUE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/venues/{}"
GEO = "https://geocoding-api.open-meteo.com/v1/search?count=5&language=en&format=json&name={}"
POINT = "https://api.weather.gov/points/{:.4f},{:.4f}"
HOURS = 4                       # kickoff and the three hours after it


def _get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "ticket-research (weather check)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def venue(gid, get=_get):
    """(name, indoor, city, state) for a game, from ESPN."""
    v = ((get(SUMMARY.format(gid)).get("gameInfo") or {}).get("venue") or {})
    d = get(VENUE.format(v["id"])) if v.get("id") else {}
    a = d.get("address") or v.get("address") or {}
    return d.get("fullName") or v.get("fullName"), bool(d.get("indoor")), a.get("city"), a.get("state")


def coords(city, state, get=_get):
    """(lat, lon) of a US city; None when not found."""
    res = (get(GEO.format(urllib.parse.quote(city))) or {}).get("results") or []
    us = [r for r in res if r.get("country_code") == "US"]
    return (us[0]["latitude"], us[0]["longitude"]) if us else None


def forecast(lat, lon, start, get=_get):
    """NWS hourly periods from `start` (aware datetime) for HOURS hours."""
    hourly = get(POINT.format(lat, lon))["properties"]["forecastHourly"]
    out = []
    for p in get(hourly)["properties"]["periods"]:
        t = dt.datetime.fromisoformat(p["startTime"])
        if start - dt.timedelta(minutes=59) <= t < start + dt.timedelta(hours=HOURS):
            out.append(p)
    return out


def summarize(periods):
    """'37-38F, wind 10-13 mph, Rain, chance of rain 76-100%' from NWS periods."""
    if not periods:
        return "no forecast for kickoff yet"
    temps = [p["temperature"] for p in periods]
    winds = [int(w) for p in periods for w in str(p.get("windSpeed", "")).replace("mph", "").replace("to", " ").split()
             if w.isdigit()]
    pops = [(p.get("probabilityOfPrecipitation") or {}).get("value") or 0 for p in periods]
    sky = max(set(p["shortForecast"] for p in periods), key=[p["shortForecast"] for p in periods].count)
    rng = lambda xs, u: (f"{min(xs)}{u}" if min(xs) == max(xs) else f"{min(xs)}-{max(xs)}{u}") if xs else "?"
    return f"{rng(temps, 'F')}, wind {rng(winds, ' mph')}, {sky}, chance of rain {rng(pops, '%')}"


def lines(rows, get=_get):
    out = []
    for r in rows:
        if r.get("lg") != "nfl":
            continue
        try:
            name, indoor, city, state = venue(r["id"], get)
            if indoor:
                out.append(f"  {r['game']}: indoors ({name}) -- no weather")
                continue
            ll = coords(city, state, get)
            if not ll:
                out.append(f"  {r['game']}: outdoors ({name}) -- city not found for a forecast")
                continue
            start = dt.datetime.fromisoformat(str(r["start"]).replace("Z", "+00:00"))
            out.append(f"  {r['game']}: outdoors ({name}, {city} {state}) -- {summarize(forecast(*ll, start, get))}")
        except Exception as ex:                     # one game's failure never hides the rest
            out.append(f"  {r.get('game')}: weather unavailable ({type(ex).__name__})")
    if out:
        out.insert(0, "Kickoff weather (National Weather Service; information only -- props were never tested "
                      "against weather, indoor vs outdoor showed nothing):")
    return out


def main(arg="today"):
    import build_ticket
    import slate_sheet
    day = build_ticket.resolve_day(arg)
    print("\n".join(lines(slate_sheet.main(day))) or f"no NFL games on {day}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "today")
