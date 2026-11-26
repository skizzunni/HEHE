import os
import sys
import unittest

sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "tools")]
import nfl_weather as W  # noqa: E402

P = [{"startTime": "2026-11-26T20:00:00-05:00", "temperature": 37, "windSpeed": "13 mph", "shortForecast": "Rain",
      "probabilityOfPrecipitation": {"value": 100}},
     {"startTime": "2026-11-26T21:00:00-05:00", "temperature": 38, "windSpeed": "10 to 12 mph", "shortForecast": "Rain",
      "probabilityOfPrecipitation": {"value": 76}},
     {"startTime": "2026-11-27T09:00:00-05:00", "temperature": 50, "windSpeed": "30 mph", "shortForecast": "Sunny",
      "probabilityOfPrecipitation": {"value": 0}}]


def fake(u):
    if "summary" in u:
        return {"gameInfo": {"venue": {"id": "1" if "event=9" in u else "2"}}}
    if u.endswith("/venues/1"):
        return {"fullName": "Highmark Stadium", "indoor": False, "address": {"city": "Orchard Park", "state": "NY"}}
    if u.endswith("/venues/2"):
        return {"fullName": "Ford Field", "indoor": True, "address": {"city": "Detroit", "state": "MI"}}
    if "geocoding" in u:
        return {"results": [{"country_code": "US", "latitude": 42.77, "longitude": -78.74}]}
    if "points" in u:
        return {"properties": {"forecastHourly": "https://nws/hourly"}}
    return {"properties": {"periods": P}}


class Weather(unittest.TestCase):
    def test_outdoor_game_gets_kickoff_hours_only(self):
        out = W.lines([{"lg": "nfl", "id": "9", "game": "KC @ BUF", "start": "2026-11-27T01:20Z"}], fake)
        self.assertEqual(out[1], "  KC @ BUF: outdoors (Highmark Stadium, Orchard Park NY) -- 37-38F, wind 10-13 mph, "
                                 "Rain, chance of rain 76-100%")

    def test_indoor_game_says_so(self):
        out = W.lines([{"lg": "nfl", "id": "5", "game": "CHI @ DET", "start": "2026-11-26T17:30Z"}], fake)
        self.assertEqual(out[1], "  CHI @ DET: indoors (Ford Field) -- no weather")

    def test_a_failure_is_named_not_raised(self):
        def boom(u):
            raise OSError("down")
        out = W.lines([{"lg": "nfl", "id": "9", "game": "KC @ BUF", "start": "2026-11-27T01:20Z"}], boom)
        self.assertEqual(out[1], "  KC @ BUF: weather unavailable (OSError)")

    def test_other_leagues_skipped(self):
        self.assertEqual(W.lines([{"lg": "nba", "id": "1", "game": "x"}], fake), [])


if __name__ == "__main__":
    unittest.main()
