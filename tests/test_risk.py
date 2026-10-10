from __future__ import annotations

import unittest
from datetime import date

from src.config import DEFAULTS
from src.risk import RiskManager, binary_bet_stake, kelly_fraction_binary


def manager(**overrides) -> RiskManager:
    return RiskManager(dict(DEFAULTS["risk"], **overrides), starting_equity=10_000)


class SizingTests(unittest.TestCase):
    def test_loss_at_stop_equals_risk_per_trade(self):
        rm = manager(risk_per_trade_pct=1.0, stop_loss_atr_multiple=2.0, max_position_pct=100)
        d = rm.size_position(equity=10_000, cash=10_000, entry_price=1_000, atr=25, fee_pct=0)
        self.assertTrue(d.approved)
        self.assertAlmostEqual(d.stop_price, 950)
        self.assertAlmostEqual(d.quantity * (1_000 - d.stop_price), 100)  # 1% of 10k

    def test_position_capped_by_max_position_pct(self):
        rm = manager(max_position_pct=10)
        d = rm.size_position(10_000, 10_000, entry_price=1_000, atr=1, fee_pct=0)
        self.assertAlmostEqual(d.notional, 1_000)

    def test_position_capped_by_cash_including_fee(self):
        rm = manager(max_position_pct=100)
        d = rm.size_position(10_000, cash=500, entry_price=1_000, atr=1, fee_pct=1.0)
        self.assertLessEqual(d.notional * 1.01, 500 + 1e-9)

    def test_tiny_trade_is_rejected(self):
        rm = manager(min_trade_usd=25)
        d = rm.size_position(10_000, cash=20, entry_price=1_000, atr=10, fee_pct=0.1)
        self.assertFalse(d.approved)
        self.assertEqual(d.reason, "size_too_small")

    def test_take_profit_only_when_enabled(self):
        self.assertIsNone(manager(take_profit_atr_multiple=0).size_position(10_000, 10_000, 100, 5, 0).take_profit_price)
        self.assertAlmostEqual(manager(take_profit_atr_multiple=3).size_position(10_000, 10_000, 100, 5, 0)
                               .take_profit_price, 115)

    def test_trailing_stop_only_moves_up(self):
        rm = manager(stop_loss_atr_multiple=2, trailing_stop=True)
        self.assertEqual(rm.trail_stop(90, close=120, atr=5), 110)
        self.assertEqual(rm.trail_stop(110, close=100, atr=5), 110)
        self.assertEqual(manager(trailing_stop=False).trail_stop(90, close=120, atr=5), 90)


class AccountLimitTests(unittest.TestCase):
    def test_daily_loss_limit_blocks_until_next_day(self):
        rm = manager(max_daily_loss_pct=3)
        rm.start_bar(date(2020, 1, 1), 10_000)
        self.assertEqual(rm.can_open_trade(9_650), (False, "daily_loss_limit"))
        rm.start_bar(date(2020, 1, 2), 9_650)
        self.assertTrue(rm.can_open_trade(9_650)[0])

    def test_max_trades_per_day(self):
        rm = manager(max_trades_per_day=1)
        rm.start_bar(date(2020, 1, 1), 10_000)
        rm.record_entry()
        self.assertEqual(rm.can_open_trade(10_000), (False, "max_trades_per_day"))

    def test_drawdown_kill_switch_trips_once_and_stays_on(self):
        rm = manager(max_drawdown_pct=20)
        self.assertFalse(rm.update_equity(12_000))
        self.assertTrue(rm.update_equity(9_600))  # 20% below the 12k peak
        self.assertFalse(rm.update_equity(9_000))  # already tripped, not reported again
        self.assertEqual(rm.can_open_trade(50_000), (False, "max_drawdown_halt"))


class KellyTests(unittest.TestCase):
    def test_kelly_formula(self):
        self.assertAlmostEqual(kelly_fraction_binary(0.6, 0.5), 0.2)
        self.assertEqual(kelly_fraction_binary(0.4, 0.5), 0.0)
        self.assertEqual(kelly_fraction_binary(0.9, 1.0), 0.0)

    def test_stake_is_capped(self):
        stake = binary_bet_stake(1_000, 0.9, 0.5, kelly_fraction=1.0, max_stake_pct=2, exposure_room=1e9)
        self.assertAlmostEqual(stake, 20)
        stake = binary_bet_stake(1_000, 0.9, 0.5, kelly_fraction=1.0, max_stake_pct=50, exposure_room=7)
        self.assertAlmostEqual(stake, 7)


if __name__ == "__main__":
    unittest.main()
