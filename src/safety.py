"""
Paper-mode safety guard.

This project is a PAPER-TRADING simulator. It contains no code that can place
real orders, sign transactions, or talk to a wallet. This module exists so
that nobody can accidentally point it at real money, either.

There is deliberately NO config switch or environment variable that turns
live trading on. Every check below refuses anything other than paper mode.
To trade live you would have to rewrite this project yourself.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping, NoReturn, Optional

# Hard-coded on purpose. Nothing reads this from config or .env.
PAPER_MODE_ONLY = True

ALLOWED_MODE = "paper"

# A paper simulator never needs a wallet key or seed phrase. If one of these
# shows up in .env, we stop rather than risk it being used or leaked.
FORBIDDEN_SECRET_MARKERS = ("PRIVATE_KEY", "MNEMONIC", "SEED_PHRASE", "WALLET")

# Keys that must never appear in config.json.
FORBIDDEN_CONFIG_MARKERS = ("private_key", "mnemonic", "seed_phrase", "wallet", "api_secret")

# Libraries whose job is placing real orders or signing transactions.
# If any of them gets imported into this process, we stop.
FORBIDDEN_MODULES = (
    "ccxt",
    "web3",
    "eth_account",
    "py_clob_client",
    "kalshi_python",
    "alpaca_trade_api",
    "binance",
    "coinbase",
    "krakenex",
    "solana",
    "solders",
)

BANNER = (
    "==============================================================\n"
    "  PAPER MODE ONLY - simulated trades, no real money, no orders\n"
    "=============================================================="
)


class LiveTradingRefused(RuntimeError):
    """Raised whenever anything tries to leave paper mode."""


def refuse_live_execution(reason: str = "") -> NoReturn:
    """Always raises. This is the only answer to 'please trade live'."""
    message = (
        "LIVE EXECUTION REFUSED.\n"
        "This project is a paper-trading simulator only. It has no code that\n"
        "can send real orders or connect a wallet, and no setting enables one.\n"
        "To trade live you would need to deliberately rewrite the project."
    )
    if reason:
        message += f"\nReason: {reason}"
    raise LiveTradingRefused(message)


def assert_paper_mode() -> None:
    """Defense in depth: simulated components call this when they are created."""
    if PAPER_MODE_ONLY is not True:
        refuse_live_execution("PAPER_MODE_ONLY was changed in src/safety.py.")


def check_config_mode(config: Mapping) -> None:
    mode = config.get("mode")
    if mode != ALLOWED_MODE:
        refuse_live_execution(
            f'config.json has "mode": {mode!r}. The only allowed value is "paper".'
        )
    if config.get("live_trading"):
        refuse_live_execution('config.json has "live_trading" turned on.')
    _check_config_for_secrets(config, path="")


def _check_config_for_secrets(node, path: str) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if any(marker in lowered for marker in FORBIDDEN_CONFIG_MARKERS):
                refuse_live_execution(
                    f"config.json contains '{key_path}'. Credentials never belong in "
                    "config.json, and this paper project never needs wallet keys."
                )
            _check_config_for_secrets(value, key_path)


def check_environment(env_file_values: Mapping[str, str], environ: Optional[Mapping[str, str]] = None) -> None:
    """Check TRADING_MODE and make sure .env holds no wallet keys."""
    environ = os.environ if environ is None else environ
    trading_mode = environ.get("TRADING_MODE", ALLOWED_MODE).strip().lower()
    if trading_mode != ALLOWED_MODE:
        refuse_live_execution(
            f"TRADING_MODE is set to {trading_mode!r}. The only allowed value is 'paper'."
        )
    for name, value in env_file_values.items():
        if value and any(marker in name.upper() for marker in FORBIDDEN_SECRET_MARKERS):
            refuse_live_execution(
                f".env contains {name}. A paper simulator never needs a wallet key or "
                "seed phrase. Delete it from .env (and keep it somewhere safe offline)."
            )


def check_no_live_libraries() -> None:
    loaded = sorted(name for name in FORBIDDEN_MODULES if name in sys.modules)
    if loaded:
        refuse_live_execution(
            f"live-trading libraries were imported: {', '.join(loaded)}."
        )


def enforce_paper_mode(config: Mapping, env_file_values: Mapping[str, str]) -> None:
    """Run every check. Called at the start of every command."""
    assert_paper_mode()
    check_config_mode(config)
    check_environment(env_file_values)
    check_no_live_libraries()
