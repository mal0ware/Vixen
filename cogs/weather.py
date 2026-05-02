"""Weather cog. Open-Meteo backend (no API key).

Two commands:
    /weather <city>          current conditions + 3-day forecast
    /forecast <city> [days]  longer forecast (1-7 days)

Both compose the same render: an embed with current temperature, conditions,
humidity, wind, and a per-day high/low forecast row.
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.services.cooldown import try_acquire
from vixen.services.weather import (
    Place,
    Weather,
    describe_code,
    geocode,
    get_weather,
)


def _f_from_c(c: float) -> float:
    """Celsius to Fahrenheit. Kept inline so we don't drag a units lib."""
    return c * 9 / 5 + 32


def _format_temp(c: float) -> str:
    """Render '23.5°C / 74.3°F' for embed fields."""
    return f"{c:.1f}°C / {_f_from_c(c):.1f}°F"


def _build_weather_embed(place: Place, weather: Weather) -> discord.Embed:
    """Compose the embed shown for /weather and /forecast.

    Top: location + current conditions header.
    Middle: temperature, feels-like, humidity, wind.
    Bottom: per-day forecast rows.
    """
    desc, emoji = describe_code(weather.weather_code)

    # Build the location header. "Boston, Massachusetts (United States)"
    # collapses gracefully when region or country is None.
    loc_parts = [place.name]
    if place.region:
        loc_parts.append(place.region)
    location = ", ".join(loc_parts)
    if place.country:
        location += f" ({place.country})"

    # Discord embed colors: warm sun, cool night.
    color = discord.Color.gold() if weather.is_day else discord.Color.dark_blue()

    embed = discord.Embed(
        title=f"{emoji} {location}",
        description=f"**{desc}**",
        color=color,
    )

    # Current conditions row.
    embed.add_field(name="Temperature", value=_format_temp(weather.temperature_c), inline=True)
    embed.add_field(name="Feels like", value=_format_temp(weather.feels_like_c), inline=True)
    embed.add_field(name="Humidity", value=f"{weather.humidity}%", inline=True)
    embed.add_field(name="Wind", value=f"{weather.wind_kph:.1f} km/h", inline=True)
    # Two empty inline fields balance the row to 3-per-line layout. Discord
    # quirk — without these the wind field hangs awkwardly alone.
    embed.add_field(name="​", value="​", inline=True)
    embed.add_field(name="​", value="​", inline=True)

    # Forecast rows. Each day gets one inline field (3 per row in Discord).
    for label, high, low, code in weather.daily:
        day_desc, day_emoji = describe_code(code)
        embed.add_field(
            name=f"{day_emoji} {label}",
            value=(
                f"{day_desc}\n"
                f"H: {high:.1f}°C / {_f_from_c(high):.1f}°F\n"
                f"L: {low:.1f}°C / {_f_from_c(low):.1f}°F"
            ),
            inline=True,
        )

    embed.set_footer(text="Powered by Open-Meteo")
    return embed


class WeatherCog(commands.Cog):
    """Current weather + multi-day forecasts."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /weather
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Show current weather + 3-day forecast for a city.")
    @app_commands.describe(city="City name (e.g. Boston, Tokyo, Reykjavik).")
    async def weather(self, ctx: commands.Context, *, city: str) -> None:
        # Same cooldown as fin charts — both involve outbound HTTP and the
        # anti-spam goal is identical.
        remaining = await try_acquire(ctx.author.id, "weather")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        # The whole pipeline (geocode + forecast) can take ~1s on cold
        # cache. Defer the slash interaction so Discord doesn't drop us.
        if ctx.interaction is not None:
            await ctx.defer()

        place = await geocode(city)
        if place is None:
            await ctx.reply(
                f"Couldn't find a location for `{city}`. Try a more specific name "
                f"like `Boston, MA`.",
                ephemeral=True,
            )
            return

        weather = await get_weather(place.latitude, place.longitude, days=3)
        await ctx.reply(embed=_build_weather_embed(place, weather))

    # ---------------------------------------------------------------- #
    # /forecast
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Show a multi-day forecast for a city (1-7 days).")
    @app_commands.describe(
        city="City name.",
        days="How many days (1-7). Default 5.",
    )
    async def forecast(
        self,
        ctx: commands.Context,
        city: str,
        days: int = 5,
    ) -> None:
        if not 1 <= days <= 7:
            await ctx.reply("Days must be between 1 and 7.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "weather")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        if ctx.interaction is not None:
            await ctx.defer()

        place = await geocode(city)
        if place is None:
            await ctx.reply(
                f"Couldn't find a location for `{city}`.",
                ephemeral=True,
            )
            return

        weather = await get_weather(place.latitude, place.longitude, days=days)
        await ctx.reply(embed=_build_weather_embed(place, weather))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeatherCog(bot))
