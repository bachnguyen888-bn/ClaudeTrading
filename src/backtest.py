"""
BTC backtest engine: replays historical bars and simulates the strategy.

For each bar, in this order:
  1. At the OPEN: fill any order decided at the previous bar's close.
  2. During the bar: check whether the stop-loss or take-profit was hit,
     then (if enabled) trail the stop up behind the price.
  3. At the CLOSE: mark the account to market and check risk limits.
  4. At the CLOSE: ask the strategy for a signal, run it through the
     risk gate and the volatility filter, and queue an order for the next
     open, or log a SKIP explaining why not.

Every entry, exit and skipped trade is written to the trade log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import metrics
from .data_loader import Bar, bars_per_year
from .paper_broker import PaperBroker
from .risk import RiskManager
from .signals import BUY, SELL, build_strategy
from .trade_logger import ENTRY, EXIT, HALT, SKIP, TradeLogger
from .volatility import VolatilityFilter

log = logging.getLogger(__name__)

MARKET = "BTC-USD"


@dataclass
class BacktestResult:
    run_id: str
    strategy: str
    data_label: str
    metrics: Dict[str, Any]
    equity_curve: List[Tuple[datetime, float]]
    benchmark_curve: List[Tuple[datetime, float]]
    round_trips: List[Dict[str, Any]]
    event_counts: Dict[str, int]
    skip_reasons: Dict[str, int]
    halted: bool = False
    notes: List[str] = field(default_factory=list)


def run_backtest(bars: List[Bar], config: Dict[str, Any], logger: TradeLogger,
                 data_label: str = "") -> BacktestResult:
    starting_cash = float(config["starting_cash_usd"])
    fee_pct = config["costs"]["fee_pct"]
    periods_per_year = bars_per_year(bars)

    strategy = build_strategy(config["strategy"])
    strategy.prepare(bars)
    vol_filter = VolatilityFilter(config["volatility_filter"], periods_per_year)
    vol_filter.prepare(bars)
    broker = PaperBroker(starting_cash, fee_pct, config["costs"]["slippage_pct"])
    risk = RiskManager(config["risk"], starting_cash)

    warmup = max(strategy.warmup_bars, vol_filter.warmup_bars)
    if len(bars) <= warmup + 1:
        raise ValueError(f"Need more than {warmup + 1} bars for this strategy; got {len(bars)}.")

    log.info("Backtesting %s on %d bars (%s -> %s)", strategy.name, len(bars),
             bars[0].timestamp.date(), bars[-1].timestamp.date())

    equity_curve: List[Tuple[datetime, float]] = []
    round_trips: List[Dict[str, Any]] = []
    pending_entry: Optional[Dict[str, Any]] = None
    pending_exit: Optional[Dict[str, str]] = None
    position: Optional[Dict[str, Any]] = None  # details of the open trade
    bars_in_position = 0

    def open_position(i: int, bar: Bar, order: Dict[str, Any]) -> None:
        nonlocal position
        equity_now = broker.equity(bar.open)
        entry_price = broker.buy_price(bar.open)
        sizing = risk.size_position(equity_now, broker.cash, entry_price, order["atr"], fee_pct)
        if not sizing.approved:
            logger.log(SKIP, bar.timestamp, MARKET, "BUY", sizing.reason, price=entry_price,
                       cash_after=broker.cash, equity_after=equity_now,
                       details={"signal": order["signal_reason"], "atr": round(order["atr"], 2)})
            return
        fill = broker.buy(bar.timestamp, bar.open, sizing.quantity)
        risk.record_entry()
        position = {
            "entry_index": i,
            "entry_time": bar.timestamp,
            "entry_price": fill.price,
            "quantity": fill.quantity,
            "stop": sizing.stop_price,
            "take_profit": sizing.take_profit_price,
        }
        logger.log(ENTRY, bar.timestamp, MARKET, "BUY", "signal", price=fill.price,
                   quantity=fill.quantity, notional=fill.notional, fee=fill.fee,
                   cash_after=broker.cash, equity_after=broker.equity(bar.open),
                   details={
                       "signal": order["signal_reason"],
                       "stop_loss": round(sizing.stop_price, 2),
                       "take_profit": round(sizing.take_profit_price, 2) if sizing.take_profit_price else None,
                       "atr": round(order["atr"], 2),
                       "annual_vol_pct": round(order["vol_pct"], 1),
                       "position_pct_of_equity": round(fill.notional / equity_now * 100, 2),
                   })

    def close_position(i: int, timestamp: datetime, market_price: float, reason: str, note: str = "") -> None:
        nonlocal position
        entry_cost = broker.entry_cost
        fill = broker.sell_all(timestamp, market_price)
        pnl = (fill.notional - fill.fee) - entry_cost
        pnl_pct = pnl / entry_cost * 100.0
        trade = {
            "entry_time": position["entry_time"].isoformat(),
            "exit_time": timestamp.isoformat(),
            "entry_price": position["entry_price"],
            "exit_price": fill.price,
            "quantity": fill.quantity,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "bars_held": i - position["entry_index"],
            "exit_reason": reason,
        }
        round_trips.append(trade)
        details = {"result": "WIN" if pnl > 0 else "LOSS", "bars_held": trade["bars_held"],
                   "stop_at_exit": round(position["stop"], 2)}
        if note:
            details["note"] = note
        logger.log(EXIT, timestamp, MARKET, "SELL", reason, price=fill.price, quantity=fill.quantity,
                   notional=fill.notional, fee=fill.fee, pnl=pnl, pnl_pct=pnl_pct,
                   cash_after=broker.cash, equity_after=broker.cash, details=details)
        position = None

    last_index = len(bars) - 1
    for i, bar in enumerate(bars):
        risk.start_bar(bar.timestamp.date(), broker.equity(bar.open))

        # 1. Fill orders queued at the previous close.
        if pending_exit and broker.in_position:
            close_position(i, bar.timestamp, bar.open, pending_exit["reason"], pending_exit["note"])
        pending_exit = None
        if pending_entry and not broker.in_position:
            open_position(i, bar, pending_entry)
        pending_entry = None

        # 2. Stop-loss / take-profit inside this bar. The stop is checked
        #    first: if both were touched we assume the worse outcome.
        if position is not None:
            if bar.low <= position["stop"]:
                close_position(i, bar.timestamp, min(bar.open, position["stop"]), "stop_loss")
            elif position["take_profit"] and bar.high >= position["take_profit"]:
                close_position(i, bar.timestamp, max(bar.open, position["take_profit"]), "take_profit")

        if position is not None:
            position["stop"] = risk.trail_stop(position["stop"], bar.close, vol_filter.atr[i])

        # 3. Mark to market and check account-level limits.
        equity = broker.equity(bar.close)
        equity_curve.append((bar.timestamp, equity))
        if broker.in_position:
            bars_in_position += 1
        if risk.update_equity(equity):
            logger.log(HALT, bar.timestamp, MARKET, "", "max_drawdown_kill_switch",
                       cash_after=broker.cash, equity_after=equity,
                       details={"drawdown_pct": round(risk.drawdown_pct(equity), 2),
                                "limit_pct": risk.max_drawdown_pct})
            log.warning("Kill switch: drawdown limit of %.1f%% reached on %s. No new trades from now on.",
                        risk.max_drawdown_pct, bar.timestamp.date())
            if broker.in_position:
                pending_exit = {"reason": "kill_switch", "note": "closing because of max_drawdown_pct"}

        # 4. New signal at the close (there is no next bar to act on after the last one).
        if i < warmup or i == last_index:
            continue
        signal = strategy.signal_at(i)
        if signal.action == SELL and broker.in_position and pending_exit is None:
            pending_exit = {"reason": "signal_exit", "note": signal.reason}
        elif signal.action == BUY and not broker.in_position:
            allowed, gate_reason = risk.can_open_trade(equity)
            vol = vol_filter.check(i)
            details = {"signal": signal.reason,
                       "annual_vol_pct": round(vol.annual_vol_pct, 1) if vol.annual_vol_pct is not None else None}
            if not allowed:
                logger.log(SKIP, bar.timestamp, MARKET, "BUY", gate_reason, price=bar.close,
                           cash_after=broker.cash, equity_after=equity, details=details)
            elif not vol.allowed:
                logger.log(SKIP, bar.timestamp, MARKET, "BUY", vol.reason, price=bar.close,
                           cash_after=broker.cash, equity_after=equity, details=details)
            else:
                pending_entry = {"signal_reason": signal.reason, "atr": vol.atr, "vol_pct": vol.annual_vol_pct}

    # Close anything still open at the final price so the results are complete.
    if broker.in_position:
        last = bars[-1]
        close_position(last_index, last.timestamp, last.close, "end_of_data")
        equity_curve[-1] = (last.timestamp, broker.cash)

    closes = [b.close for b in bars]
    benchmark_curve = [(b.timestamp, starting_cash * b.close / closes[0]) for b in bars]
    summary = metrics.summarize_equity(equity_curve, periods_per_year)
    summary.update(metrics.trade_stats([t["pnl"] for t in round_trips]))
    summary.update(metrics.buy_and_hold(closes, starting_cash))
    summary["total_fees"] = broker.total_fees
    summary["exposure_pct"] = bars_in_position / len(bars) * 100.0
    summary["skipped_signals"] = sum(logger.skip_reasons.values())
    summary["bars"] = len(bars)
    summary["bars_per_year"] = round(periods_per_year, 1)

    return BacktestResult(
        run_id=logger.run_id,
        strategy=strategy.name,
        data_label=data_label,
        metrics=summary,
        equity_curve=equity_curve,
        benchmark_curve=benchmark_curve,
        round_trips=round_trips,
        event_counts=dict(logger.counts),
        skip_reasons=dict(logger.skip_reasons),
        halted=risk.halted,
    )
