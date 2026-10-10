"""
Load and check config.json.

Every risk limit lives in config.json, so you can change behaviour without
touching code. This module fills in defaults for anything you leave out, warns
about keys it doesn't recognise (usually typos), and explains bad values in
plain English.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

STRATEGIES = ("sma_crossover", "rsi_mean_reversion", "donchian_breakout")

DEFAULTS: Dict[str, Any] = {
    "mode": "paper",
    "starting_cash_usd": 10000,
    "data": {
        "btc_csv": "data/btc_usd_1d.csv",
        "sample_btc_csv": "data/sample/btc_usd_1d_sample.csv",
        "prediction_markets_csv": "data/sample/prediction_markets_sample.csv",
        "download_source": "coinbase",
        "download_start": "2016-01-01",
        "download_granularity": "1d",
    },
    "backtest": {
        "start_date": None,
        "end_date": None,
    },
    "costs": {
        "fee_pct": 0.10,
        "slippage_pct": 0.05,
    },
    "strategy": {
        "name": "sma_crossover",
        "sma_crossover": {"fast_period": 20, "slow_period": 50},
        "rsi_mean_reversion": {"period": 14, "buy_below": 30, "sell_above": 55},
        "donchian_breakout": {"entry_lookback": 20, "exit_lookback": 10},
    },
    "volatility_filter": {
        "enabled": True,
        "lookback_bars": 20,
        "min_annual_vol_pct": 15,
        "max_annual_vol_pct": 120,
        "atr_period": 14,
    },
    "risk": {
        "risk_per_trade_pct": 1.0,
        "stop_loss_atr_multiple": 2.0,
        "trailing_stop": True,
        "take_profit_atr_multiple": 0,
        "max_position_pct": 50.0,
        "max_daily_loss_pct": 3.0,
        "max_drawdown_pct": 20.0,
        "max_trades_per_day": 2,
        "min_trade_usd": 25,
    },
    "prediction_markets": {
        "starting_cash_usd": 1000,
        "vol_lookback_days": 30,
        "min_edge": 0.05,
        "kelly_fraction": 0.25,
        "max_stake_pct": 2.0,
        "max_total_exposure_pct": 20.0,
        "min_price": 0.05,
        "max_price": 0.95,
        "price_slippage": 0.01,
        "fee_per_contract": 0.01,
        "min_annual_vol_pct": 15,
        "max_annual_vol_pct": 150,
        "max_drawdown_pct": 25.0,
    },
    "output": {
        "log_dir": "logs",
        "results_dir": "results",
        "log_level": "INFO",
        "terminal_chart": True,
    },
}

# (setting, kind, minimum, maximum, what it means)
RULES: List[Tuple[str, str, Any, Any, str]] = [
    ("starting_cash_usd", "number", 1, 1e12, "pretend money the BTC backtest starts with"),
    ("data.download_source", "choice:coinbase,kraken", None, None, "where 'download' fetches public price history"),
    ("data.download_granularity", "choice:1d,1h", None, None, "candle size for 'download'"),
    ("data.download_start", "date", None, None, "first date to download (YYYY-MM-DD)"),
    ("backtest.start_date", "date_or_null", None, None, "first date to backtest, or null for all data"),
    ("backtest.end_date", "date_or_null", None, None, "last date to backtest, or null for all data"),
    ("costs.fee_pct", "number", 0, 5, "exchange fee per fill, in percent (0.1 = 0.1%)"),
    ("costs.slippage_pct", "number", 0, 5, "price slippage per fill, in percent"),
    ("strategy.name", "choice:" + ",".join(STRATEGIES), None, None, "which signal generator to use"),
    ("strategy.sma_crossover.fast_period", "int", 2, 500, "fast moving-average length in bars"),
    ("strategy.sma_crossover.slow_period", "int", 3, 1000, "slow moving-average length in bars"),
    ("strategy.rsi_mean_reversion.period", "int", 2, 200, "RSI length in bars"),
    ("strategy.rsi_mean_reversion.buy_below", "number", 1, 99, "buy when RSI drops below this"),
    ("strategy.rsi_mean_reversion.sell_above", "number", 1, 99, "sell when RSI rises above this"),
    ("strategy.donchian_breakout.entry_lookback", "int", 2, 500, "buy on a close above the highest high of this many bars"),
    ("strategy.donchian_breakout.exit_lookback", "int", 2, 500, "sell on a close below the lowest low of this many bars"),
    ("volatility_filter.enabled", "bool", None, None, "turn the volatility filter on/off"),
    ("volatility_filter.lookback_bars", "int", 2, 500, "bars used to measure volatility"),
    ("volatility_filter.min_annual_vol_pct", "number", 0, 1000, "skip entries when volatility is below this"),
    ("volatility_filter.max_annual_vol_pct", "number", 1, 1000, "skip entries when volatility is above this"),
    ("volatility_filter.atr_period", "int", 2, 500, "bars used for ATR (average true range)"),
    ("risk.risk_per_trade_pct", "number", 0.01, 10, "percent of equity you accept losing if the stop is hit"),
    ("risk.stop_loss_atr_multiple", "number", 0.1, 20, "stop-loss distance in ATRs below entry"),
    ("risk.trailing_stop", "bool", None, None, "move the stop up as the price rises (never down)"),
    ("risk.take_profit_atr_multiple", "number", 0, 50, "take-profit distance in ATRs above entry (0 = off)"),
    ("risk.max_position_pct", "number", 1, 100, "largest position as percent of equity (100 = no leverage)"),
    ("risk.max_daily_loss_pct", "number", 0.1, 100, "stop opening trades for the day after losing this much"),
    ("risk.max_drawdown_pct", "number", 1, 100, "kill switch: close everything and stop at this drop from peak"),
    ("risk.max_trades_per_day", "int", 1, 1000, "most new positions per calendar day"),
    ("risk.min_trade_usd", "number", 0, 1e9, "skip trades smaller than this"),
    ("prediction_markets.starting_cash_usd", "number", 1, 1e12, "pretend money for prediction-market bets"),
    ("prediction_markets.vol_lookback_days", "int", 2, 365, "days of BTC history used by the probability model"),
    ("prediction_markets.min_edge", "number", 0, 1, "minimum model-minus-price edge, in dollars per $1 contract"),
    ("prediction_markets.kelly_fraction", "number", 0, 1, "fraction of the Kelly bet size to use (0.25 = quarter Kelly)"),
    ("prediction_markets.max_stake_pct", "number", 0.01, 100, "largest single bet as percent of bankroll"),
    ("prediction_markets.max_total_exposure_pct", "number", 0.01, 100, "most bankroll allowed in open bets at once"),
    ("prediction_markets.min_price", "number", 0, 1, "skip markets whose YES price is below this"),
    ("prediction_markets.max_price", "number", 0, 1, "skip markets whose YES price is above this"),
    ("prediction_markets.price_slippage", "number", 0, 0.5, "dollars added to the price you pay per contract"),
    ("prediction_markets.fee_per_contract", "number", 0, 0.5, "fee in dollars per contract"),
    ("prediction_markets.min_annual_vol_pct", "number", 0, 1000, "skip BTC markets when volatility is below this"),
    ("prediction_markets.max_annual_vol_pct", "number", 1, 1000, "skip BTC markets when volatility is above this"),
    ("prediction_markets.max_drawdown_pct", "number", 1, 100, "kill switch: stop betting at this drop from peak"),
    ("output.log_level", "choice:DEBUG,INFO,WARNING,ERROR", None, None, "how chatty the console log is"),
    ("output.terminal_chart", "bool", None, None, "draw an ASCII equity chart in the terminal"),
]


class ConfigError(ValueError):
    """config.json has a value we can't use. The message says how to fix it."""


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Tuple[Dict[str, Any], List[str]]:
    """Return (config, warnings). Raises ConfigError with a friendly message."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        user_config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{path.name} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}.\n"
            "Common causes: a trailing comma, a missing comma, or // comments (JSON has none)."
        ) from exc
    if not isinstance(user_config, dict):
        raise ConfigError(f"{path.name} must contain a JSON object {{ ... }} at the top level.")

    warnings: List[str] = []
    config = _merge(copy.deepcopy(DEFAULTS), user_config, prefix="", warnings=warnings)
    validate(config)
    return config, warnings


def _merge(base: Dict[str, Any], override: Dict[str, Any], prefix: str, warnings: List[str]) -> Dict[str, Any]:
    for key, value in override.items():
        key_path = f"{prefix}{key}"
        if key.startswith("_"):
            continue  # "_note" style keys are comments
        if key not in base:
            # Unknown keys are kept (the safety guard inspects them) but flagged.
            warnings.append(f"Unknown setting '{key_path}' is ignored. Typo?")
            base[key] = value
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value, prefix=f"{key_path}.", warnings=warnings)
        else:
            base[key] = value
    return base


def get_setting(config: Dict[str, Any], dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        node = node[part]
    return node


def validate(config: Dict[str, Any]) -> None:
    problems: List[str] = []
    for dotted, kind, low, high, meaning in RULES:
        value = get_setting(config, dotted)
        problem = _check_value(value, kind, low, high)
        if problem:
            problems.append(f"- {dotted} = {value!r}: {problem}. (It means: {meaning}.)")

    if not problems:
        problems.extend(_cross_checks(config))
    if problems:
        raise ConfigError("config.json needs fixing:\n" + "\n".join(problems))


def _check_value(value: Any, kind: str, low: Any, high: Any) -> str:
    if kind.startswith("choice:"):
        choices = kind[len("choice:"):].split(",")
        return "" if value in choices else f"must be one of {', '.join(choices)}"
    if kind == "bool":
        return "" if isinstance(value, bool) else "must be true or false"
    if kind in ("date", "date_or_null"):
        if value is None and kind == "date_or_null":
            return ""
        try:
            date.fromisoformat(str(value))
            return ""
        except ValueError:
            return "must be a date like \"2020-01-31\"" + (" or null" if kind == "date_or_null" else "")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "must be a number"
    if kind == "int" and int(value) != value:
        return "must be a whole number"
    if low is not None and value < low:
        return f"must be at least {low}"
    if high is not None and value > high:
        return f"must be at most {high}"
    return ""


def _cross_checks(config: Dict[str, Any]) -> List[str]:
    problems = []
    sma = config["strategy"]["sma_crossover"]
    if sma["fast_period"] >= sma["slow_period"]:
        problems.append("- strategy.sma_crossover: fast_period must be smaller than slow_period.")
    rsi = config["strategy"]["rsi_mean_reversion"]
    if rsi["buy_below"] >= rsi["sell_above"]:
        problems.append("- strategy.rsi_mean_reversion: buy_below must be smaller than sell_above.")
    vol = config["volatility_filter"]
    if vol["min_annual_vol_pct"] >= vol["max_annual_vol_pct"]:
        problems.append("- volatility_filter: min_annual_vol_pct must be smaller than max_annual_vol_pct.")
    pm = config["prediction_markets"]
    if pm["min_price"] >= pm["max_price"]:
        problems.append("- prediction_markets: min_price must be smaller than max_price.")
    if pm["min_annual_vol_pct"] >= pm["max_annual_vol_pct"]:
        problems.append("- prediction_markets: min_annual_vol_pct must be smaller than max_annual_vol_pct.")
    bt = config["backtest"]
    if bt["start_date"] and bt["end_date"] and bt["start_date"] > bt["end_date"]:
        problems.append("- backtest: start_date is after end_date.")
    return problems


def resolve_path(relative: str | Path) -> Path:
    """Paths in config.json are relative to the project folder."""
    path = Path(relative)
    return path if path.is_absolute() else PROJECT_ROOT / path
