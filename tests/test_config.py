from __future__ import annotations

import json
import unittest

from src.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from tests.helpers import temp_dir


class ConfigTests(unittest.TestCase):
    def write(self, data) -> str:
        path = temp_dir(self) / "config.json"
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return str(path)

    def test_shipped_config_is_valid_and_has_no_typos(self):
        config, warnings = load_config(DEFAULT_CONFIG_PATH)
        self.assertEqual(config["mode"], "paper")
        self.assertEqual(warnings, [])

    def test_missing_settings_fall_back_to_defaults(self):
        config, _ = load_config(self.write({"mode": "paper", "risk": {"risk_per_trade_pct": 0.5}}))
        self.assertEqual(config["risk"]["risk_per_trade_pct"], 0.5)
        self.assertEqual(config["risk"]["max_drawdown_pct"], 20.0)

    def test_out_of_range_value_explains_itself(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write({"mode": "paper", "risk": {"risk_per_trade_pct": 50}}))
        self.assertIn("risk.risk_per_trade_pct", str(ctx.exception))
        self.assertIn("at most", str(ctx.exception))

    def test_wrong_type_is_reported(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write({"mode": "paper", "volatility_filter": {"enabled": "yes"}}))
        self.assertIn("true or false", str(ctx.exception))

    def test_unknown_key_produces_warning(self):
        _, warnings = load_config(self.write({"mode": "paper", "risk": {"risk_per_trade": 1}}))
        self.assertTrue(any("risk.risk_per_trade" in w for w in warnings))

    def test_comment_keys_are_ignored(self):
        _, warnings = load_config(self.write({"_note": "hello", "mode": "paper"}))
        self.assertEqual(warnings, [])

    def test_invalid_json_gives_friendly_hint(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write('{"mode": "paper",}'))
        self.assertIn("trailing comma", str(ctx.exception))

    def test_cross_field_checks(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write({"mode": "paper",
                                    "strategy": {"sma_crossover": {"fast_period": 50, "slow_period": 20}}}))
        self.assertIn("fast_period must be smaller", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
