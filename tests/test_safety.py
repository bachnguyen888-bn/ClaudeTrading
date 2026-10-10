"""The most important tests: the project must refuse anything but paper mode."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from src import safety
from src.config import DEFAULTS, PROJECT_ROOT
from src.main import main
from src.paper_broker import PaperBroker
from tests.helpers import temp_dir

SRC = PROJECT_ROOT / "src"
NETWORK_MODULES = {"urllib", "http", "socket", "requests", "httpx", "aiohttp", "websocket", "websockets"}


def run_cli(*args: str) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(list(args))


class RefuseLiveTests(unittest.TestCase):
    def test_refuse_live_execution_always_raises(self):
        with self.assertRaises(safety.LiveTradingRefused):
            safety.refuse_live_execution()

    def test_live_command_refuses_with_exit_code_2(self):
        self.assertEqual(run_cli("live"), 2)

    def test_non_paper_mode_in_config_is_refused(self):
        for mode in ("live", "real", "LIVE", "", None):
            with self.subTest(mode=mode), self.assertRaises(safety.LiveTradingRefused):
                safety.check_config_mode({"mode": mode})

    def test_paper_mode_is_accepted(self):
        safety.check_config_mode(dict(DEFAULTS))

    def test_live_trading_flag_is_refused(self):
        with self.assertRaises(safety.LiveTradingRefused):
            safety.check_config_mode({"mode": "paper", "live_trading": True})

    def test_credentials_in_config_are_refused(self):
        config = {"mode": "paper", "data": {"exchange": {"wallet_private_key": "abc"}}}
        with self.assertRaises(safety.LiveTradingRefused):
            safety.check_config_mode(config)

    def test_cli_refuses_config_with_live_mode(self):
        tmp = temp_dir(self)
        config = dict(DEFAULTS, mode="live")
        path = tmp / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(run_cli("--config", str(path), "check"), 2)

    def test_trading_mode_env_must_be_paper(self):
        with self.assertRaises(safety.LiveTradingRefused):
            safety.check_environment({}, {"TRADING_MODE": "live"})
        safety.check_environment({}, {"TRADING_MODE": "paper"})
        safety.check_environment({}, {})  # unset defaults to paper

    def test_wallet_keys_in_env_file_are_refused(self):
        for name in ("WALLET_PRIVATE_KEY", "PRIVATE_KEY", "MNEMONIC", "SEED_PHRASE", "POLYMARKET_WALLET"):
            with self.subTest(name=name), self.assertRaises(safety.LiveTradingRefused):
                safety.check_environment({name: "0xdeadbeef"}, {})

    def test_empty_placeholders_and_data_keys_are_fine(self):
        safety.check_environment({"WALLET_PRIVATE_KEY": "", "DATA_API_KEY": "read-only"}, {})

    def test_imported_live_trading_library_is_refused(self):
        with mock.patch.dict(sys.modules, {"ccxt": types.ModuleType("ccxt")}):
            with self.assertRaises(safety.LiveTradingRefused):
                safety.check_no_live_libraries()

    def test_broker_refuses_if_paper_flag_is_changed(self):
        with mock.patch.object(safety, "PAPER_MODE_ONLY", False):
            with self.assertRaises(safety.LiveTradingRefused):
                PaperBroker(1000, 0.1, 0.05)


class SourceCodeGuardrailTests(unittest.TestCase):
    """Scan the source so nobody quietly adds an order-sending library."""

    def imports_by_file(self):
        for path in sorted(SRC.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names.add(node.module.split(".")[0])
            yield path, names

    def test_no_live_trading_libraries_imported(self):
        for path, names in self.imports_by_file():
            with self.subTest(file=path.name):
                self.assertFalse(names & set(safety.FORBIDDEN_MODULES))

    def test_only_the_read_only_downloader_touches_the_network(self):
        for path, names in self.imports_by_file():
            if path.name == "downloader.py":
                continue
            with self.subTest(file=path.name):
                self.assertFalse(names & NETWORK_MODULES, f"{path.name} imports network modules")

    def test_downloader_only_sends_get_requests(self):
        source = (SRC / "downloader.py").read_text(encoding="utf-8")
        self.assertNotIn('method="POST"', source)
        self.assertNotIn("Authorization", source)


if __name__ == "__main__":
    unittest.main()
