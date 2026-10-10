"""
Download public historical BTC prices for backtesting.

READ-ONLY. This uses public market-data endpoints that need no account and
no API key. It only ever sends HTTP GET requests to the hosts listed in
ALLOWED_HOSTS, and it never sends credentials. It cannot place orders.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

from .data_loader import Bar

log = logging.getLogger(__name__)

ALLOWED_HOSTS = {"api.exchange.coinbase.com", "api.kraken.com"}
USER_AGENT = "btc-paper-research/1.0 (read-only historical data)"
GRANULARITY_SECONDS = {"1d": 86400, "1h": 3600}

COINBASE_MAX_CANDLES = 300
KRAKEN_MAX_CANDLES = 720

# Tests swap this for a fake so they never touch the network.
Fetcher = Callable[[str], Any]


def http_get_json(url: str, retries: int = 3) -> Any:
    """GET a public URL and decode JSON. Refuses any host not on the allowlist."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing to contact {parsed.hostname!r}: not an allowed read-only data host.")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def download_coinbase(
    start: datetime,
    end: Optional[datetime] = None,
    granularity: str = "1d",
    product: str = "BTC-USD",
    fetch: Fetcher = http_get_json,
    pause_seconds: float = 0.35,
) -> List[Bar]:
    """Coinbase Exchange public candles. Returns at most 300 per request, so we page."""
    step = GRANULARITY_SECONDS[granularity]
    end = end or datetime.now(timezone.utc)
    bars: dict = {}
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(seconds=step * COINBASE_MAX_CANDLES), end)
        query = urllib.parse.urlencode({
            "granularity": step,
            "start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        rows = fetch(f"https://api.exchange.coinbase.com/products/{product}/candles?{query}")
        if isinstance(rows, dict):
            raise RuntimeError(f"Coinbase returned an error: {rows.get('message', rows)}")
        for bar in parse_coinbase_candles(rows):
            bars[bar.timestamp] = bar
        log.info("Coinbase: %s -> %s (%d bars so far)", window_start.date(), window_end.date(), len(bars))
        window_start = window_end
        if pause_seconds:
            time.sleep(pause_seconds)
    return _complete_bars_only(sorted(bars.values(), key=lambda b: b.timestamp), step)


def parse_coinbase_candles(rows: List[list]) -> List[Bar]:
    # Each row is [time, low, high, open, close, volume], newest first.
    bars = []
    for row in rows:
        ts, low, high, open_, close, volume = row[:6]
        bars.append(Bar(datetime.fromtimestamp(int(ts), tz=timezone.utc),
                        float(open_), float(high), float(low), float(close), float(volume)))
    return bars


def download_kraken(
    granularity: str = "1d",
    pair: str = "XBTUSD",
    fetch: Fetcher = http_get_json,
) -> List[Bar]:
    """Kraken public OHLC. Kraken only serves the most recent 720 candles."""
    step = GRANULARITY_SECONDS[granularity]
    query = urllib.parse.urlencode({"pair": pair, "interval": step // 60})
    payload = fetch(f"https://api.kraken.com/0/public/OHLC?{query}")
    return _complete_bars_only(parse_kraken_ohlc(payload), step)


def parse_kraken_ohlc(payload: dict) -> List[Bar]:
    if payload.get("error"):
        raise RuntimeError(f"Kraken returned an error: {payload['error']}")
    result = payload["result"]
    series_key = next(key for key in result if key != "last")
    bars = []
    # Each row is [time, open, high, low, close, vwap, volume, count].
    for row in result[series_key]:
        bars.append(Bar(datetime.fromtimestamp(int(row[0]), tz=timezone.utc),
                        float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[6])))
    return sorted(bars, key=lambda b: b.timestamp)


def _complete_bars_only(bars: List[Bar], step_seconds: int, now: Optional[datetime] = None) -> List[Bar]:
    """Drop the still-forming current candle so we only backtest finished bars."""
    now = now or datetime.now(timezone.utc)
    return [b for b in bars if b.timestamp + timedelta(seconds=step_seconds) <= now]
