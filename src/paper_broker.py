"""
Simulated broker. It fills orders against historical prices, in memory.

There is no network code here, no API keys, and no way to reach an exchange.
"Buying" just moves numbers between `cash` and `position_qty`.
Fees and slippage are charged on every fill so results aren't flattering.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import safety


@dataclass(frozen=True)
class Fill:
    side: str  # BUY or SELL
    timestamp: datetime
    price: float  # after slippage
    quantity: float
    notional: float
    fee: float


class PaperBroker:
    def __init__(self, starting_cash: float, fee_pct: float, slippage_pct: float):
        safety.assert_paper_mode()
        self.cash = float(starting_cash)
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.position_qty = 0.0
        self.entry_price = 0.0
        self.entry_cost = 0.0  # notional + fee paid to open
        self.total_fees = 0.0

    @property
    def in_position(self) -> bool:
        return self.position_qty > 0

    def buy_price(self, market_price: float) -> float:
        """You pay a little more than the quoted price when buying."""
        return market_price * (1.0 + self.slippage_pct / 100.0)

    def sell_price(self, market_price: float) -> float:
        """You receive a little less than the quoted price when selling."""
        return market_price * (1.0 - self.slippage_pct / 100.0)

    def equity(self, market_price: float) -> float:
        return self.cash + self.position_qty * market_price

    def buy(self, timestamp: datetime, market_price: float, quantity: float) -> Fill:
        if self.in_position:
            raise RuntimeError("Already in a position; this simulator holds one position at a time.")
        price = self.buy_price(market_price)
        notional = price * quantity
        fee = notional * self.fee_pct / 100.0
        if notional + fee > self.cash + 1e-9:
            raise RuntimeError(f"Not enough paper cash: need {notional + fee:.2f}, have {self.cash:.2f}")
        self.cash -= notional + fee
        self.position_qty = quantity
        self.entry_price = price
        self.entry_cost = notional + fee
        self.total_fees += fee
        return Fill("BUY", timestamp, price, quantity, notional, fee)

    def sell_all(self, timestamp: datetime, market_price: float) -> Fill:
        if not self.in_position:
            raise RuntimeError("No position to sell.")
        price = self.sell_price(market_price)
        quantity = self.position_qty
        notional = price * quantity
        fee = notional * self.fee_pct / 100.0
        self.cash += notional - fee
        self.total_fees += fee
        self.position_qty = 0.0
        return Fill("SELL", timestamp, price, quantity, notional, fee)
