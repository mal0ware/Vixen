"""Tests for vixen.services.weather.

Covers the pure parse and helper functions. We don't hit Open-Meteo over
the network in unit tests — that would be flaky and rate-limit-prone.
The HTTP layer is one thin aiohttp call; integration testing it belongs
in a smoke test, not the unit suite.
"""

from __future__ import annotations

from vixen.services.weather import (
    _parse_place,
    _parse_weather,
    describe_code,
)

# ---------------------------------------------------------------- #
# describe_code
# ---------------------------------------------------------------- #


def test_describe_known_code():
    desc, emoji = describe_code(0)
    assert "Clear" in desc
    assert emoji == "☀️"


def test_describe_unknown_code_falls_back():
    """Future Open-Meteo codes (or noise) shouldn't crash — generic fallback."""
    desc, emoji = describe_code(999)
    assert desc == "Unknown conditions"
    assert emoji == "❓"


# ---------------------------------------------------------------- #
# _parse_place
# ---------------------------------------------------------------- #


def test_parse_place_picks_top_result():
    payload = {
        "results": [
            {
                "name": "Boston",
                "admin1": "Massachusetts",
                "country": "United States",
                "latitude": 42.36,
                "longitude": -71.06,
            },
            {
                "name": "Boston",
                "admin1": "England",
                "country": "United Kingdom",
                "latitude": 52.97,
                "longitude": -0.02,
            },
        ]
    }
    place = _parse_place(payload)

    assert place is not None
    assert place.name == "Boston"
    assert place.region == "Massachusetts"
    assert place.country == "United States"
    assert place.latitude == 42.36
    assert place.longitude == -71.06


def test_parse_place_no_results_returns_none():
    """Payload with no `results` array → None, not an exception."""
    assert _parse_place({}) is None
    assert _parse_place({"results": []}) is None


def test_parse_place_missing_optional_fields():
    """admin1 and country can be absent — Place still constructs."""
    payload = {
        "results": [
            {
                "name": "Antarctica Base",
                "latitude": -77.85,
                "longitude": 166.67,
            }
        ]
    }
    place = _parse_place(payload)

    assert place is not None
    assert place.name == "Antarctica Base"
    assert place.region is None
    assert place.country is None


# ---------------------------------------------------------------- #
# _parse_weather
# ---------------------------------------------------------------- #


def _sample_payload(days: int = 3) -> dict:
    """Build a minimal Open-Meteo response shaped like the real one."""
    return {
        "current": {
            "temperature_2m": 21.4,
            "apparent_temperature": 22.0,
            "relative_humidity_2m": 55,
            "weather_code": 2,
            "wind_speed_10m": 12.3,
            "is_day": 1,
        },
        "daily": {
            "time": [f"2026-05-{(i + 2):02d}" for i in range(days)],
            "temperature_2m_max": [25.0 + i for i in range(days)],
            "temperature_2m_min": [15.0 + i for i in range(days)],
            # Cycle through a few codes so days=7 still produces a full list.
            "weather_code": [(2, 1, 0)[i % 3] for i in range(days)],
        },
    }


def test_parse_weather_extracts_current_fields():
    weather = _parse_weather(_sample_payload(days=3))

    assert weather.temperature_c == 21.4
    assert weather.feels_like_c == 22.0
    assert weather.humidity == 55
    assert weather.weather_code == 2
    assert weather.wind_kph == 12.3
    assert weather.is_day is True


def test_parse_weather_labels_today_tomorrow():
    """First two days get friendly labels; later days fall back to dates."""
    weather = _parse_weather(_sample_payload(days=4))

    labels = [d[0] for d in weather.daily]
    assert labels[0] == "Today"
    assert labels[1] == "Tomorrow"
    # Day 3 onward uses the raw date.
    assert labels[2].startswith("2026-05-")
    assert labels[3].startswith("2026-05-")


def test_parse_weather_daily_count_matches_input():
    for n in (1, 3, 7):
        weather = _parse_weather(_sample_payload(days=n))
        assert len(weather.daily) == n


def test_parse_weather_daily_high_low_codes():
    weather = _parse_weather(_sample_payload(days=2))
    label, high, low, code = weather.daily[0]
    assert label == "Today"
    assert high == 25.0
    assert low == 15.0
    assert code == 2


def test_parse_weather_is_day_zero_means_night():
    payload = _sample_payload(days=1)
    payload["current"]["is_day"] = 0
    weather = _parse_weather(payload)
    assert weather.is_day is False
