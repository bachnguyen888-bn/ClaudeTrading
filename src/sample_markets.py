"""
Build a SAMPLE prediction-market dataset from historical BTC prices.

Real historical prediction-market prices are hard to get for free, so this
creates weekly "Will BTC close above $K in 7 days?" markets where:
  * the OUTCOMES are real: they come from actual historical BTC closes;
  * the MARKET PRICES are SIMULATED: a noisy pricing model stands in for
    real traders.
That makes it good for testing the pipeline and learning, and useless as
evidence that any strategy beats real markets. Swap in real exported data
(same CSV columns) for real research.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import timedelta
from pathlib import Path
from typing import List

from .data_loader import Bar
from .indicators import realized_volatility
from .prediction_market import prob_above_strike

HORIZON_DAYS = 7
STRIKE_MULTIPLIERS = (0.95, 1.00, 1.05)
MARKET_VOL_LOOKBACK = 10  # the simulated "market" uses a shorter, noisier vol estimate
FIELDNAMES = ["market_id", "question", "decision_time", "resolve_time",
              "strike", "yes_price", "outcome", "my_probability"]


def nice_strike(price: float) -> float:
    """Round to a strike a real market might list ($1, $10, $100 steps depending on price)."""
    step = 10 ** max(0, int(math.floor(math.log10(price))) - 2)
    return round(price / step) * step


def make_sample_markets(bars: List[Bar], path: str | Path, seed: int = 42) -> int:
    """Write the sample CSV. Needs daily bars. Returns the number of markets written."""
    rng = random.Random(seed)
    closes = [b.close for b in bars]
    vol = realized_volatility(closes, MARKET_VOL_LOOKBACK, 365.0)
    one_day = timedelta(days=1)
    rows = []
    for d, bar in enumerate(bars):
        r = d + HORIZON_DAYS
        if bar.timestamp.weekday() != 0 or d < 30 or r >= len(bars) or vol[d] is None:
            continue
        if bars[r].timestamp - bar.timestamp != timedelta(days=HORIZON_DAYS):
            continue  # skip weeks with missing data
        spot = closes[d]
        decision_time = bar.timestamp + one_day  # just after Monday's close
        resolve_time = bars[r].timestamp + one_day  # just after the following Monday's close
        resolve_day = bars[r].timestamp.date().isoformat()
        market_vol = min(max(vol[d] * math.exp(rng.gauss(0.0, 0.25)), 0.15), 2.5)
        for multiplier in STRIKE_MULTIPLIERS:
            strike = nice_strike(spot * multiplier)
            fair = prob_above_strike(spot, strike, market_vol, HORIZON_DAYS / 365.0)
            yes_price = round(min(max(fair + rng.gauss(0.0, 0.03), 0.01), 0.99), 2)
            rows.append({
                "market_id": f"BTC-ABOVE-{strike:g}-{resolve_day}",
                "question": f"Will BTC close above ${strike:,.0f} on {resolve_day} (UTC)?",
                "decision_time": decision_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "resolve_time": resolve_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "strike": f"{strike:g}",
                "yes_price": f"{yes_price:.2f}",
                "outcome": 1 if closes[r] > strike else 0,
                "my_probability": "",
            })

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
