"""
Save each run's outputs to results/<run_id>/ so you can compare runs later.

  summary.json      - headline numbers (read back by `python -m src.main summary`)
  equity_curve.csv  - account value over time
  config_used.json  - the exact settings this run used
  round_trips.csv   - (BTC backtest) one row per completed trade
  bets.csv          - (prediction markets) one row per settled bet
  trades.csv        - every logged event (written live by trade_logger.py)
  report.html       - the visual dashboard (written by dashboard.py)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SUMMARY_FILE = "summary.json"


def save_run(run_dir: Path, experiment: str, summary: Dict[str, Any], equity_curve, config: Dict[str, Any],
             extra: Optional[Dict[str, Any]] = None, rows_name: str = "", rows: Optional[List[Dict]] = None,
             benchmark_curve=None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": run_dir.name, "experiment": experiment, "metrics": summary}
    payload.update(extra or {})
    (run_dir / SUMMARY_FILE).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (run_dir / "config_used.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    with (run_dir / "equity_curve.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        header = ["timestamp", "equity"] + (["buy_and_hold"] if benchmark_curve else [])
        writer.writerow(header)
        for k, (ts, value) in enumerate(equity_curve):
            row = [ts.strftime("%Y-%m-%dT%H:%M:%SZ"), f"{value:.2f}"]
            if benchmark_curve:
                row.append(f"{benchmark_curve[k][1]:.2f}")
            writer.writerow(row)

    if rows_name:
        with (run_dir / rows_name).open("w", newline="", encoding="utf-8") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)


def latest_run_dir(results_dir: Path) -> Optional[Path]:
    """Run ids start with a UTC timestamp, so the newest sorts last."""
    if not results_dir.exists():
        return None
    runs = sorted(p for p in results_dir.iterdir() if (p / SUMMARY_FILE).exists())
    return runs[-1] if runs else None


def load_summary(run_dir: Path) -> Dict[str, Any]:
    return json.loads((run_dir / SUMMARY_FILE).read_text(encoding="utf-8"))
