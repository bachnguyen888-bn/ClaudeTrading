from __future__ import annotations

import csv
import unittest
from datetime import datetime, timedelta, timezone

from src.config import DEFAULTS, resolve_path
from src.data_loader import load_ohlcv_csv
from src.prediction_market import (BtcThresholdModel, Market, load_markets_csv, prob_above_strike,
                                   run_prediction_backtest)
from src.trade_logger import TradeLogger
from tests.helpers import bars_from_closes, make_config, temp_dir

T0 = datetime(2021, 1, 1, tzinfo=timezone.utc)


def market(mid, yes_price, my_p, outcome, day=0, days=7):
    return Market(mid, f"Question {mid}?", T0 + timedelta(days=day), T0 + timedelta(days=day + days),
                  yes_price, outcome, None, my_p)


class PredictionMarketTests(unittest.TestCase):
    def run_pm(self, markets, btc_bars=None, **overrides):
        tmp = temp_dir(self)
        config = make_config(tmp)
        config["prediction_markets"].update(overrides)
        with TradeLogger("pm_test", "prediction_markets", tmp / "logs", tmp / "results") as logger:
            result = run_prediction_backtest(markets, btc_bars, config, logger)
        with (tmp / "results" / "pm_test" / "trades.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return result, rows

    def test_bets_yes_no_and_skips_with_own_probabilities(self):
        markets = [
            market("cheap_yes", 0.30, 0.60, outcome=1),  # big YES edge -> bet YES, wins
            market("fair", 0.50, 0.52, outcome=0),  # tiny edge -> skip
            market("rich_yes", 0.80, 0.40, outcome=1),  # big NO edge -> bet NO, loses
        ]
        result, rows = self.run_pm(markets, price_slippage=0.0, fee_per_contract=0.0)
        bets = {r["market"]: r for r in rows if r["event"] == "BET"}
        self.assertEqual(bets["cheap_yes"]["side"], "YES")
        self.assertEqual(bets["rich_yes"]["side"], "NO")
        skips = [r for r in rows if r["event"] == "SKIP"]
        self.assertEqual([(r["market"], r["reason"]) for r in skips], [("fair", "edge_too_small")])

        resolves = {r["market"]: r for r in rows if r["event"] == "RESOLVE"}
        self.assertEqual(resolves["cheap_yes"]["reason"], "WIN")
        self.assertEqual(resolves["rich_yes"]["reason"], "LOSS")
        # Money is conserved: bankroll change equals the sum of settled bet P&L.
        m = result.metrics
        self.assertAlmostEqual(m["end_equity"] - m["start_equity"], sum(b["pnl"] for b in result.bets), places=9)

    def test_winning_contract_pays_one_dollar(self):
        result, _ = self.run_pm([market("a", 0.30, 0.70, outcome=1)], price_slippage=0.0, fee_per_contract=0.0)
        bet = result.bets[0]
        self.assertAlmostEqual(bet["payout"], bet["contracts"] * 1.0)
        self.assertAlmostEqual(bet["pnl"], bet["contracts"] * (1 - 0.30))

    def test_stake_respects_max_stake_pct(self):
        result, _ = self.run_pm([market("a", 0.10, 0.90, outcome=1)], max_stake_pct=2.0)
        self.assertLessEqual(result.bets[0]["cost"], 1000 * 0.02 + 1e-9)

    def test_price_band_filter(self):
        _, rows = self.run_pm([market("longshot", 0.02, 0.50, outcome=0)])
        self.assertEqual(rows[0]["reason"], "price_out_of_range")

    def test_exposure_limit(self):
        markets = [market(f"m{i}", 0.30, 0.70, outcome=1, day=0) for i in range(30)]
        result, rows = self.run_pm(markets, max_stake_pct=5.0, max_total_exposure_pct=10.0)
        self.assertIn("max_total_exposure", {r["reason"] for r in rows if r["event"] == "SKIP"})

    def test_probability_model(self):
        self.assertAlmostEqual(prob_above_strike(100, 100, 0.0001, 7 / 365), 0.5, places=3)
        self.assertGreater(prob_above_strike(150, 100, 0.6, 7 / 365), 0.99)
        self.assertLess(prob_above_strike(50, 100, 0.6, 7 / 365), 0.01)

    def test_model_uses_only_completed_bars(self):
        bars = bars_from_closes([100 + i for i in range(60)], start=T0)
        model = BtcThresholdModel(bars, vol_lookback_days=10)
        # Decision at the START of day 40: day 40's close isn't known yet, so spot is day 39's close.
        m = Market("x", "", T0 + timedelta(days=40), T0 + timedelta(days=47), 0.5, 1, strike=140.0)
        _, details, problem = model.estimate(m)
        self.assertEqual(problem, "")
        self.assertEqual(details["spot"], 139)

    def test_sample_dataset_runs_end_to_end(self):
        markets = load_markets_csv(resolve_path(DEFAULTS["data"]["prediction_markets_csv"]))
        btc = load_ohlcv_csv(resolve_path(DEFAULTS["data"]["sample_btc_csv"]))
        result, rows = self.run_pm(markets, btc)
        decided = {r["market"] for r in rows if r["event"] in ("BET", "SKIP")}
        self.assertEqual(len(decided), len(markets))  # every market gets a logged decision
        self.assertGreater(result.metrics["bets"], 0)
        self.assertEqual(result.metrics["forecasts_scored"], len(markets))

    def test_csv_validation(self):
        path = temp_dir(self) / "m.csv"
        path.write_text("market_id,decision_time,resolve_time,yes_price,outcome\n"
                        "a,2021-01-01,2021-01-08,1.5,1\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_markets_csv(path)
        self.assertIn("yes_price", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
