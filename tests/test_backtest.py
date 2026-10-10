from __future__ import annotations

import csv
import unittest
from datetime import timedelta
from pathlib import Path

from src.backtest import run_backtest
from src.config import DEFAULTS, resolve_path
from src.data_loader import Bar, load_ohlcv_csv
from src.trade_logger import TradeLogger
from tests.helpers import bars_from_closes, make_config, temp_dir

SAMPLE = load_ohlcv_csv(resolve_path(DEFAULTS["data"]["sample_btc_csv"]))


class BacktestTests(unittest.TestCase):
    def run_bt(self, bars, **section_overrides):
        tmp = temp_dir(self)
        config = make_config(tmp)
        for section, values in section_overrides.items():
            config[section].update(values)
        with TradeLogger("test_run", "btc_backtest", tmp / "logs", tmp / "results") as logger:
            result = run_backtest(bars, config, logger, data_label="test")
        return result, self.read_rows(tmp / "results" / "test_run" / "trades.csv"), tmp

    @staticmethod
    def read_rows(path: Path):
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_every_strategy_runs_and_books_add_up(self):
        for name in ("sma_crossover", "rsi_mean_reversion", "donchian_breakout"):
            with self.subTest(strategy=name):
                result, rows, _ = self.run_bt(SAMPLE, strategy={"name": name})
                m = result.metrics
                self.assertEqual(len(result.equity_curve), len(SAMPLE))
                # Final equity = starting cash + every trade's profit or loss.
                self.assertAlmostEqual(m["end_equity"], m["start_equity"] + sum(t["pnl"] for t in result.round_trips),
                                       places=6)
                entries = [r for r in rows if r["event"] == "ENTRY"]
                exits = [r for r in rows if r["event"] == "EXIT"]
                self.assertEqual(len(entries), len(exits))
                self.assertEqual(len(exits), m["trades"])

    def test_losses_and_wins_are_both_logged(self):
        result, rows, _ = self.run_bt(SAMPLE, strategy={"name": "donchian_breakout"})
        pnls = [float(r["pnl"]) for r in rows if r["event"] == "EXIT"]
        self.assertTrue(any(p < 0 for p in pnls))
        self.assertTrue(any(p > 0 for p in pnls))

    def test_volatility_filter_skips_are_logged_with_reasons(self):
        result, rows, _ = self.run_bt(SAMPLE, volatility_filter={"max_annual_vol_pct": 2, "min_annual_vol_pct": 1})
        skips = [r for r in rows if r["event"] == "SKIP"]
        self.assertEqual(result.metrics["trades"], 0)
        self.assertGreater(len(skips), 0)
        self.assertTrue(all(r["reason"] == "volatility_too_high" for r in skips))
        self.assertTrue(all(r["details"] for r in skips))

    def test_master_log_is_appended_across_runs(self):
        tmp = temp_dir(self)
        config = make_config(tmp)
        for run in ("run_a", "run_b"):
            with TradeLogger(run, "btc_backtest", tmp / "logs", tmp / "results") as logger:
                run_backtest(SAMPLE[:400], config, logger)
        run_ids = {r["run_id"] for r in self.read_rows(tmp / "logs" / "trade_log.csv")}
        self.assertEqual(run_ids, {"run_a", "run_b"})

    def test_stop_loss_fills_at_open_when_price_gaps_below_stop(self):
        # Steady climb (breakout entry), then a bar that OPENS far below any stop.
        bars = bars_from_closes([100 + i for i in range(40)], spread=0.001)
        gap_time = bars[-1].timestamp + timedelta(days=1)
        bars += [Bar(gap_time, 60, 61, 59, 60), Bar(gap_time + timedelta(days=1), 60, 61, 59, 60)]
        result, rows, _ = self.run_bt(
            bars, strategy={"name": "donchian_breakout"},
            volatility_filter={"enabled": False, "lookback_bars": 5, "atr_period": 5},
            risk={"trailing_stop": False, "stop_loss_atr_multiple": 5})
        last = result.round_trips[-1]
        self.assertEqual(last["exit_reason"], "stop_loss")
        self.assertEqual(last["exit_time"], gap_time.isoformat())
        self.assertLess(last["exit_price"], 60)  # filled at the gap open (minus slippage), not at the stop

    def test_kill_switch_halts_and_logs(self):
        closes = [100 + i for i in range(40)] + [100 - 3 * i for i in range(25)] + [30 + i for i in range(60)]
        bars = bars_from_closes(closes, spread=0.001)
        result, rows, _ = self.run_bt(
            bars, strategy={"name": "donchian_breakout"},
            volatility_filter={"enabled": False, "lookback_bars": 5, "atr_period": 5},
            risk={"max_drawdown_pct": 1, "risk_per_trade_pct": 5, "trailing_stop": False,
                  "stop_loss_atr_multiple": 20, "max_position_pct": 100})
        self.assertTrue(result.halted)
        self.assertEqual(sum(1 for r in rows if r["event"] == "HALT"), 1)
        halt_index = next(i for i, r in enumerate(rows) if r["event"] == "HALT")
        self.assertFalse(any(r["event"] == "ENTRY" for r in rows[halt_index:]))


if __name__ == "__main__":
    unittest.main()
