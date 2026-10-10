"""Shared test helpers: temp output folders and synthetic price data."""

from __future__ import annotations

import copy
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Sequence

from src.config import DEFAULTS
from src.data_loader import Bar


def make_config(tmp: Path) -> dict:
    """Default config with logs/results redirected into a temp folder."""
    config = copy.deepcopy(DEFAULTS)
    config["output"]["log_dir"] = str(tmp / "logs")
    config["output"]["results_dir"] = str(tmp / "results")
    config["output"]["log_level"] = "ERROR"
    return config


def temp_dir(case) -> Path:
    handle = tempfile.TemporaryDirectory()
    case.addCleanup(handle.cleanup)
    return Path(handle.name)


def bars_from_closes(closes: Sequence[float], start: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc),
                     spread: float = 0.01) -> List[Bar]:
    """Daily bars whose open is the previous close and high/low sit `spread` around the range."""
    bars = []
    prev = closes[0]
    for i, close in enumerate(closes):
        high = max(prev, close) * (1 + spread)
        low = min(prev, close) * (1 - spread)
        bars.append(Bar(start + timedelta(days=i), prev, high, low, close, 1.0))
        prev = close
    return bars
