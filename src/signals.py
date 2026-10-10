"""
Signal generation: decide WHEN we would like to buy or sell.

Signals only express a wish. They know nothing about account size, risk
limits, or volatility. Those decisions live in risk.py and volatility.py.

A signal for bar i is computed from data up to the CLOSE of bar i. The
backtester then acts at the OPEN of bar i+1, so a strategy can never trade
on a price it couldn't have seen yet.

All strategies here are long-only (buy BTC, later sell it), which is the
simplest setup to reason about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from . import indicators
from .data_loader import Bar

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    action: str  # BUY, SELL or HOLD
    reason: str = ""


HOLD_SIGNAL = Signal(HOLD)


class Strategy:
    """Base class. Subclasses fill in prepare() and signal_at()."""

    name = "base"

    def prepare(self, bars: Sequence[Bar]) -> None:
        """Precompute indicators for the whole series (each value uses only past data)."""
        raise NotImplementedError

    @property
    def warmup_bars(self) -> int:
        """Bars needed before the first signal is possible."""
        raise NotImplementedError

    def signal_at(self, i: int) -> Signal:
        raise NotImplementedError


class SmaCrossover(Strategy):
    """Buy when the fast moving average crosses above the slow one; sell on the cross below."""

    name = "sma_crossover"

    def __init__(self, fast_period: int, slow_period: int):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.fast: List[Optional[float]] = []
        self.slow: List[Optional[float]] = []

    @property
    def warmup_bars(self) -> int:
        return self.slow_period + 1

    def prepare(self, bars: Sequence[Bar]) -> None:
        closes = [b.close for b in bars]
        self.fast = indicators.sma(closes, self.fast_period)
        self.slow = indicators.sma(closes, self.slow_period)

    def signal_at(self, i: int) -> Signal:
        if i < 1 or None in (self.fast[i], self.slow[i], self.fast[i - 1], self.slow[i - 1]):
            return HOLD_SIGNAL
        was_above = self.fast[i - 1] > self.slow[i - 1]
        is_above = self.fast[i] > self.slow[i]
        if is_above and not was_above:
            return Signal(BUY, f"SMA{self.fast_period} crossed above SMA{self.slow_period}")
        if was_above and not is_above:
            return Signal(SELL, f"SMA{self.fast_period} crossed below SMA{self.slow_period}")
        return HOLD_SIGNAL


class RsiMeanReversion(Strategy):
    """Buy when RSI dips below `buy_below` (oversold); sell once it recovers above `sell_above`."""

    name = "rsi_mean_reversion"

    def __init__(self, period: int, buy_below: float, sell_above: float):
        self.period = period
        self.buy_below = buy_below
        self.sell_above = sell_above
        self.values: List[Optional[float]] = []

    @property
    def warmup_bars(self) -> int:
        return self.period + 2

    def prepare(self, bars: Sequence[Bar]) -> None:
        self.values = indicators.rsi([b.close for b in bars], self.period)

    def signal_at(self, i: int) -> Signal:
        if i < 1 or self.values[i] is None or self.values[i - 1] is None:
            return HOLD_SIGNAL
        now, before = self.values[i], self.values[i - 1]
        if now < self.buy_below <= before:
            return Signal(BUY, f"RSI{self.period} fell below {self.buy_below:g} ({now:.1f})")
        if now > self.sell_above:
            return Signal(SELL, f"RSI{self.period} above {self.sell_above:g} ({now:.1f})")
        return HOLD_SIGNAL


class DonchianBreakout(Strategy):
    """Buy on a close above the recent highest high; sell on a close below the recent lowest low."""

    name = "donchian_breakout"

    def __init__(self, entry_lookback: int, exit_lookback: int):
        self.entry_lookback = entry_lookback
        self.exit_lookback = exit_lookback
        self.closes: List[float] = []
        self.upper: List[Optional[float]] = []
        self.lower: List[Optional[float]] = []

    @property
    def warmup_bars(self) -> int:
        return max(self.entry_lookback, self.exit_lookback) + 1

    def prepare(self, bars: Sequence[Bar]) -> None:
        self.closes = [b.close for b in bars]
        self.upper = indicators.highest([b.high for b in bars], self.entry_lookback)
        self.lower = indicators.lowest([b.low for b in bars], self.exit_lookback)

    def signal_at(self, i: int) -> Signal:
        if self.upper[i] is None or self.lower[i] is None:
            return HOLD_SIGNAL
        if self.closes[i] > self.upper[i]:
            return Signal(BUY, f"close broke above {self.entry_lookback}-bar high {self.upper[i]:.2f}")
        if self.closes[i] < self.lower[i]:
            return Signal(SELL, f"close broke below {self.exit_lookback}-bar low {self.lower[i]:.2f}")
        return HOLD_SIGNAL


def build_strategy(strategy_config: Dict) -> Strategy:
    name = strategy_config["name"]
    params = strategy_config[name]
    if name == "sma_crossover":
        return SmaCrossover(params["fast_period"], params["slow_period"])
    if name == "rsi_mean_reversion":
        return RsiMeanReversion(params["period"], params["buy_below"], params["sell_above"])
    if name == "donchian_breakout":
        return DonchianBreakout(params["entry_lookback"], params["exit_lookback"])
    raise ValueError(f"Unknown strategy: {name}")
