"""
Basic technical indicators, written out by hand so you can read the math.

Every function returns a list the same length as its input. The value at
index i only uses data up to and including index i, so there is no peeking
into the future (no "lookahead bias"). Values that can't be computed yet
(not enough history) are None.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from .data_loader import Bar

Series = List[Optional[float]]


def sma(values: Sequence[float], period: int) -> Series:
    """Simple moving average: the mean of the last `period` values."""
    out: Series = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def rsi(closes: Sequence[float], period: int) -> Series:
    """Relative Strength Index (Wilder's smoothing), 0-100."""
    out: Series = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def true_range(bars: Sequence[Bar]) -> List[float]:
    out = []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append(bar.high - bar.low)
        else:
            prev_close = bars[i - 1].close
            out.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
    return out


def atr(bars: Sequence[Bar], period: int) -> Series:
    """Average True Range (Wilder's smoothing): typical bar-to-bar price movement in dollars."""
    ranges = true_range(bars)
    out: Series = [None] * len(bars)
    if len(bars) < period:
        return out
    value = sum(ranges[:period]) / period
    out[period - 1] = value
    for i in range(period, len(bars)):
        value = (value * (period - 1) + ranges[i]) / period
        out[i] = value
    return out


def highest(values: Sequence[float], lookback: int, include_current: bool = False) -> Series:
    """Highest value over the last `lookback` bars (by default excluding the current bar)."""
    out: Series = [None] * len(values)
    offset = 0 if include_current else 1
    for i in range(len(values)):
        lo = i - lookback + 1 - offset
        if lo < 0:
            continue
        out[i] = max(values[lo:i + 1 - offset])
    return out


def lowest(values: Sequence[float], lookback: int, include_current: bool = False) -> Series:
    """Lowest value over the last `lookback` bars (by default excluding the current bar)."""
    out: Series = [None] * len(values)
    offset = 0 if include_current else 1
    for i in range(len(values)):
        lo = i - lookback + 1 - offset
        if lo < 0:
            continue
        out[i] = min(values[lo:i + 1 - offset])
    return out


def log_returns(closes: Sequence[float]) -> List[Optional[float]]:
    return [None] + [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def realized_volatility(closes: Sequence[float], lookback: int, periods_per_year: float) -> Series:
    """Annualized standard deviation of log returns over the last `lookback` bars, as a fraction (0.6 = 60%)."""
    rets = log_returns(closes)
    out: Series = [None] * len(closes)
    for i in range(lookback, len(closes)):
        window = rets[i - lookback + 1:i + 1]
        mean = sum(window) / lookback
        variance = sum((r - mean) ** 2 for r in window) / (lookback - 1)
        out[i] = math.sqrt(variance) * math.sqrt(periods_per_year)
    return out
