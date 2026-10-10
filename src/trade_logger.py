"""
Trade logging. EVERY simulated decision gets a row: entries, exits (wins and
losses), bets, resolutions, kill-switch halts, and skipped trades with the
reason they were skipped.

Where it goes:
  logs/trade_log.csv            - master log, appended across all runs
  results/<run_id>/trades.csv   - just this run
  logs/run_<run_id>.log         - human-readable text log (see setup_logging)

Rows are written and flushed immediately, so a crash never loses history.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

COLUMNS = [
    "run_id", "experiment", "event", "timestamp", "market", "side", "reason",
    "price", "quantity", "notional", "fee", "pnl", "pnl_pct",
    "cash_after", "equity_after", "details",
]

# Event types
ENTRY, EXIT, SKIP, HALT, BET, RESOLVE = "ENTRY", "EXIT", "SKIP", "HALT", "BET", "RESOLVE"

log = logging.getLogger(__name__)


def new_run_id(experiment: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3] + f"_{experiment}"


def setup_logging(log_dir: Path, run_id: str, level: str = "INFO") -> Path:
    """Console logging plus a per-run text file in logs/."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{run_id}.log"
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level))
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    root.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(file_handler)
    return log_path


class TradeLogger:
    def __init__(self, run_id: str, experiment: str, log_dir: Path, results_dir: Path):
        self.run_id = run_id
        self.experiment = experiment
        self.rows: List[Dict[str, Any]] = []
        self.counts: Counter = Counter()
        self.skip_reasons: Counter = Counter()

        log_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir = results_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.master_path = log_dir / "trade_log.csv"
        self._rotate_if_old_format(self.master_path)
        master_is_new = not self.master_path.exists()
        self._master_file = self.master_path.open("a", newline="", encoding="utf-8")
        self._master = csv.DictWriter(self._master_file, fieldnames=COLUMNS)
        if master_is_new:
            self._master.writeheader()

        self.run_path = self.run_dir / "trades.csv"
        self._run_file = self.run_path.open("w", newline="", encoding="utf-8")
        self._run = csv.DictWriter(self._run_file, fieldnames=COLUMNS)
        self._run.writeheader()

    @staticmethod
    def _rotate_if_old_format(path: Path) -> None:
        """If the master log was written by an older version with different columns, set it aside."""
        if not path.exists():
            return
        with path.open(encoding="utf-8") as handle:
            header = handle.readline().strip()
        if header and header != ",".join(COLUMNS):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path.rename(path.with_name(f"trade_log_old_{stamp}.csv"))

    def log(self, event: str, timestamp: datetime, market: str, side: str = "", reason: str = "",
            price: Optional[float] = None, quantity: Optional[float] = None,
            notional: Optional[float] = None, fee: Optional[float] = None,
            pnl: Optional[float] = None, pnl_pct: Optional[float] = None,
            cash_after: Optional[float] = None, equity_after: Optional[float] = None,
            details: Optional[Dict[str, Any]] = None) -> None:
        row = {
            "run_id": self.run_id,
            "experiment": self.experiment,
            "event": event,
            "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "market": market,
            "side": side,
            "reason": reason,
            "price": _fmt(price, 6),
            "quantity": _fmt(quantity, 8),
            "notional": _fmt(notional, 2),
            "fee": _fmt(fee, 4),
            "pnl": _fmt(pnl, 2),
            "pnl_pct": _fmt(pnl_pct, 3),
            "cash_after": _fmt(cash_after, 2),
            "equity_after": _fmt(equity_after, 2),
            "details": json.dumps(details, sort_keys=True) if details else "",
        }
        self.rows.append(row)
        self.counts[event] += 1
        if event == SKIP:
            self.skip_reasons[reason] += 1
        for writer, handle in ((self._master, self._master_file), (self._run, self._run_file)):
            writer.writerow(row)
            handle.flush()

        text = f"[{row['timestamp']}] {event:<7} {market} {side} {reason}"
        if pnl is not None:
            text += f" pnl={pnl:+.2f}"
        log.debug(text)

    def close(self) -> None:
        for handle in (self._master_file, self._run_file):
            if not handle.closed:
                handle.close()

    def __enter__(self) -> "TradeLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _fmt(value: Optional[float], decimals: int) -> str:
    return "" if value is None else f"{value:.{decimals}f}"
