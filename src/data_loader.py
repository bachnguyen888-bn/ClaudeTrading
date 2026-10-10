"""
Load historical OHLCV price data (open, high, low, close, volume) from CSV.

The loader is forgiving about column names ("Date", "timestamp", "Close",
"close"...) and timestamp formats (2020-01-31, ISO datetimes, unix seconds
or milliseconds), so you can drop in CSVs from most free data sites.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

TIME_COLUMNS = ("timestamp", "date", "time", "datetime", "open_time", "unix")
VOLUME_COLUMNS = ("volume", "volume_btc", "vol")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime  # start of the bar, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def parse_timestamp(value: str) -> datetime:
    """Turn a date/datetime/unix-time string into a UTC datetime."""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        if number > 1e11:  # milliseconds
            number /= 1000.0
        return datetime.fromtimestamp(number, tz=timezone.utc)

    text = text.replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_ohlcv_csv(path: str | Path) -> List[Bar]:
    """Read a price CSV into a sorted, de-duplicated list of Bars."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Price data not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty.")
        columns = _map_columns(reader.fieldnames, path)
        bars_by_time: Dict[datetime, Bar] = {}
        bad_rows = 0
        for row in reader:
            bar = _row_to_bar(row, columns)
            if bar is None:
                bad_rows += 1
                continue
            bars_by_time[bar.timestamp] = bar

    if bad_rows:
        log.warning("Skipped %d unreadable or invalid rows in %s", bad_rows, path.name)
    bars = [bars_by_time[t] for t in sorted(bars_by_time)]
    if len(bars) < 2:
        raise ValueError(f"{path} has fewer than 2 usable price rows.")
    return bars


def _map_columns(fieldnames: List[str], path: Path) -> Dict[str, Optional[str]]:
    lookup = {name.strip().lower(): name for name in fieldnames if name}
    columns: Dict[str, Optional[str]] = {}
    columns["timestamp"] = next((lookup[c] for c in TIME_COLUMNS if c in lookup), None)
    for field in ("open", "high", "low", "close"):
        columns[field] = lookup.get(field)
    columns["volume"] = next((lookup[c] for c in VOLUME_COLUMNS if c in lookup), None)
    missing = [k for k in ("timestamp", "open", "high", "low", "close") if columns[k] is None]
    if missing:
        raise ValueError(
            f"{path.name} is missing column(s): {', '.join(missing)}. "
            f"Found: {', '.join(fieldnames)}. Expected: timestamp, open, high, low, close[, volume]."
        )
    return columns


def _row_to_bar(row: Dict[str, str], columns: Dict[str, Optional[str]]) -> Optional[Bar]:
    try:
        timestamp = parse_timestamp(row[columns["timestamp"]])
        o, h, l, c = (float(row[columns[k]]) for k in ("open", "high", "low", "close"))
        v = float(row[columns["volume"]] or 0) if columns["volume"] else 0.0
    except (TypeError, ValueError, KeyError):
        return None
    if min(o, h, l, c) <= 0 or max(o, h, l, c) > 1e12:
        return None
    # Repair slightly inconsistent rows instead of dropping them.
    h = max(h, o, c)
    l = min(l, o, c)
    return Bar(timestamp, o, h, l, c, v)


def save_ohlcv_csv(bars: List[Bar], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    daily = _is_daily(bars)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in bars:
            stamp = bar.timestamp.date().isoformat() if daily else bar.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
            writer.writerow([stamp, f"{bar.open:.2f}", f"{bar.high:.2f}", f"{bar.low:.2f}",
                             f"{bar.close:.2f}", f"{bar.volume:.6f}"])


def _is_daily(bars: List[Bar]) -> bool:
    return all(b.timestamp.hour == 0 and b.timestamp.minute == 0 for b in bars[:50])


def filter_dates(bars: List[Bar], start: Optional[str], end: Optional[str]) -> List[Bar]:
    """Keep bars between start and end (inclusive, YYYY-MM-DD strings or None)."""
    start_d = date.fromisoformat(start) if start else None
    end_d = date.fromisoformat(end) if end else None
    return [
        b for b in bars
        if (start_d is None or b.timestamp.date() >= start_d)
        and (end_d is None or b.timestamp.date() <= end_d)
    ]


def bars_per_year(bars: List[Bar]) -> float:
    """Crypto trades 24/7, so a year of daily bars is 365, of hourly bars 8760."""
    gaps = sorted(
        (bars[i + 1].timestamp - bars[i].timestamp).total_seconds()
        for i in range(min(len(bars) - 1, 500))
    )
    median_gap = gaps[len(gaps) // 2] if gaps else 86400.0
    return 365.0 * 86400.0 / max(median_gap, 1.0)
