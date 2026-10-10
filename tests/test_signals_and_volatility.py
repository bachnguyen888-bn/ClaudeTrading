from __future__ import annotations

import math
import unittest

from src import indicators
from src.config import DEFAULTS
from src.data_loader import load_ohlcv_csv
from src.config import resolve_path
from src.signals import BUY, HOLD, SELL, DonchianBreakout, RsiMeanReversion, SmaCrossover
from src.volatility import VolatilityFilter, vol_band_check
from tests.helpers import bars_from_closes

SAMPLE = load_ohlcv_csv(resolve_path(DEFAULTS["data"]["sample_btc_csv"]))


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(indicators.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_rsi_stays_between_0_and_100(self):
        values = [v for v in indicators.rsi([b.close for b in SAMPLE], 14) if v is not None]
        self.assertTrue(all(0 <= v <= 100 for v in values))

    def test_rsi_of_only_rises_is_100(self):
        self.assertEqual(indicators.rsi(list(range(1, 30)), 14)[-1], 100.0)

    def test_highest_excludes_current_bar(self):
        self.assertEqual(indicators.highest([1, 5, 2, 9], 2), [None, None, 5, 5])

    def test_realized_vol_of_steady_growth_is_zero(self):
        closes = [100 * 1.01 ** i for i in range(40)]
        self.assertAlmostEqual(indicators.realized_volatility(closes, 20, 365)[-1], 0.0, places=9)

    def test_realized_vol_matches_alternating_moves(self):
        closes = [100.0]
        for i in range(60):
            closes.append(closes[-1] * (1.02 if i % 2 == 0 else 1 / 1.02))
        vol = indicators.realized_volatility(closes, 20, 365)[-1]
        self.assertAlmostEqual(vol, math.log(1.02) * math.sqrt(20 / 19) * math.sqrt(365), places=6)


class SignalTests(unittest.TestCase):
    def test_sma_crossover_detects_both_crosses(self):
        closes = [10] * 10 + [20] * 10 + [5] * 10
        strategy = SmaCrossover(2, 5)
        strategy.prepare(bars_from_closes(closes))
        actions = [strategy.signal_at(i).action for i in range(len(closes))]
        self.assertEqual(actions.count(BUY), 1)
        self.assertEqual(actions.count(SELL), 1)
        self.assertLess(actions.index(BUY), actions.index(SELL))

    def test_no_lookahead(self):
        """A signal at bar k must be identical whether or not later bars exist."""
        strategies = [SmaCrossover(20, 50), RsiMeanReversion(14, 30, 55), DonchianBreakout(20, 10)]
        full = SAMPLE[:400]
        for strategy in strategies:
            strategy.prepare(full)
            expected = {k: strategy.signal_at(k) for k in range(60, 400, 7)}
            for k, signal in expected.items():
                truncated = type(strategy)(*self._params(strategy))
                truncated.prepare(full[:k + 1])
                with self.subTest(strategy=strategy.name, k=k):
                    self.assertEqual(truncated.signal_at(k), signal)

    @staticmethod
    def _params(strategy):
        if isinstance(strategy, SmaCrossover):
            return strategy.fast_period, strategy.slow_period
        if isinstance(strategy, RsiMeanReversion):
            return strategy.period, strategy.buy_below, strategy.sell_above
        return strategy.entry_lookback, strategy.exit_lookback

    def test_warmup_returns_hold(self):
        strategy = DonchianBreakout(20, 10)
        strategy.prepare(SAMPLE[:30])
        self.assertEqual(strategy.signal_at(5).action, HOLD)


class VolatilityFilterTests(unittest.TestCase):
    def make(self, **overrides):
        cfg = dict(DEFAULTS["volatility_filter"], **overrides)
        f = VolatilityFilter(cfg, 365)
        f.prepare(SAMPLE)
        return f

    def test_blocks_when_too_volatile(self):
        check = self.make(max_annual_vol_pct=1, min_annual_vol_pct=0).check(300)
        self.assertFalse(check.allowed)
        self.assertEqual(check.reason, "volatility_too_high")

    def test_blocks_when_too_quiet(self):
        check = self.make(min_annual_vol_pct=999, max_annual_vol_pct=1000).check(300)
        self.assertEqual(check.reason, "volatility_too_low")

    def test_disabled_filter_allows_but_still_reports_atr(self):
        check = self.make(enabled=False).check(300)
        self.assertTrue(check.allowed)
        self.assertGreater(check.atr, 0)

    def test_not_ready_during_warmup(self):
        self.assertEqual(self.make().check(3).reason, "volatility_not_ready")

    def test_band_helper(self):
        self.assertEqual(vol_band_check(50, 10, 100), "")
        self.assertEqual(vol_band_check(150, 10, 100), "volatility_too_high")
        self.assertEqual(vol_band_check(None, 10, 100), "volatility_not_ready")


if __name__ == "__main__":
    unittest.main()
