"""Tests for vixen.services.finance.

Indicator math is pure DataFrame in / DataFrame out — no fixtures, no
network. We don't test `download_history` here; that would require
hitting yfinance over the network and would be brittle.
"""

from __future__ import annotations

import pandas as pd

from vixen.services.finance import (
    compute_bollinger,
    compute_macd,
    compute_moving_averages,
    compute_rsi,
    last_price,
    normalize_to_base,
    percent_change,
)


def _make_frame(prices: list[float]) -> pd.DataFrame:
    """Build a minimal price DataFrame with a Close column."""
    return pd.DataFrame({"Close": prices})


# ---------------------------------------------------------------- #
# compute_rsi
# ---------------------------------------------------------------- #


def test_rsi_column_added():
    """compute_rsi attaches an 'RSI' column."""
    df = _make_frame([1.0, 2.0, 3.0, 4.0, 5.0])
    result = compute_rsi(df, window=2)
    assert "RSI" in result.columns


def test_rsi_warmup_period_is_nan():
    """RSI is undefined until `window` rows of price changes have happened.

    With window=14, the first 14 rows produce NaN. Sanity check on a small
    case: window=3 → first 3 rows NaN.
    """
    df = _make_frame([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    result = compute_rsi(df, window=3)
    # First N values are NaN where the rolling window hasn't filled.
    assert result["RSI"].iloc[:3].isna().all()
    assert not result["RSI"].iloc[3:].isna().any()


def test_rsi_strict_uptrend_is_100():
    """An uptrend with no losses gives RSI = 100 (avg_loss == 0)."""
    df = _make_frame([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    result = compute_rsi(df, window=3)
    # The last value is the most settled — strict uptrend means 100.
    assert result["RSI"].iloc[-1] == 100.0


def test_rsi_strict_downtrend_is_0():
    """A downtrend with no gains gives RSI = 0."""
    df = _make_frame([15.0, 14.0, 13.0, 12.0, 11.0, 10.0])
    result = compute_rsi(df, window=3)
    assert result["RSI"].iloc[-1] == 0.0


# ---------------------------------------------------------------- #
# compute_moving_averages
# ---------------------------------------------------------------- #


def test_moving_averages_default_columns():
    """Default windows are 20 and 50 → MA20 and MA50 columns added."""
    df = _make_frame(list(range(1, 101)))  # 100 rows
    result = compute_moving_averages(df)
    assert "MA20" in result.columns
    assert "MA50" in result.columns


def test_moving_averages_custom_windows():
    """Custom windows produce custom column names."""
    df = _make_frame(list(range(1, 11)))
    result = compute_moving_averages(df, windows=(3, 5))
    assert "MA3" in result.columns
    assert "MA5" in result.columns
    assert "MA20" not in result.columns


def test_moving_averages_uses_min_periods_1():
    """First values are present (not NaN) even before the window fills."""
    df = _make_frame([10.0, 20.0, 30.0])
    result = compute_moving_averages(df, windows=(5,))
    # First row's MA5 should equal first row's Close (only one data point).
    assert result["MA5"].iloc[0] == 10.0


# ---------------------------------------------------------------- #
# last_price / percent_change
# ---------------------------------------------------------------- #


def test_last_price_returns_final_close():
    df = _make_frame([1.0, 2.0, 3.0])
    assert last_price(df) == 3.0


def test_last_price_empty_returns_zero():
    """No rows → 0.0 (caller guard)."""
    assert last_price(pd.DataFrame({"Close": []})) == 0.0


def test_percent_change_positive():
    df = _make_frame([100.0, 110.0])
    assert percent_change(df) == 10.0


def test_percent_change_negative():
    df = _make_frame([100.0, 90.0])
    assert percent_change(df) == -10.0


def test_percent_change_empty_returns_zero():
    assert percent_change(pd.DataFrame({"Close": []})) == 0.0


# ---------------------------------------------------------------- #
# compute_macd
# ---------------------------------------------------------------- #


def test_macd_columns_added():
    df = _make_frame([float(i) for i in range(1, 51)])
    result = compute_macd(df)
    assert {"MACD", "MACD_SIGNAL", "MACD_HIST"}.issubset(result.columns)


def test_macd_histogram_is_macd_minus_signal():
    """By definition: hist = macd - signal. Any other relationship is a bug."""
    df = _make_frame([float(i % 10) for i in range(60)])  # noisy input
    result = compute_macd(df)
    diff = result["MACD"] - result["MACD_SIGNAL"]
    # Compare with tolerance for float rounding.
    assert (result["MACD_HIST"] - diff).abs().max() < 1e-9


def test_macd_uptrend_macd_positive_at_end():
    """Steady uptrend → MACD ends above zero (fast EMA pulls ahead of slow)."""
    df = _make_frame([float(i) for i in range(1, 101)])
    result = compute_macd(df)
    assert result["MACD"].iloc[-1] > 0


def test_macd_downtrend_macd_negative_at_end():
    df = _make_frame([float(100 - i) for i in range(100)])
    result = compute_macd(df)
    assert result["MACD"].iloc[-1] < 0


# ---------------------------------------------------------------- #
# compute_bollinger
# ---------------------------------------------------------------- #


def test_bollinger_columns_added():
    df = _make_frame([float(i) for i in range(1, 41)])
    result = compute_bollinger(df, window=20)
    assert {"BB_MID", "BB_UPPER", "BB_LOWER"}.issubset(result.columns)


def test_bollinger_mid_is_sma():
    """BB_MID equals the simple moving average of `Close`."""
    df = _make_frame([float(i) for i in range(1, 31)])
    result = compute_bollinger(df, window=20)
    expected_mid = df["Close"].rolling(window=20, min_periods=20).mean()
    # Last row should match exactly (within float tolerance).
    assert abs(result["BB_MID"].iloc[-1] - expected_mid.iloc[-1]) < 1e-9


def test_bollinger_upper_above_lower():
    """Upper band is above lower wherever both are defined."""
    df = _make_frame([float(i) for i in range(1, 41)])
    result = compute_bollinger(df, window=20)
    valid = result.dropna(subset=["BB_UPPER", "BB_LOWER"])
    assert (valid["BB_UPPER"] >= valid["BB_LOWER"]).all()


def test_bollinger_width_widens_with_std():
    """Higher num_std → wider band. Sanity check on the parameter."""
    df = _make_frame([1.0, 5.0, 1.0, 5.0, 1.0, 5.0] * 5)  # noisy input

    narrow = compute_bollinger(df.copy(), window=5, num_std=1.0)
    wide = compute_bollinger(df.copy(), window=5, num_std=3.0)

    n_width = (narrow["BB_UPPER"] - narrow["BB_LOWER"]).iloc[-1]
    w_width = (wide["BB_UPPER"] - wide["BB_LOWER"]).iloc[-1]
    assert w_width > n_width


# ---------------------------------------------------------------- #
# normalize_to_base
# ---------------------------------------------------------------- #


def test_normalize_first_value_is_base():
    df = _make_frame([200.0, 210.0, 220.0])
    result = normalize_to_base(df, base=100.0)
    assert result.iloc[0] == 100.0


def test_normalize_last_reflects_percent_change():
    """Final normalized value mirrors percent change relative to first."""
    df = _make_frame([100.0, 150.0])  # +50%
    result = normalize_to_base(df, base=100.0)
    assert result.iloc[-1] == 150.0


def test_normalize_empty_returns_empty():
    result = normalize_to_base(pd.DataFrame({"Close": []}))
    assert result.empty
