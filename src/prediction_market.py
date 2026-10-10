"""
Prediction-market paper experiment.

A binary contract pays $1 if its question resolves YES and $0 otherwise, so
a YES price of $0.30 means "the market thinks there's about a 30% chance".
You can also buy NO, which costs (1 - YES price).

The experiment:
  1. Estimate our own probability for each market, either
       * from a `my_probability` column you fill in yourself, or
       * for "Will BTC close above $K?" markets, from a simple model: BTC's
         recent volatility plus a lognormal price distribution.
  2. Compare it with the market price. If our edge (after slippage and fees)
     is at least `min_edge`, place a simulated bet on the cheaper side.
  3. Size the bet with fractional Kelly, capped by the config limits.
  4. When the market resolves, pay out $1 per winning contract.

Every market produces a log row: BET, RESOLVE (win or loss) or SKIP (with
the reason). Open bets are valued at cost until they resolve.
"""

from __future__ import annotations

import bisect
import csv
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import metrics, safety
from .data_loader import Bar, bars_per_year, parse_timestamp
from .indicators import realized_volatility
from .risk import binary_bet_stake
from .trade_logger import BET, HALT, RESOLVE, SKIP, TradeLogger
from .volatility import vol_band_check

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("market_id", "decision_time", "resolve_time", "yes_price", "outcome")


@dataclass(frozen=True)
class Market:
    market_id: str
    question: str
    decision_time: datetime  # when we decide whether to bet (price observed here)
    resolve_time: datetime  # when the outcome is known and bets pay out
    yes_price: float  # price of one YES contract, between 0 and 1
    outcome: int  # 1 = resolved YES, 0 = resolved NO
    strike: Optional[float] = None  # for "BTC above $strike" markets
    my_probability: Optional[float] = None  # your own forecast, if you have one


@dataclass
class PredictionResult:
    run_id: str
    data_label: str
    metrics: Dict[str, Any]
    equity_curve: List[Tuple[datetime, float]]
    bets: List[Dict[str, Any]]
    event_counts: Dict[str, int]
    skip_reasons: Dict[str, int]
    calibration: List[Dict[str, Any]]
    halted: bool = False


# --- loading ------------------------------------------------------------

def load_markets_csv(path: str | Path) -> List[Market]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Prediction-market data not found: {path}")
    markets: List[Market] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing column(s): {', '.join(missing)}")
        for line_no, row in enumerate(reader, start=2):
            try:
                markets.append(_row_to_market(row))
            except (ValueError, KeyError) as exc:
                raise ValueError(f"{path.name} line {line_no}: {exc}") from exc
    markets.sort(key=lambda m: (m.decision_time, m.market_id))
    return markets


def _row_to_market(row: Dict[str, str]) -> Market:
    yes_price = float(row["yes_price"])
    if not 0.0 < yes_price < 1.0:
        raise ValueError(f"yes_price must be between 0 and 1, got {yes_price}")
    outcome = int(float(row["outcome"]))
    if outcome not in (0, 1):
        raise ValueError(f"outcome must be 0 or 1, got {row['outcome']}")
    decision_time = parse_timestamp(row["decision_time"])
    resolve_time = parse_timestamp(row["resolve_time"])
    if resolve_time <= decision_time:
        raise ValueError("resolve_time must be after decision_time")
    strike = float(row["strike"]) if row.get("strike") else None
    my_probability = float(row["my_probability"]) if row.get("my_probability") else None
    if my_probability is not None and not 0.0 <= my_probability <= 1.0:
        raise ValueError(f"my_probability must be between 0 and 1, got {my_probability}")
    if strike is None and my_probability is None:
        raise ValueError("each market needs either a strike (BTC model) or my_probability")
    return Market(row["market_id"], row.get("question", ""), decision_time, resolve_time,
                  yes_price, outcome, strike, my_probability)


# --- probability model ---------------------------------------------------

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_above_strike(spot: float, strike: float, annual_vol: float, years: float) -> float:
    """
    Chance BTC finishes above `strike`, assuming no drift and lognormal moves:
        P = N(d2),  d2 = (ln(S/K) - vol^2 * T / 2) / (vol * sqrt(T))
    """
    if years <= 0 or annual_vol <= 0:
        return 1.0 if spot > strike else 0.0
    d2 = (math.log(spot / strike) - 0.5 * annual_vol ** 2 * years) / (annual_vol * math.sqrt(years))
    return normal_cdf(d2)


class BtcThresholdModel:
    """Looks up the latest COMPLETED BTC bar before a decision time, so it never peeks ahead."""

    def __init__(self, bars: List[Bar], vol_lookback_days: int):
        self.bars = bars
        self.closes = [b.close for b in bars]
        self.bar_length = timedelta(days=365) / bars_per_year(bars)
        # A bar's close is only known once the bar has finished.
        self.close_times = [b.timestamp + self.bar_length for b in bars]
        self.vol = realized_volatility(self.closes, vol_lookback_days, bars_per_year(bars))

    def covers(self, when: datetime) -> bool:
        return bool(self.close_times) and self.close_times[0] <= when <= self.close_times[-1] + self.bar_length

    def estimate(self, market: Market) -> Tuple[Optional[float], Dict[str, Any], str]:
        """Return (probability, details, problem). problem is '' when the estimate is usable."""
        index = bisect.bisect_right(self.close_times, market.decision_time) - 1
        if index < 0 or not self.covers(market.decision_time):
            return None, {}, "no_btc_history"
        vol = self.vol[index]
        if vol is None:
            return None, {}, "volatility_not_ready"
        spot = self.closes[index]
        years = (market.resolve_time - market.decision_time).total_seconds() / (365.0 * 86400.0)
        p = prob_above_strike(spot, market.strike, vol, years)
        details = {"spot": round(spot, 2), "strike": market.strike, "annual_vol_pct": round(vol * 100, 1),
                   "days_to_resolve": round(years * 365, 2)}
        return p, details, ""


# --- simulation ----------------------------------------------------------

def run_prediction_backtest(markets: List[Market], btc_bars: Optional[List[Bar]], config: Dict[str, Any],
                            logger: TradeLogger, data_label: str = "") -> PredictionResult:
    safety.assert_paper_mode()
    if not markets:
        raise ValueError("No markets to simulate.")
    pm = config["prediction_markets"]
    model = BtcThresholdModel(btc_bars, pm["vol_lookback_days"]) if btc_bars else None

    cash = float(pm["starting_cash_usd"])
    peak = cash
    halted = False
    open_bets: List[Dict[str, Any]] = []
    settled: List[Dict[str, Any]] = []
    equity_curve: List[Tuple[datetime, float]] = [(markets[0].decision_time, cash)]
    forecasts: List[Tuple[float, float, int]] = []  # (model p, market p, outcome)
    total_fees = 0.0

    def equity() -> float:
        return cash + sum(b["cost"] for b in open_bets)

    def check_halt(when: datetime) -> None:
        nonlocal peak, halted
        current = equity()
        peak = max(peak, current)
        drawdown = (peak - current) / peak * 100.0 if peak > 0 else 0.0
        if not halted and drawdown >= pm["max_drawdown_pct"]:
            halted = True
            logger.log(HALT, when, "PREDICTION", "", "max_drawdown_kill_switch", cash_after=cash,
                       equity_after=current, details={"drawdown_pct": round(drawdown, 2),
                                                      "limit_pct": pm["max_drawdown_pct"]})
            log.warning("Prediction kill switch: drawdown limit %.1f%% reached on %s.",
                        pm["max_drawdown_pct"], when.date())

    def resolve_until(when: Optional[datetime]) -> None:
        nonlocal cash
        due = sorted((b for b in open_bets if when is None or b["resolve_time"] <= when),
                     key=lambda b: b["resolve_time"])
        for bet in due:
            open_bets.remove(bet)
            won = bet["outcome"] == bet["wins_if"]
            payout = bet["contracts"] * 1.0 if won else 0.0
            cash += payout
            pnl = payout - bet["cost"]
            bet.update(payout=payout, pnl=pnl, won=won)
            settled.append(bet)
            logger.log(RESOLVE, bet["resolve_time"], bet["market_id"], bet["side"], "WIN" if won else "LOSS",
                       price=1.0 if won else 0.0, quantity=bet["contracts"], notional=payout,
                       pnl=pnl, pnl_pct=pnl / bet["cost"] * 100.0, cash_after=cash, equity_after=equity(),
                       details={"outcome": "YES" if bet["outcome"] else "NO"})
            equity_curve.append((bet["resolve_time"], equity()))
            check_halt(bet["resolve_time"])

    for market in markets:
        resolve_until(market.decision_time)

        def skip(reason: str, extra: Optional[Dict[str, Any]] = None) -> None:
            details = {"question": market.question, "yes_price": market.yes_price}
            details.update(extra or {})
            logger.log(SKIP, market.decision_time, market.market_id, "", reason, price=market.yes_price,
                       cash_after=cash, equity_after=equity(), details=details)

        # Our probability: your own forecast wins over the BTC model.
        info: Dict[str, Any] = {}
        if market.my_probability is not None:
            p_yes, problem, source = market.my_probability, "", "my_probability"
        elif model is not None:
            p_yes, info, problem = model.estimate(market)
            source = "btc_lognormal_model"
        else:
            p_yes, problem, source = None, "no_btc_history", "none"

        if p_yes is not None:
            forecasts.append((p_yes, market.yes_price, market.outcome))

        if halted:
            skip("max_drawdown_halt")
            continue
        if p_yes is None:
            skip(problem)
            continue
        if source == "btc_lognormal_model":
            vol_problem = vol_band_check(info.get("annual_vol_pct"), pm["min_annual_vol_pct"],
                                         pm["max_annual_vol_pct"])
            if vol_problem:
                skip(vol_problem, info)
                continue
        if not pm["min_price"] <= market.yes_price <= pm["max_price"]:
            skip("price_out_of_range", {"model_p_yes": round(p_yes, 4)})
            continue

        fee = pm["fee_per_contract"]
        yes_cost = market.yes_price + pm["price_slippage"]
        no_cost = (1.0 - market.yes_price) + pm["price_slippage"]
        yes_edge = p_yes - yes_cost - fee
        no_edge = (1.0 - p_yes) - no_cost - fee
        if yes_edge >= no_edge:
            side, cost, win_prob, edge, wins_if = "YES", yes_cost, p_yes, yes_edge, 1
        else:
            side, cost, win_prob, edge, wins_if = "NO", no_cost, 1.0 - p_yes, no_edge, 0

        decision = {"model_p_yes": round(p_yes, 4), "source": source, "best_side": side,
                    "edge_after_costs": round(edge, 4)}
        decision.update(info)
        if edge < pm["min_edge"]:
            skip("edge_too_small", decision)
            continue

        current_equity = equity()
        open_exposure = sum(b["cost"] for b in open_bets)
        exposure_room = current_equity * pm["max_total_exposure_pct"] / 100.0 - open_exposure
        all_in_cost = cost + fee
        if exposure_room < all_in_cost:
            skip("max_total_exposure", decision)
            continue
        stake = binary_bet_stake(current_equity, win_prob, all_in_cost, pm["kelly_fraction"],
                                 pm["max_stake_pct"], exposure_room)
        contracts = math.floor(stake / all_in_cost)
        if contracts < 1:
            skip("size_too_small", decision)
            continue

        bet_cost = contracts * all_in_cost
        cash -= bet_cost
        total_fees += contracts * fee
        bet = {"market_id": market.market_id, "question": market.question, "side": side,
               "contracts": contracts, "price": cost, "cost": bet_cost, "edge": edge,
               "model_p_yes": p_yes, "yes_price": market.yes_price, "wins_if": wins_if,
               "outcome": market.outcome, "decision_time": market.decision_time,
               "resolve_time": market.resolve_time}
        open_bets.append(bet)
        logger.log(BET, market.decision_time, market.market_id, side, "edge", price=cost,
                   quantity=contracts, notional=bet_cost, fee=contracts * fee,
                   cash_after=cash, equity_after=equity(), details=decision)
        equity_curve.append((market.decision_time, equity()))

    resolve_until(None)

    values = [v for _, v in equity_curve]
    stats = metrics.trade_stats([b["pnl"] for b in settled])
    model_ps = [f[0] for f in forecasts]
    market_ps = [f[1] for f in forecasts]
    outcomes = [f[2] for f in forecasts]
    summary: Dict[str, Any] = {
        "start_date": markets[0].decision_time.date().isoformat(),
        "end_date": max(m.resolve_time for m in markets).date().isoformat(),
        "markets": len(markets),
        "start_equity": values[0],
        "end_equity": values[-1],
        "total_return_pct": (values[-1] / values[0] - 1.0) * 100.0,
        "max_drawdown_pct": metrics.max_drawdown_pct(values),
        "total_fees": total_fees,
        "total_staked": sum(b["cost"] for b in settled),
        "avg_edge": (sum(b["edge"] for b in settled) / len(settled)) if settled else None,
        "brier_model": metrics.brier_score(model_ps, outcomes),
        "brier_market": metrics.brier_score(market_ps, outcomes),
        "forecasts_scored": len(forecasts),
        "skipped_markets": sum(logger.skip_reasons.values()),
    }
    summary.update(stats)
    summary["bets"] = summary.pop("trades")

    return PredictionResult(
        run_id=logger.run_id,
        data_label=data_label,
        metrics=summary,
        equity_curve=equity_curve,
        bets=[_serializable(b) for b in settled],
        event_counts=dict(logger.counts),
        skip_reasons=dict(logger.skip_reasons),
        calibration=calibration_table(model_ps, market_ps, outcomes),
        halted=halted,
    )


def calibration_table(model_ps: List[float], market_ps: List[float], outcomes: List[int],
                      buckets: int = 5) -> List[Dict[str, Any]]:
    """Group forecasts into probability buckets and compare with how often YES actually happened."""
    rows = []
    for k in range(buckets):
        lo, hi = k / buckets, (k + 1) / buckets
        idx = [i for i, p in enumerate(model_ps) if lo <= p < hi or (k == buckets - 1 and p == 1.0)]
        mkt_idx = [i for i, p in enumerate(market_ps) if lo <= p < hi or (k == buckets - 1 and p == 1.0)]
        rows.append({
            "bucket": f"{lo:.0%}-{hi:.0%}",
            "model_count": len(idx),
            "model_avg_p": (sum(model_ps[i] for i in idx) / len(idx)) if idx else None,
            "model_yes_rate": (sum(outcomes[i] for i in idx) / len(idx)) if idx else None,
            "market_count": len(mkt_idx),
            "market_avg_p": (sum(market_ps[i] for i in mkt_idx) / len(mkt_idx)) if mkt_idx else None,
            "market_yes_rate": (sum(outcomes[i] for i in mkt_idx) / len(mkt_idx)) if mkt_idx else None,
        })
    return rows


def _serializable(bet: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in bet.items()}
