"""Chart rendering helpers.

Every render function returns `bytes` (a PNG payload). Callers wrap that
in `discord.File(io.BytesIO(payload), filename="...")` to ship it. We
never write temp files — keeps disk clean and lets us scale the output
to attached uploads without per-user directory races.

Why not return `io.BytesIO` directly: returning `bytes` keeps the
interface simple and makes test assertions (length, magic bytes) easy.
The cog wraps in BytesIO when handing to discord.py.

Theme

We force a dark theme so charts look at home embedded in Discord. The
palette is hand-tuned to be readable against Discord's #313338 channel
background.
"""

from __future__ import annotations

# Headless renderer must be selected BEFORE pyplot imports anywhere in
# the bot. cogs/fin_cog.py also sets this; doing it here too is harmless
# and makes this module independently safe to import (e.g. from a test
# that doesn't load the cog).
import matplotlib

matplotlib.use("Agg")

import io

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #


# Discord-flavored dark palette. Tweak these to retheme everything at once.
_BG = "#2b2d31"          # matches Discord embed background
_FG = "#dcddde"          # primary text
_GRID = "#3f4248"        # subtle gridlines
_PRICE = "#5865f2"       # Discord blurple
_MA20 = "#fee75c"        # yellow
_MA50 = "#eb459e"        # pink
_RSI_LINE = "#5865f2"
_RSI_OVERBOUGHT = "#ed4245"  # red
_RSI_OVERSOLD = "#3ba55c"    # green
_VOL_UP = "#3ba55c"
_VOL_DOWN = "#ed4245"

# 150 DPI hits a sweet spot — sharp on Retina without ballooning file size.
_DPI = 150


# Reusable mplfinance style. Built once at import.
_MPF_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    facecolor=_BG,
    edgecolor=_BG,
    figcolor=_BG,
    gridcolor=_GRID,
    rc={
        "axes.labelcolor": _FG,
        "axes.titlecolor": _FG,
        "xtick.color": _FG,
        "ytick.color": _FG,
        "text.color": _FG,
    },
    marketcolors=mpf.make_marketcolors(
        up=_VOL_UP,
        down=_VOL_DOWN,
        edge="inherit",
        wick={"up": _VOL_UP, "down": _VOL_DOWN},
        volume={"up": _VOL_UP, "down": _VOL_DOWN},
    ),
)


def _apply_axes_theme(ax) -> None:
    """Apply the dark palette to a single matplotlib Axes."""
    ax.set_facecolor(_BG)
    ax.spines["bottom"].set_color(_GRID)
    ax.spines["top"].set_color(_GRID)
    ax.spines["left"].set_color(_GRID)
    ax.spines["right"].set_color(_GRID)
    ax.tick_params(colors=_FG, which="both")
    ax.yaxis.label.set_color(_FG)
    ax.xaxis.label.set_color(_FG)
    ax.title.set_color(_FG)
    ax.grid(True, color=_GRID, linestyle="--", linewidth=0.5, alpha=0.6)


def _figure_to_png_bytes(fig) -> bytes:
    """Render a matplotlib figure to PNG bytes and close it."""
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=_DPI,
        bbox_inches="tight",
        facecolor=_BG,
    )
    plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Public renderers
# --------------------------------------------------------------------------- #


def render_price_with_mas(
    data: pd.DataFrame,
    ticker: str,
    timeframe: str,
) -> bytes:
    """Line chart: Close + MA20 + MA50.

    `data` must already have MA20 and MA50 columns (call
    services.finance.compute_moving_averages first).
    """
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=_BG)

    ax.plot(data.index, data["Close"], label="Close", color=_PRICE, linewidth=2)
    if "MA20" in data.columns:
        ax.plot(data.index, data["MA20"], label="MA20", color=_MA20, linewidth=1)
    if "MA50" in data.columns:
        ax.plot(data.index, data["MA50"], label="MA50", color=_MA50, linewidth=1)

    ax.set_title(f"{ticker.upper()} — {timeframe}")
    ax.set_ylabel("Price")
    ax.legend(loc="upper left", facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    _apply_axes_theme(ax)

    fig.tight_layout()
    return _figure_to_png_bytes(fig)


def render_price_with_rsi(
    data: pd.DataFrame,
    ticker: str,
    timeframe: str,
) -> bytes:
    """Two-pane chart: price + MAs on top, RSI on bottom.

    `data` must have MA20, MA50, and RSI columns. Top pane is 3x the
    height of the bottom pane (the price action gets the visual weight,
    RSI is the supporting indicator).
    """
    fig, (ax_price, ax_rsi) = plt.subplots(
        2, 1,
        figsize=(10, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
        facecolor=_BG,
    )

    # Top pane
    ax_price.plot(data.index, data["Close"], label="Close", color=_PRICE, linewidth=2)
    if "MA20" in data.columns:
        ax_price.plot(data.index, data["MA20"], label="MA20", color=_MA20, linewidth=1)
    if "MA50" in data.columns:
        ax_price.plot(data.index, data["MA50"], label="MA50", color=_MA50, linewidth=1)
    ax_price.set_title(f"{ticker.upper()} — {timeframe}")
    ax_price.set_ylabel("Price")
    ax_price.legend(loc="upper left", facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    _apply_axes_theme(ax_price)

    # Bottom pane
    ax_rsi.plot(data.index, data["RSI"], color=_RSI_LINE, linewidth=1.2)
    ax_rsi.axhline(70, color=_RSI_OVERBOUGHT, linestyle="--", linewidth=0.8, alpha=0.7)
    ax_rsi.axhline(30, color=_RSI_OVERSOLD, linestyle="--", linewidth=0.8, alpha=0.7)
    ax_rsi.set_ylabel("RSI")
    ax_rsi.set_ylim(0, 100)
    _apply_axes_theme(ax_rsi)

    fig.tight_layout()
    return _figure_to_png_bytes(fig)


def render_price_with_macd(
    data: pd.DataFrame,
    ticker: str,
    timeframe: str,
) -> bytes:
    """Two-pane chart: price on top, MACD lines + histogram on bottom.

    `data` must have MACD, MACD_SIGNAL, MACD_HIST. The histogram is
    coloured green when MACD is above signal (bullish) and red when below.
    """
    fig, (ax_price, ax_macd) = plt.subplots(
        2, 1,
        figsize=(10, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.4]},
        facecolor=_BG,
    )

    # Top pane — just the price line.
    ax_price.plot(data.index, data["Close"], label="Close", color=_PRICE, linewidth=2)
    ax_price.set_title(f"{ticker.upper()} — {timeframe} (MACD)")
    ax_price.set_ylabel("Price")
    ax_price.legend(loc="upper left", facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    _apply_axes_theme(ax_price)

    # Bottom pane — MACD line, signal line, and histogram bars.
    ax_macd.plot(data.index, data["MACD"], label="MACD", color=_MA20, linewidth=1.2)
    ax_macd.plot(
        data.index, data["MACD_SIGNAL"], label="Signal", color=_MA50, linewidth=1.0
    )
    # Histogram colours: bullish bars green, bearish red. Bars are wide so
    # they're visible against the line plots.
    hist = data["MACD_HIST"]
    bar_colors = [_VOL_UP if v >= 0 else _VOL_DOWN for v in hist.fillna(0)]
    ax_macd.bar(data.index, hist, color=bar_colors, alpha=0.6, width=1.0)
    ax_macd.axhline(0, color=_GRID, linewidth=0.6)
    ax_macd.set_ylabel("MACD")
    ax_macd.legend(loc="upper left", facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    _apply_axes_theme(ax_macd)

    fig.tight_layout()
    return _figure_to_png_bytes(fig)


def render_price_with_bollinger(
    data: pd.DataFrame,
    ticker: str,
    timeframe: str,
) -> bytes:
    """Single-pane chart: Close + Bollinger Bands (upper, middle, lower).

    `data` must have BB_UPPER, BB_MID, BB_LOWER. The band area between
    upper and lower is shaded faintly to make squeezes (narrow) and
    expansions (wide) immediately visible.
    """
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=_BG)

    ax.plot(data.index, data["Close"], label="Close", color=_PRICE, linewidth=2)
    ax.plot(data.index, data["BB_UPPER"], label="Upper", color=_MA20, linewidth=1)
    ax.plot(data.index, data["BB_MID"], label="Mid (SMA20)", color=_FG, linewidth=0.8)
    ax.plot(data.index, data["BB_LOWER"], label="Lower", color=_MA20, linewidth=1)

    # Shade the band so the width is visible at a glance.
    ax.fill_between(
        data.index, data["BB_LOWER"], data["BB_UPPER"], color=_MA20, alpha=0.10
    )

    ax.set_title(f"{ticker.upper()} — {timeframe} (Bollinger)")
    ax.set_ylabel("Price")
    ax.legend(loc="upper left", facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    _apply_axes_theme(ax)

    fig.tight_layout()
    return _figure_to_png_bytes(fig)


def render_compare(
    series_by_ticker: dict[str, pd.Series],
    timeframe: str,
) -> bytes:
    """Plot multiple tickers normalized to a common base on one axis.

    `series_by_ticker` maps "AAPL" -> normalized close-price series (call
    `services.finance.normalize_to_base` for each ticker before passing).
    Each ticker gets a distinct colour from a small cycling palette;
    if you compare more than 6 tickers the colours repeat — fine for a
    personal bot, would warrant a real palette generator at scale.
    """
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=_BG)

    palette = (_PRICE, _MA20, _MA50, _RSI_OVERSOLD, _RSI_OVERBOUGHT, _FG)
    for i, (ticker, series) in enumerate(series_by_ticker.items()):
        ax.plot(
            series.index,
            series,
            label=ticker.upper(),
            color=palette[i % len(palette)],
            linewidth=1.6,
        )

    # Reference line at 100 makes "above starting price" / "below starting
    # price" instantly readable.
    ax.axhline(100, color=_GRID, linestyle="--", linewidth=0.6)

    ax.set_title(f"Comparison — {timeframe} (rebased to 100)")
    ax.set_ylabel("Indexed price")
    ax.legend(loc="upper left", facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    _apply_axes_theme(ax)

    fig.tight_layout()
    return _figure_to_png_bytes(fig)


def render_candles(
    data: pd.DataFrame,
    ticker: str,
    timeframe: str,
) -> bytes:
    """OHLC candlestick chart with volume sub-pane.

    Uses mplfinance which already knows how to draw candlesticks; we just
    feed it our themed style. The frame must have the standard OHLCV
    column names (yfinance gives us those by default).
    """
    # mplfinance writes directly to a buffer when `savefig=` is provided.
    buf = io.BytesIO()

    # `returnfig=False` lets mpf own the figure lifecycle; combined with
    # `savefig=` it renders + saves + closes in one call.
    mpf.plot(
        data,
        type="candle",
        style=_MPF_STYLE,
        title=f"\n{ticker.upper()} — {timeframe}",
        ylabel="Price",
        ylabel_lower="Volume",
        volume=True,
        figsize=(10, 6),
        savefig={
            "fname": buf,
            "format": "png",
            "dpi": _DPI,
            "bbox_inches": "tight",
            "facecolor": _BG,
        },
    )

    return buf.getvalue()


__all__ = [
    "render_candles",
    "render_compare",
    "render_price_with_bollinger",
    "render_price_with_macd",
    "render_price_with_mas",
    "render_price_with_rsi",
]
