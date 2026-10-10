"""
Risk sizing and account-level risk limits.

Signals say WHEN. This module says HOW MUCH, and whether we're allowed to
trade at all right now. All limits come from config.json.

Position sizing (fixed-fractional, ATR stop):
    stop distance  = ATR x stop_loss_atr_multiple
    dollars at risk = equity x risk_per_trade_pct / 100
    quantity        = dollars at risk / stop distance
So if the stop is hit you lose roughly risk_per_trade_pct of the account
(plus fees and slippage), no matter how volatile BTC is. The position is
then capped by max_position_pct and by the cash you have (no leverage).

Account limits:
    max_daily_loss_pct  - no new trades for the rest of the day
    max_trades_per_day  - no new trades for the rest of the day
    max_drawdown_pct    - kill switch: close everything, stop for good

With trailing_stop on, the stop follows the price up (never down), so a big
winner can't hand all of its gains back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class SizingDecision:
    approved: bool
    quantity: float
    notional: float
    stop_price: Optional[float]
    take_profit_price: Optional[float]
    reason: str


class RiskManager:
    def __init__(self, risk_config: Dict, starting_equity: float):
        self.risk_per_trade_pct = risk_config["risk_per_trade_pct"]
        self.stop_atr_multiple = risk_config["stop_loss_atr_multiple"]
        self.trailing_stop = risk_config["trailing_stop"]
        self.take_profit_atr_multiple = risk_config["take_profit_atr_multiple"]
        self.max_position_pct = risk_config["max_position_pct"]
        self.max_daily_loss_pct = risk_config["max_daily_loss_pct"]
        self.max_drawdown_pct = risk_config["max_drawdown_pct"]
        self.max_trades_per_day = risk_config["max_trades_per_day"]
        self.min_trade_usd = risk_config["min_trade_usd"]

        self.peak_equity = starting_equity
        self.current_day: Optional[date] = None
        self.day_start_equity = starting_equity
        self.trades_today = 0
        self.halted = False

    # --- account state -------------------------------------------------

    def start_bar(self, day: date, equity: float) -> None:
        """Call at the start of every bar. Resets daily counters on a new calendar day."""
        if day != self.current_day:
            self.current_day = day
            self.day_start_equity = equity
            self.trades_today = 0

    def update_equity(self, equity: float) -> bool:
        """Track the equity peak. Returns True the moment the drawdown kill switch trips."""
        self.peak_equity = max(self.peak_equity, equity)
        if not self.halted and self.drawdown_pct(equity) >= self.max_drawdown_pct:
            self.halted = True
            return True
        return False

    def drawdown_pct(self, equity: float) -> float:
        return (self.peak_equity - equity) / self.peak_equity * 100.0 if self.peak_equity > 0 else 0.0

    def daily_loss_pct(self, equity: float) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return max(0.0, (self.day_start_equity - equity) / self.day_start_equity * 100.0)

    def can_open_trade(self, equity: float) -> Tuple[bool, str]:
        """Account-level gate checked before every new entry."""
        if self.halted:
            return False, "max_drawdown_halt"
        if self.daily_loss_pct(equity) >= self.max_daily_loss_pct:
            return False, "daily_loss_limit"
        if self.trades_today >= self.max_trades_per_day:
            return False, "max_trades_per_day"
        return True, "ok"

    def record_entry(self) -> None:
        self.trades_today += 1

    # --- position sizing ------------------------------------------------

    def size_position(self, equity: float, cash: float, entry_price: float, atr: float,
                      fee_pct: float) -> SizingDecision:
        if atr is None or atr <= 0 or entry_price <= 0:
            return SizingDecision(False, 0.0, 0.0, None, None, "no_valid_atr")

        stop_distance = atr * self.stop_atr_multiple
        dollars_at_risk = equity * self.risk_per_trade_pct / 100.0
        quantity = dollars_at_risk / stop_distance

        max_notional = equity * self.max_position_pct / 100.0
        cash_notional = cash / (1.0 + fee_pct / 100.0)  # leave room for the fee
        notional_cap = min(max_notional, cash_notional)
        if quantity * entry_price > notional_cap:
            quantity = notional_cap / entry_price

        notional = quantity * entry_price
        if notional < self.min_trade_usd or quantity <= 0:
            return SizingDecision(False, 0.0, 0.0, None, None, "size_too_small")

        stop_price = entry_price - stop_distance
        take_profit = (entry_price + atr * self.take_profit_atr_multiple
                       if self.take_profit_atr_multiple > 0 else None)
        return SizingDecision(True, quantity, notional, stop_price, take_profit, "ok")


    def trail_stop(self, current_stop: float, close: float, atr: Optional[float]) -> float:
        """Trailing stop: follow the price up by the same ATR distance, never move it down."""
        if not self.trailing_stop or atr is None:
            return current_stop
        return max(current_stop, close - atr * self.stop_atr_multiple)


def kelly_fraction_binary(win_probability: float, cost_per_contract: float) -> float:
    """
    Kelly bet size for a contract that costs `cost_per_contract` and pays $1 if it wins.

        f* = (p - c) / (1 - c)

    Returns the fraction of bankroll to stake (0 if there is no edge).
    """
    if cost_per_contract <= 0 or cost_per_contract >= 1:
        return 0.0
    return max(0.0, (win_probability - cost_per_contract) / (1.0 - cost_per_contract))


def binary_bet_stake(bankroll: float, win_probability: float, cost_per_contract: float,
                     kelly_fraction: float, max_stake_pct: float, exposure_room: float) -> float:
    """Dollars to stake: fractional Kelly, capped by max_stake_pct and remaining exposure room."""
    full_kelly = kelly_fraction_binary(win_probability, cost_per_contract)
    stake = bankroll * full_kelly * kelly_fraction
    return max(0.0, min(stake, bankroll * max_stake_pct / 100.0, exposure_room))
