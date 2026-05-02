"""Weather service — Open-Meteo client.

Why Open-Meteo: free, no API key, no rate-limit headaches for personal-bot
volume, decent global coverage. Two endpoints are used:

    geocoding-api.open-meteo.com/v1/search?name=...   city -> (lat, lon)
    api.open-meteo.com/v1/forecast?latitude=...&...    coords -> weather data

The service exposes two public coroutines:

    geocode(city)             -> Place | None
    get_weather(lat, lon, n)  -> Weather

`Place` and `Weather` are frozen dataclasses with only the fields the cog
needs — keeps the surface area small and lets us drop fields the cog never
reads. Anything else from the Open-Meteo response is ignored on parse.

HTTP transport: aiohttp via a single per-process ClientSession reused
across calls (`_get_session`). Re-creating sessions per request leaks
sockets and burns DNS lookups; one shared session with a connection pool
is the standard pattern.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Per-process aiohttp session. Lazily created on first use so importing
# this module from non-event-loop contexts (alembic, ipython before bot
# init) doesn't blow up.
_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    """Return the shared aiohttp session, creating it on first call."""
    global _session
    if _session is None or _session.closed:
        # 10s timeout matches Discord's interaction window — a slow upstream
        # is preferable to leaving the user staring at a stalled command.
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "Vixen-Bot (personal Discord assistant)"},
        )
    return _session


async def close_session() -> None:
    """Close the shared session. Call from bot shutdown to free sockets."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


# --------------------------------------------------------------------------- #
# Models — only the fields we actually render
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Place:
    """One geocoded location. Open-Meteo returns more (admin1, country_code,
    population, etc.) but we only show name + region + country."""

    name: str
    region: str | None        # e.g. "Massachusetts"
    country: str | None       # e.g. "United States"
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class Weather:
    """Current conditions + brief daily forecast.

    `daily` is a list of (label, max_c, min_c, code) tuples for the next
    `days` days starting today. `label` is "Today", "Tomorrow", weekday,
    etc. — pre-formatted by the parser so the cog doesn't repeat date
    arithmetic.
    """

    temperature_c: float
    feels_like_c: float
    humidity: int
    wind_kph: float
    weather_code: int
    is_day: bool
    daily: list[tuple[str, float, float, int]]


# --------------------------------------------------------------------------- #
# Weather-code → human description / emoji
# --------------------------------------------------------------------------- #


# WMO weather codes per Open-Meteo docs. We collapse the full list to the
# common buckets — finer detail (e.g. light vs heavy snow) is in the docs
# if anyone wants to expand it.
_WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Freezing fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Heavy drizzle", "🌧️"),
    61: ("Light rain", "🌦️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Snow", "❄️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Rain showers", "🌦️"),
    81: ("Heavy showers", "🌧️"),
    82: ("Violent showers", "⛈️"),
    85: ("Snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunder + hail", "⛈️"),
    99: ("Severe thunder + hail", "⛈️"),
}


def describe_code(code: int) -> tuple[str, str]:
    """Map a WMO weather code to (description, emoji). Unknown codes
    fall back to a generic label so we never crash on a future code.
    """
    return _WEATHER_CODES.get(code, ("Unknown conditions", "❓"))


# --------------------------------------------------------------------------- #
# Geocoding
# --------------------------------------------------------------------------- #


async def geocode(city: str) -> Place | None:
    """Resolve a city name to a Place. Returns None when no match found.

    Open-Meteo accepts free-form text ("Boston", "Boston, MA", "Boston US"),
    which is friendlier than requiring lat/lon from the user. We pick the
    top match — Open-Meteo's relevance ranking tends to be sensible.
    """
    session = await _get_session()
    params = {
        "name": city,
        "count": 1,
        "language": "en",
        "format": "json",
    }
    async with session.get(_GEOCODE_URL, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()

    return _parse_place(data)


def _parse_place(data: dict) -> Place | None:
    """Extract the top result from the geocoding payload. Test-friendly
    seam — callers can construct fake payloads without touching aiohttp.
    """
    results = data.get("results") or []
    if not results:
        return None
    top = results[0]
    return Place(
        name=top.get("name", "Unknown"),
        region=top.get("admin1"),
        country=top.get("country"),
        latitude=float(top["latitude"]),
        longitude=float(top["longitude"]),
    )


# --------------------------------------------------------------------------- #
# Current weather + forecast
# --------------------------------------------------------------------------- #


async def get_weather(
    latitude: float,
    longitude: float,
    days: int = 3,
) -> Weather:
    """Fetch current conditions + a short daily forecast.

    `days` controls how many forecast days to include (1..7). Today is
    always position 0 in the returned `daily` list.
    """
    if not 1 <= days <= 7:
        raise ValueError(f"days must be 1..7, got {days}")

    session = await _get_session()
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "weather_code",
            "wind_speed_10m",
            "is_day",
        ]),
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
        ]),
        "timezone": "auto",
        "forecast_days": days,
        "wind_speed_unit": "kmh",
        "temperature_unit": "celsius",
    }
    async with session.get(_FORECAST_URL, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()

    return _parse_weather(data)


def _parse_weather(data: dict) -> Weather:
    """Pure parse step — turn Open-Meteo's JSON into a Weather dataclass."""
    current = data["current"]
    daily = data["daily"]

    # Build the per-day list with friendly labels.
    days_out: list[tuple[str, float, float, int]] = []
    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])

    for i, _ in enumerate(times):
        if i == 0:
            label = "Today"
        elif i == 1:
            label = "Tomorrow"
        else:
            # Open-Meteo gives YYYY-MM-DD; use it as a fallback display.
            label = times[i]
        days_out.append((label, float(highs[i]), float(lows[i]), int(codes[i])))

    return Weather(
        temperature_c=float(current["temperature_2m"]),
        feels_like_c=float(current["apparent_temperature"]),
        humidity=int(current["relative_humidity_2m"]),
        wind_kph=float(current["wind_speed_10m"]),
        weather_code=int(current["weather_code"]),
        is_day=bool(current["is_day"]),
        daily=days_out,
    )


__all__ = [
    "Place",
    "Weather",
    "close_session",
    "describe_code",
    "geocode",
    "get_weather",
]
