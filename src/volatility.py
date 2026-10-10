"""
Volatility filters: decide whether market conditions are calm enough to trade.

Two measurements:
  * realized volatility: how much the price has been swinging lately,
    annualized (60% means "a typical year of moves this size").
  * ATR (average true range): typical bar size in dollars. risk.py uses it
    to place stop-losses a sensible distance from the entry price.

The filter blocks NEW entries when volatility is outside your configured
band. Extremely high volatility means huge stop distances and gap risk;
extremely low volatility often means a dead market where fees eat profits.
It never blocks exits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from . import indicators
from .data_loader import Bar


@dataclass(frozen=True)
class VolatilityCheck:
    allowed: bool
    reason: str
    annual_vol_pct: Optional[float]
    atr: Optional[float]


class VolatilityFilter:
    def __init__(self, filter_config: Dict, periods_per_year: float):
        self.enabled = filter_config["enabled"]
        self.lookback = filter_config["lookback_bars"]
        self.min_vol_pct = filter_config["min_annual_vol_pct"]
        self.max_vol_pct = filter_config["max_annual_vol_pct"]
        self.atr_period = filter_config["atr_period"]
        self.periods_per_year = periods_per_year
        self.vol: List[Optional[float]] = []
        self.atr: List[Optional[float]] = []

    @property
    def warmup_bars(self) -> int:
        return max(self.lookback, self.atr_period) + 1

    def prepare(self, bars: Sequence[Bar]) -> None:
        closes = [b.close for b in bars]
        self.vol = indicators.realized_volatility(closes, self.lookback, self.periods_per_year)
        self.atr = indicators.atr(bars, self.atr_period)

    def annual_vol_pct(self, i: int) -> Optional[float]:
        return None if self.vol[i] is None else self.vol[i] * 100.0

    def check(self, i: int) -> VolatilityCheck:
        vol_pct = self.annual_vol_pct(i)
        atr_value = self.atr[i]
        if vol_pct is None or atr_value is None:
            return VolatilityCheck(False, "volatility_not_ready", vol_pct, atr_value)
        if not self.enabled:
            return VolatilityCheck(True, "filter_disabled", vol_pct, atr_value)
        if vol_pct > self.max_vol_pct:
            return VolatilityCheck(False, "volatility_too_high", vol_pct, atr_value)
        if vol_pct < self.min_vol_pct:
            return VolatilityCheck(False, "volatility_too_low", vol_pct, atr_value)
        return VolatilityCheck(True, "ok", vol_pct, atr_value)


def vol_band_check(annual_vol_pct: Optional[float], min_pct: float, max_pct: float) -> str:
    """Shared helper for the prediction-market experiment. Returns '' if OK, else a skip reason."""
    if annual_vol_pct is None:
        return "volatility_not_ready"
    if annual_vol_pct > max_pct:
        return "volatility_too_high"
    if annual_vol_pct < min_pct:
        return "volatility_too_low"
    return ""
