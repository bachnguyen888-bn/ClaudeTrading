from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src import dashboard, downloader
from src.data_loader import bars_per_year, filter_dates, load_ohlcv_csv, save_ohlcv_csv
from src.env_loader import load_env_file
from tests.helpers import bars_from_closes, temp_dir


class CsvLoaderTests(unittest.TestCase):
    def test_flexible_columns_and_unix_milliseconds(self):
        path = temp_dir(self) / "prices.csv"
        path.write_text("Unix,Open,High,Low,Close,Volume BTC\n"
                        "1609545600000,2,3,1,2.5,10\n"
                        "1609459200000,1,2.2,0.9,2,5\n"
                        "1609459200000,1,2.2,0.9,2,5\n"  # duplicate
                        "bad,row,,,,\n", encoding="utf-8")
        bars = load_ohlcv_csv(path)
        self.assertEqual([b.timestamp.date().isoformat() for b in bars], ["2021-01-01", "2021-01-02"])
        self.assertEqual(bars[1].close, 2.5)

    def test_missing_columns_explained(self):
        path = temp_dir(self) / "prices.csv"
        path.write_text("date,close\n2021-01-01,1\n2021-01-02,2\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_ohlcv_csv(path)
        self.assertIn("open", str(ctx.exception))

    def test_save_and_reload_round_trip(self):
        bars = bars_from_closes([100, 101, 102])
        path = temp_dir(self) / "out.csv"
        save_ohlcv_csv(bars, path)
        self.assertEqual([b.close for b in load_ohlcv_csv(path)], [100, 101, 102])

    def test_filter_dates_and_bars_per_year(self):
        bars = bars_from_closes(list(range(1, 11)))
        self.assertEqual(len(filter_dates(bars, "2020-01-03", "2020-01-05")), 3)
        self.assertAlmostEqual(bars_per_year(bars), 365)


class DownloaderTests(unittest.TestCase):
    """No network: a fake fetcher stands in for the exchange."""

    def test_coinbase_pages_sorts_dedupes_and_drops_unfinished_bar(self):
        calls = []
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=400)

        def fake_fetch(url):
            calls.append(url)
            day0 = start + timedelta(days=300 * (len(calls) - 1))
            rows = []
            for d in range(300):
                ts = day0 + timedelta(days=d)
                if ts < end:
                    rows.append([int(ts.timestamp()), 9, 11, 10, 10.5, 1])
            return list(reversed(rows))  # Coinbase sends newest first

        bars = downloader.download_coinbase(start, end, fetch=fake_fetch, pause_seconds=0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(u.startswith("https://api.exchange.coinbase.com/") for u in calls))
        self.assertEqual(bars[0].timestamp, start)
        self.assertEqual(len(bars), 400)
        self.assertEqual((bars[0].open, bars[0].high, bars[0].low, bars[0].close), (10, 11, 9, 10.5))

    def test_kraken_parsing(self):
        payload = {"error": [], "result": {"XXBTZUSD": [[1577836800, "7000", "7300", "6900", "7200", "7100", "12.5", 99]],
                                           "last": 1577836800}}
        bars = downloader.parse_kraken_ohlc(payload)
        self.assertEqual((bars[0].open, bars[0].close, bars[0].volume), (7000, 7200, 12.5))

    def test_refuses_hosts_not_on_the_allowlist(self):
        for url in ("https://evil.example.com/x", "http://api.kraken.com/0/public/OHLC"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                downloader.http_get_json(url)


class EnvLoaderTests(unittest.TestCase):
    def test_parses_quotes_comments_and_keeps_existing_values(self):
        path = temp_dir(self) / ".env"
        path.write_text("# comment\nTRADING_MODE=paper\nQUOTED='a b'\nINLINE=x # note\nTEST_KEEP=file\n",
                        encoding="utf-8")
        with mock.patch.dict(os.environ, {"TEST_KEEP": "shell"}, clear=False):
            values = load_env_file(path)
            self.assertEqual(values["QUOTED"], "a b")
            self.assertEqual(values["INLINE"], "x")
            self.assertEqual(os.environ["TEST_KEEP"], "shell")


class DashboardTests(unittest.TestCase):
    def test_ascii_chart_shape(self):
        lines = dashboard.ascii_chart([1, 2, 3, 2, 5] * 30, width=40, height=8)
        self.assertEqual(len(lines), 9)

    def test_summary_always_shows_paper_banner(self):
        payload = json.loads(json.dumps({
            "run_id": "r", "experiment": "btc_backtest", "strategy": "sma_crossover", "data_label": "x",
            "skip_reasons": {"volatility_too_high": 2}, "metrics": {
                "start_date": "2020-01-01", "end_date": "2021-01-01", "years": 1, "bars": 366,
                "total_return_pct": 5, "buy_hold_return_pct": 50, "max_drawdown_pct": 3,
                "buy_hold_max_drawdown_pct": 30, "cagr_pct": 5, "sharpe": 1.1, "start_equity": 10000,
                "end_equity": 10500, "trades": 3, "win_rate_pct": 66.7, "wins": 2, "losses": 1,
                "profit_factor": 2.0, "avg_win": 400, "avg_loss": -300, "largest_win": 500,
                "largest_loss": -300, "total_fees": 12, "exposure_pct": 20}}))
        text = dashboard.render_summary(payload, [1, 2, 3])
        self.assertIn("PAPER MODE ONLY", text)
        self.assertIn("volatility_too_high", text)


if __name__ == "__main__":
    unittest.main()
