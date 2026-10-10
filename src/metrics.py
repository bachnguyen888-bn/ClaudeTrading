"""
Performance statistics for a simulated run.

All of these describe the PAST on ONE dataset. Good backtest numbers do
not mean a strategy will make money in the future.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

EquityPoint = Tuple[datetime, float]


def max_drawdown_pct(values: Sequence[float]) -> float:
    """Largest peak-to-trough drop, in percent."""
    peak = -math.inf
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def period_returns(values: Sequence[float]) -> List[float]:
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] > 0]


def sharpe_ratio(returns: Sequence[float], periods_per_year: float) -> Optional[float]:
    """Annualized mean/stdev of returns (risk-free rate assumed 0)."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        return None
    return mean / math.sqrt(variance) * math.sqrt(periods_per_year)


def cagr_pct(start_value: float, end_value: float, years: float) -> Optional[float]:
    if years <= 0 or start_value <= 0 or end_value <= 0:
        return None
    return ((end_value / start_value) ** (1.0 / years) - 1.0) * 100.0


def trade_stats(pnls: Sequence[float]) -> Dict[str, Optional[float]]:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / len(pnls) * 100.0) if pnls else None,
        "avg_win": (gross_win / len(wins)) if wins else None,
        "avg_loss": (-gross_loss / len(losses)) if losses else None,
        "largest_win": max(wins) if wins else None,
        "largest_loss": min(losses) if losses else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "expectancy": (sum(pnls) / len(pnls)) if pnls else None,
        "net_pnl": sum(pnls),
    }


def summarize_equity(curve: Sequence[EquityPoint], periods_per_year: float) -> Dict[str, Optional[float]]:
    values = [v for _, v in curve]
    start_value, end_value = values[0], values[-1]
    years = (curve[-1][0] - curve[0][0]).total_seconds() / (365.0 * 86400.0)
    rets = period_returns(values)
    vol = None
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(periods_per_year) * 100.0
    return {
        "start_date": curve[0][0].date().isoformat(),
        "end_date": curve[-1][0].date().isoformat(),
        "years": round(years, 2),
        "start_equity": start_value,
        "end_equity": end_value,
        "total_return_pct": (end_value / start_value - 1.0) * 100.0,
        "cagr_pct": cagr_pct(start_value, end_value, years),
        "max_drawdown_pct": max_drawdown_pct(values),
        "annual_volatility_pct": vol,
        "sharpe": sharpe_ratio(rets, periods_per_year),
    }


def buy_and_hold(closes: Sequence[float], starting_cash: float) -> Dict[str, float]:
    """What simply buying at the first close and holding would have done (no fees)."""
    curve = [starting_cash * c / closes[0] for c in closes]
    return {
        "buy_hold_return_pct": (curve[-1] / curve[0] - 1.0) * 100.0,
        "buy_hold_max_drawdown_pct": max_drawdown_pct(curve),
    }


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> Optional[float]:
    """Mean squared error of probability forecasts. 0 is perfect; 0.25 is a coin flip at 50%."""
    if not probabilities:
        return None
    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities)
