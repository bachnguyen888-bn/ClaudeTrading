"""
Command-line entry point. Run from the project folder:

    python -m src.main check                 # verify setup and paper mode
    python -m src.main backtest              # BTC strategy backtest
    python -m src.main predict               # prediction-market paper experiment
    python -m src.main download              # fetch public historical BTC prices
    python -m src.main make-sample-markets   # rebuild the sample prediction markets
    python -m src.main summary               # re-print the latest run's summary
    python -m src.main live                  # always refuses: paper mode only

Every command loads .env and config.json and runs the paper-mode safety checks first.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import dashboard, downloader, results_store, safety
from .backtest import run_backtest
from .config import DEFAULT_CONFIG_PATH, PROJECT_ROOT, ConfigError, load_config, resolve_path, validate
from .data_loader import Bar, filter_dates, load_ohlcv_csv, save_ohlcv_csv
from .env_loader import load_env_file
from .prediction_market import load_markets_csv, run_prediction_backtest
from .sample_markets import make_sample_markets
from .trade_logger import TradeLogger, new_run_id, setup_logging

log = logging.getLogger("paper")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.main",
                                     description="BTC & prediction-market PAPER-TRADING research tool.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="path to config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="check config, .env and paper-mode safety")

    bt = sub.add_parser("backtest", help="backtest a BTC strategy on historical data")
    bt.add_argument("--strategy", help="override strategy.name from config.json")
    bt.add_argument("--start", help="first date, YYYY-MM-DD")
    bt.add_argument("--end", help="last date, YYYY-MM-DD")
    bt.add_argument("--csv", help="price CSV to use instead of the configured one")

    pr = sub.add_parser("predict", help="run the prediction-market paper experiment")
    pr.add_argument("--markets", help="prediction-market CSV to use instead of the configured one")
    pr.add_argument("--btc-csv", help="BTC price CSV for the probability model")

    dl = sub.add_parser("download", help="download public historical BTC prices (read-only, no keys)")
    dl.add_argument("--source", choices=["coinbase", "kraken"], help="override data.download_source")
    dl.add_argument("--granularity", choices=["1d", "1h"], help="override data.download_granularity")
    dl.add_argument("--start", help="override data.download_start (YYYY-MM-DD)")
    dl.add_argument("--out", help="where to save (default: data.btc_csv, or btc_usd_1h.csv for hourly)")

    mk = sub.add_parser("make-sample-markets", help="rebuild the sample prediction-market CSV from BTC data")
    mk.add_argument("--btc-csv", help="daily BTC CSV to build from")
    mk.add_argument("--out", help="output CSV (default: data.prediction_markets_csv)")
    mk.add_argument("--seed", type=int, default=42, help="random seed for the simulated prices")

    sm = sub.add_parser("summary", help="print the summary of the latest (or a given) run")
    sm.add_argument("--run", help="run id (folder name in results/)")

    sub.add_parser("live", help="refuses: this project is paper mode only")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "live":
        try:
            safety.refuse_live_execution("the 'live' command exists only to say no.")
        except safety.LiveTradingRefused as exc:
            print(exc, file=sys.stderr)
            return 2

    try:
        env_values = load_env_file(PROJECT_ROOT / ".env")
        config, warnings = load_config(args.config)
        safety.enforce_paper_mode(config, env_values)
        if args.command not in ("backtest", "predict"):
            logging.basicConfig(level=getattr(logging, config["output"]["log_level"]),
                                format="%(levelname)-7s %(message)s")
        for warning in warnings:
            log.warning(warning)
        handler = COMMANDS[args.command]
        return handler(args, config)
    except safety.LiveTradingRefused as exc:
        print(exc, file=sys.stderr)
        return 2
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


# --- commands -----------------------------------------------------------

def cmd_check(args, config) -> int:
    print(safety.BANNER)
    btc_path = resolve_path(config["data"]["btc_csv"])
    sample_path = resolve_path(config["data"]["sample_btc_csv"])
    markets_path = resolve_path(config["data"]["prediction_markets_csv"])
    env_path = PROJECT_ROOT / ".env"
    print("  Paper-mode safety checks ......... PASSED")
    print(f"  config.json ...................... OK ({args.config})")
    print(f"  .env ............................. {'found' if env_path.exists() else 'not found (optional; copy .env.example)'}")
    print(f"  BTC data ......................... {_describe_csv(btc_path)}")
    print(f"  Bundled sample BTC data .......... {_describe_csv(sample_path)}")
    print(f"  Prediction-market data ........... {_describe_csv(markets_path)}")
    risk = config["risk"]
    print(f"  Strategy ......................... {config['strategy']['name']}")
    print(f"  Risk per trade / max position .... {risk['risk_per_trade_pct']}% / {risk['max_position_pct']}%")
    print(f"  Daily loss limit / kill switch ... {risk['max_daily_loss_pct']}% / {risk['max_drawdown_pct']}% drawdown")
    print("  Live trading ..................... NOT AVAILABLE (by design)")
    return 0


def _describe_csv(path: Path) -> str:
    if not path.exists():
        return f"missing ({_rel(path)})"
    with path.open(encoding="utf-8") as handle:
        rows = sum(1 for _ in handle) - 1
    return f"{rows} rows ({_rel(path)})"


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _choose_btc_csv(config, override: Optional[str]) -> Tuple[Path, str]:
    if override:
        path = resolve_path(override)
        return path, _rel(path)
    path = resolve_path(config["data"]["btc_csv"])
    if path.exists():
        return path, _rel(path)
    sample = resolve_path(config["data"]["sample_btc_csv"])
    log.warning("%s not found, so using the bundled SAMPLE data (real Bitstamp prices, 2013-2017).",
                _rel(path))
    log.warning("For up-to-date history run:  python -m src.main download")
    return sample, f"bundled sample ({_rel(sample)})"


def _start_run(config, experiment: str) -> Tuple[str, Path, Path]:
    run_id = new_run_id(experiment)
    log_dir = resolve_path(config["output"]["log_dir"])
    results_dir = resolve_path(config["output"]["results_dir"])
    setup_logging(log_dir, run_id, config["output"]["log_level"])
    return run_id, log_dir, results_dir


def cmd_backtest(args, config) -> int:
    if args.strategy:
        config["strategy"]["name"] = args.strategy
        validate(config)
    run_id, log_dir, results_dir = _start_run(config, "btc_backtest")
    print(safety.BANNER)
    csv_path, label = _choose_btc_csv(config, args.csv)
    bars = load_ohlcv_csv(csv_path)
    bars = filter_dates(bars, args.start or config["backtest"]["start_date"],
                        args.end or config["backtest"]["end_date"])
    if len(bars) < 2:
        raise ValueError("No price data in the chosen date range.")

    with TradeLogger(run_id, "btc_backtest", log_dir, results_dir) as logger:
        result = run_backtest(bars, config, logger, data_label=label)
        run_dir = logger.run_dir

    files = {
        "Trade log": _rel(log_dir / "trade_log.csv"),
        "This run": _rel(run_dir / "trades.csv"),
        "HTML report": _rel(run_dir / "report.html"),
        "Text log": _rel(log_dir / f"run_{run_id}.log"),
    }
    payload = {
        "strategy": result.strategy,
        "data_label": label,
        "skip_reasons": result.skip_reasons,
        "event_counts": result.event_counts,
        "exit_reasons": dict(Counter(t["exit_reason"] for t in result.round_trips)),
        "halted": result.halted,
        "files": files,
    }
    results_store.save_run(run_dir, "btc_backtest", result.metrics, result.equity_curve, config,
                           extra=payload, rows_name="round_trips.csv", rows=result.round_trips,
                           benchmark_curve=result.benchmark_curve)
    full_payload = results_store.load_summary(run_dir)
    dashboard.write_backtest_html(result, full_payload, run_dir / "report.html")
    dashboard.print_summary(full_payload, [v for _, v in result.equity_curve],
                            config["output"]["terminal_chart"])
    return 0


def _choose_btc_for_markets(config, override: Optional[str], first_decision: datetime) -> Tuple[Optional[List[Bar]], str]:
    """Use the configured BTC file if it covers the markets, otherwise the bundled sample."""
    if override:
        path = resolve_path(override)
        return load_ohlcv_csv(path), _rel(path)
    lookback = timedelta(days=config["prediction_markets"]["vol_lookback_days"] + 2)
    candidates = [resolve_path(config["data"]["btc_csv"]), resolve_path(config["data"]["sample_btc_csv"])]
    loaded = []
    for path in candidates:
        if path.exists():
            bars = load_ohlcv_csv(path)
            loaded.append((path, bars))
            if bars[0].timestamp <= first_decision - lookback:
                return bars, _rel(path)
    if loaded:
        path, bars = min(loaded, key=lambda pb: pb[1][0].timestamp)
        log.warning("No BTC file fully covers the markets' dates; markets without history will be skipped.")
        return bars, _rel(path)
    return None, "none"


def cmd_predict(args, config) -> int:
    run_id, log_dir, results_dir = _start_run(config, "prediction_markets")
    print(safety.BANNER)
    markets_path = resolve_path(args.markets or config["data"]["prediction_markets_csv"])
    markets = load_markets_csv(markets_path)
    if not markets:
        raise ValueError(f"{_rel(markets_path)} contains no markets.")
    needs_btc = any(m.my_probability is None for m in markets)
    btc_bars, btc_label = (_choose_btc_for_markets(config, args.btc_csv, markets[0].decision_time)
                           if needs_btc else (None, "not needed"))
    label = f"{_rel(markets_path)} (BTC model data: {btc_label})"
    sample_data = "sample" in markets_path.name
    if sample_data:
        log.warning("Sample markets: outcomes are real BTC history, but market PRICES are simulated.")

    with TradeLogger(run_id, "prediction_markets", log_dir, results_dir) as logger:
        result = run_prediction_backtest(markets, btc_bars, config, logger, data_label=label)
        run_dir = logger.run_dir

    files = {
        "Trade log": _rel(log_dir / "trade_log.csv"),
        "This run": _rel(run_dir / "trades.csv"),
        "HTML report": _rel(run_dir / "report.html"),
        "Text log": _rel(log_dir / f"run_{run_id}.log"),
    }
    payload = {
        "data_label": label,
        "skip_reasons": result.skip_reasons,
        "event_counts": result.event_counts,
        "calibration": result.calibration,
        "halted": result.halted,
        "sample_data": sample_data,
        "files": files,
    }
    results_store.save_run(run_dir, "prediction_markets", result.metrics, result.equity_curve, config,
                           extra=payload, rows_name="bets.csv", rows=result.bets)
    full_payload = results_store.load_summary(run_dir)
    dashboard.write_prediction_html(result, full_payload, run_dir / "report.html")
    dashboard.print_summary(full_payload, [v for _, v in result.equity_curve],
                            config["output"]["terminal_chart"])
    return 0


def cmd_download(args, config) -> int:
    print(safety.BANNER)
    data_cfg = config["data"]
    source = args.source or data_cfg["download_source"]
    granularity = args.granularity or data_cfg["download_granularity"]
    start_text = args.start or data_cfg["download_start"]
    start = datetime.fromisoformat(start_text).replace(tzinfo=timezone.utc)
    if args.out:
        out = resolve_path(args.out)
    elif granularity == "1d":
        out = resolve_path(data_cfg["btc_csv"])
    else:
        out = resolve_path(data_cfg["btc_csv"]).with_name("btc_usd_1h.csv")

    log.info("Downloading %s BTC candles from %s (public, read-only)...", granularity, source)
    try:
        if source == "coinbase":
            bars = downloader.download_coinbase(start, granularity=granularity)
        else:
            bars = downloader.download_kraken(granularity=granularity)
            log.info("Note: Kraken only provides the most recent 720 candles.")
    except (OSError, RuntimeError) as exc:
        other = "kraken" if source == "coinbase" else "coinbase"
        print(f"ERROR: download from {source} failed: {exc}", file=sys.stderr)
        print(f"  Try the other source:  python -m src.main download --source {other}", file=sys.stderr)
        print("  Or save a CSV from any free data site into data/ (format: data/README.md).", file=sys.stderr)
        return 1
    bars = [b for b in bars if b.timestamp >= start]
    if not bars:
        raise ValueError("The download returned no data.")
    save_ohlcv_csv(bars, out)
    print(f"  Saved {len(bars)} bars ({bars[0].timestamp.date()} -> {bars[-1].timestamp.date()}) to {_rel(out)}")
    if granularity == "1h" and not args.out:
        print("  To backtest it:  python -m src.main backtest --csv " + _rel(out))
    return 0


def cmd_make_sample_markets(args, config) -> int:
    print(safety.BANNER)
    csv_path, label = _choose_btc_csv(config, args.btc_csv)
    bars = load_ohlcv_csv(csv_path)
    out = resolve_path(args.out or config["data"]["prediction_markets_csv"])
    count = make_sample_markets(bars, out, seed=args.seed)
    print(f"  Wrote {count} sample markets to {_rel(out)} (from {label}).")
    print("  Outcomes come from real BTC closes; market PRICES are simulated.")
    return 0


def cmd_summary(args, config) -> int:
    results_dir = resolve_path(config["output"]["results_dir"])
    run_dir = results_dir / args.run if args.run else results_store.latest_run_dir(results_dir)
    if run_dir is None or not (run_dir / results_store.SUMMARY_FILE).exists():
        raise FileNotFoundError("No saved runs yet. Try:  python -m src.main backtest")
    payload = results_store.load_summary(run_dir)
    equity_values = _read_equity(run_dir / "equity_curve.csv")
    dashboard.print_summary(payload, equity_values, config["output"]["terminal_chart"])
    return 0


def _read_equity(path: Path) -> List[float]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [float(row["equity"]) for row in csv.DictReader(handle)]


def cmd_live(args, config) -> int:
    safety.refuse_live_execution()


COMMANDS: Dict[str, Any] = {
    "check": cmd_check,
    "backtest": cmd_backtest,
    "predict": cmd_predict,
    "download": cmd_download,
    "make-sample-markets": cmd_make_sample_markets,
    "summary": cmd_summary,
    "live": cmd_live,
}


if __name__ == "__main__":
    sys.exit(main())
