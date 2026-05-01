"""Financial analysis cog.

Commands:
    /chart <ticker> [timeframe] [type]   primary command, interactive view
    /candles <ticker> [timeframe]        OHLC candles (shortcut)
    /rsi <ticker> [timeframe]            price + MAs + RSI (shortcut)
    /moving_average <ticker> [timeframe] price + MAs (shortcut)

The cog is thin: validate args, hit `services.finance` for data,
`services.charts` for the PNG bytes, ship a `discord.File`. The
non-trivial bit is the interactive view on /chart — buttons let users
re-render at a different timeframe without retyping the command. We
edit the original message rather than posting a new one each click,
keeping the channel tidy.
"""

# Headless matplotlib backend MUST be selected before pyplot imports
# anywhere in the process. Setting it here as well as in services.charts
# is harmless — `matplotlib.use("Agg")` is idempotent.
import matplotlib

matplotlib.use("Agg")

import io

import discord
from discord import app_commands
from discord.ext import commands

from vixen.services import charts
from vixen.services.cooldown import try_acquire
from vixen.services.finance import (
    DEFAULT_TIMEFRAME,
    TIMEFRAMES,
    compute_moving_averages,
    compute_rsi,
    download_history,
    last_price,
    percent_change,
)

# Slash-choice list for the timeframe parameter. Same order as TIMEFRAMES
# so the dropdown matches the natural progression short-to-long.
_TIMEFRAME_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name=tf, value=tf) for tf in TIMEFRAMES
]


_CHART_TYPE_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name="Line + MAs", value="line"),
    app_commands.Choice(name="Candles", value="candles"),
    app_commands.Choice(name="Price + RSI", value="rsi"),
]


# --------------------------------------------------------------------------- #
# Renderer dispatch — single place that maps "what kind of chart?" to bytes
# --------------------------------------------------------------------------- #


async def _render_chart(
    ticker: str, timeframe: str, chart_type: str
) -> tuple[bytes, str] | None:
    """Download data and render. Returns (png_bytes, summary_line) or None on
    empty data so the caller can tell the user `ticker` doesn't exist.
    """
    df = await download_history(ticker, timeframe)
    if df.empty:
        return None

    # Indicators are cheap; compute everything so the renderers can pick.
    compute_moving_averages(df)
    if chart_type == "rsi":
        compute_rsi(df)

    if chart_type == "candles":
        png = charts.render_candles(df, ticker, timeframe)
    elif chart_type == "rsi":
        png = charts.render_price_with_rsi(df, ticker, timeframe)
    else:  # "line"
        png = charts.render_price_with_mas(df, ticker, timeframe)

    # One-line summary that goes in the message above the chart. Shows the
    # last close + relative change over the timeframe — enough context to
    # read at a glance without scrolling the chart.
    last = last_price(df)
    pct = percent_change(df)
    sign = "+" if pct >= 0 else ""
    summary = (
        f"**{ticker.upper()}** — last **{last:,.2f}**, "
        f"{sign}{pct:.2f}% over **{timeframe}**"
    )
    return png, summary


# --------------------------------------------------------------------------- #
# Interactive view — timeframe buttons that re-render in place
# --------------------------------------------------------------------------- #


class _ChartView(discord.ui.View):
    """A row of timeframe buttons under a /chart message.

    Clicking a button re-downloads, re-renders, and edits the message
    with the new chart. The original requester is the only one allowed
    to use the buttons — otherwise a stranger could spam someone else's
    message into a different timeframe.

    Times out after 5 minutes; after that, button clicks return a polite
    "this is stale" reply and the bot stops listening.
    """

    def __init__(
        self,
        *,
        ticker: str,
        chart_type: str,
        owner_id: int,
        initial_timeframe: str,
    ):
        super().__init__(timeout=300)
        self.ticker = ticker
        self.chart_type = chart_type
        self.owner_id = owner_id
        self.current_timeframe = initial_timeframe

        # One button per timeframe. The button currently in use is rendered
        # in primary blue; the others are secondary grey. Clicking re-runs
        # _render_and_edit which updates this state.
        for tf in TIMEFRAMES:
            self.add_item(_TimeframeButton(tf, active=(tf == initial_timeframe)))

    async def interaction_check(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "These buttons belong to whoever ran `/chart`. "
                "Run your own `/chart` to control your view.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        # Disable all buttons so they grey out client-side. We can't edit
        # the message here cleanly without storing it; discord.py renders
        # disabled state on the next interaction attempt.
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]


class _TimeframeButton(discord.ui.Button):
    """One pill-shaped timeframe button. The View owns the data + state."""

    def __init__(self, timeframe: str, *, active: bool):
        super().__init__(
            label=timeframe,
            style=(
                discord.ButtonStyle.primary
                if active
                else discord.ButtonStyle.secondary
            ),
            custom_id=f"chart_tf_{timeframe}",
        )
        self.timeframe = timeframe

    async def callback(self, interaction: discord.Interaction) -> None:
        view: _ChartView = self.view  # type: ignore[assignment]

        # Update the view's internal state and the visual highlight.
        view.current_timeframe = self.timeframe
        for child in view.children:
            if isinstance(child, _TimeframeButton):
                child.style = (
                    discord.ButtonStyle.primary
                    if child.timeframe == self.timeframe
                    else discord.ButtonStyle.secondary
                )

        # Defer first — re-rendering can take a few seconds (network +
        # mpl) which would blow past Discord's 3-second interaction
        # response window without this.
        await interaction.response.defer()

        result = await _render_chart(
            view.ticker, view.timeframe_or(self.timeframe), view.chart_type
        )
        if result is None:
            await interaction.followup.send(
                f"Couldn't reload data for `{view.ticker}`.", ephemeral=True
            )
            return

        png, summary = result
        await interaction.edit_original_response(
            content=summary,
            attachments=[
                discord.File(io.BytesIO(png), filename="chart.png")
            ],
            view=view,
        )


# Convenience: the view occasionally references its own current timeframe
# from a button's perspective. We attach this as a method instead of a
# property to keep the call site explicit.
def _timeframe_or(self: _ChartView, fallback: str) -> str:
    return self.current_timeframe or fallback


_ChartView.timeframe_or = _timeframe_or  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #


class FinCog(commands.Cog):
    """Charts and indicators. Data via yfinance, rendered in-process."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # Common cooldown + render path used by every command below.
    # ---------------------------------------------------------------- #

    async def _do_chart_reply(
        self,
        ctx: commands.Context,
        ticker: str,
        timeframe: str,
        chart_type: str,
        *,
        with_view: bool = False,
    ) -> None:
        # Anti-spam cooldown shared across all chart commands — switching
        # between /rsi, /candles, /chart shouldn't let a user bypass.
        remaining = await try_acquire(ctx.author.id, "fin_chart")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        # Slash command interactions can take longer than 3s to respond
        # to. Defer so Discord doesn't time us out while yfinance loads.
        if ctx.interaction is not None:
            await ctx.defer()

        result = await _render_chart(ticker, timeframe, chart_type)
        if result is None:
            await ctx.reply(
                f"No data for ticker `{ticker}` over `{timeframe}`. "
                f"Check the symbol and try again.",
                ephemeral=True,
            )
            return

        png, summary = result
        file = discord.File(io.BytesIO(png), filename="chart.png")

        if with_view:
            view = _ChartView(
                ticker=ticker,
                chart_type=chart_type,
                owner_id=ctx.author.id,
                initial_timeframe=timeframe,
            )
            await ctx.reply(content=summary, file=file, view=view)
        else:
            await ctx.reply(content=summary, file=file)

    # ---------------------------------------------------------------- #
    # /chart — primary command, with timeframe buttons
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        help="Chart a ticker. Buttons let you switch timeframe in place."
    )
    @app_commands.describe(
        ticker="Symbol like AAPL, MSFT, BTC-USD.",
        timeframe="Lookback window. Default 3mo.",
        chart_type="Line + MAs / Candles / Price + RSI.",
    )
    @app_commands.choices(timeframe=_TIMEFRAME_CHOICES, chart_type=_CHART_TYPE_CHOICES)
    async def chart(
        self,
        ctx: commands.Context,
        ticker: str,
        timeframe: str = DEFAULT_TIMEFRAME,
        chart_type: str = "line",
    ) -> None:
        await self._do_chart_reply(
            ctx, ticker, timeframe, chart_type, with_view=True
        )

    # ---------------------------------------------------------------- #
    # /candles
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="OHLC candlestick chart with volume.")
    @app_commands.describe(
        ticker="Symbol like AAPL.",
        timeframe="Lookback window. Default 3mo.",
    )
    @app_commands.choices(timeframe=_TIMEFRAME_CHOICES)
    async def candles(
        self,
        ctx: commands.Context,
        ticker: str,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> None:
        await self._do_chart_reply(ctx, ticker, timeframe, "candles")

    # ---------------------------------------------------------------- #
    # /rsi (backwards-compatible)
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Price + MAs + RSI in one chart.")
    @app_commands.describe(
        ticker="Symbol like AAPL.",
        timeframe="Lookback window. Default 3mo.",
    )
    @app_commands.choices(timeframe=_TIMEFRAME_CHOICES)
    async def rsi(
        self,
        ctx: commands.Context,
        ticker: str,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> None:
        await self._do_chart_reply(ctx, ticker, timeframe, "rsi")

    # ---------------------------------------------------------------- #
    # /moving_average (backwards-compatible)
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Price with 20- and 50-day moving averages.")
    @app_commands.describe(
        ticker="Symbol like AAPL.",
        timeframe="Lookback window. Default 3mo.",
    )
    @app_commands.choices(timeframe=_TIMEFRAME_CHOICES)
    async def moving_average(
        self,
        ctx: commands.Context,
        ticker: str,
        timeframe: str = DEFAULT_TIMEFRAME,
    ) -> None:
        await self._do_chart_reply(ctx, ticker, timeframe, "line")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FinCog(bot))
