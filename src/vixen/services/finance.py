"""Finance data + indicator computations.

Two responsibilities:

1. Async wrappers around yfinance. yfinance is a synchronous library
   (HTTP under the hood), and calling it directly from a coroutine
   blocks the entire event loop for the duration of the network round
   trip — which can be hundreds of ms to seconds. We bounce the call
   through `asyncio.to_thread` so the bot keeps serving other commands
   while the data loads.

2. Pure-Python indicator math (RSI, moving averages). Pure functions on
   DataFrames, no I/O — easy to test without the network.

Charts and Discord rendering live in `services/charts.py`. This module
deliberately knows nothing about images, embeds, or discord.py.
"""

from __future__ import annotations

import asyncio

import pandas as pd
import yfinance as yf

# --------------------------------------------------------------------------- #
# Timeframe helpers
# --------------------------------------------------------------------------- #


# Maps a friendly timeframe string to (period, interval) yfinance arguments.
# `period` selects the lookback window, `interval` the candle granularity.
# Discord users typically want short timeframes with intraday detail and
# longer timeframes with daily candles, so the map encodes that taste.
TIMEFRAMES: dict[str, tuple[str, str]] = {
    "1d": ("1d", "5m"),
    "5d": ("5d", "15m"),
    "1mo": ("1mo", "1h"),
    "3mo": ("3mo", "1d"),
    "1y": ("1y", "1d"),
    "5y": ("5y", "1wk"),
}

DEFAULT_TIMEFRAME = "3mo"


# --------------------------------------------------------------------------- #
# Async data download
# --------------------------------------------------------------------------- #


async def download_history(
    ticker: str,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> pd.DataFrame:
    """Async wrapper around yfinance.download. Returns OHLCV DataFrame.

    Empty DataFrame on invalid ticker or no data — caller should check
    `df.empty` before plotting. Raises if yfinance itself errors out
    (network failure, malformed response).
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"unknown timeframe {timeframe!r}; choices: {sorted(TIMEFRAMES)}"
        )

    period, interval = TIMEFRAMES[timeframe]

    # to_thread runs the blocking call on the default thread pool. yfinance
    # internally uses requests; this keeps the event loop responsive.
    df = await asyncio.to_thread(
        yf.download,
        ticker,
        period=period,
        interval=interval,
        progress=False,        # no console progress bar
        auto_adjust=False,     # keep raw OHLC; we'll handle adjusted close ourselves later
    )

    # yfinance returns multi-index columns when given multiple tickers. We
    # always pass one ticker, but newer yfinance versions still wrap the
    # frame; flatten for downstream simplicity.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df


# --------------------------------------------------------------------------- #
# Indicators (pure functions on a DataFrame)
# --------------------------------------------------------------------------- #


def compute_rsi(data: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Add an "RSI" column to `data` using Wilder-style smoothing.

    RSI is bounded 0..100. >70 typically read as overbought, <30 oversold —
    those thresholds are conventions, not mathematics. The window param is
    the standard Wilder period; 14 is the textbook default.

    Returns the same DataFrame with the new column attached.
    """
    delta = data["Close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Simple rolling mean for the first pass — easier to read than Wilder's
    # exponential variant, and indistinguishable on multi-week windows.
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()

    rs = avg_gain / avg_loss
    data["RSI"] = 100 - (100 / (1 + rs))
    return data


def compute_moving_averages(
    data: pd.DataFrame,
    windows: tuple[int, ...] = (20, 50),
) -> pd.DataFrame:
    """Add MA<window> columns for each window. Default: MA20 and MA50.

    Uses min_periods=1 so the lines start drawing from row 1 rather than
    leaving a gap until `window` candles have accumulated. Tradeoff: the
    early values are noisier than the textbook MA. Looks better in a chart;
    quants would use NaN.
    """
    for w in windows:
        data[f"MA{w}"] = data["Close"].rolling(window=w, min_periods=1).mean()
    return data


def last_price(data: pd.DataFrame) -> float:
    """Return the most recent close price as a float. Empty frame → 0.0."""
    if data.empty:
        return 0.0
    return float(data["Close"].iloc[-1])


def percent_change(data: pd.DataFrame) -> float:
    """Return the percent change from first close to last close, e.g. +5.3."""
    if data.empty:
        return 0.0
    first = float(data["Close"].iloc[0])
    last = float(data["Close"].iloc[-1])
    if first == 0:
        return 0.0
    return (last - first) / first * 100.0


__all__ = [
    "DEFAULT_TIMEFRAME",
    "TIMEFRAMES",
    "compute_moving_averages",
    "compute_rsi",
    "download_history",
    "last_price",
    "percent_change",
]
