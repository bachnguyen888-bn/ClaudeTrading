# BTC & Prediction-Market Paper-Trading Lab

A beginner-friendly **research project** for testing BTC trading ideas and
prediction-market betting ideas on **historical data, with pretend money**.

> **PAPER MODE ONLY.** This project cannot place real orders, connect a
> wallet, or move real money. There is no setting that turns live trading on.
> Making it trade for real would require deliberately rewriting the project.

What you get:

- **BTC backtester**: three simple strategies, ATR-based position sizing, stop-losses, a volatility filter, daily loss limits and a drawdown kill switch.
- **Prediction-market experiment**: compares your probability (or a simple BTC model) with market prices, places simulated bets when it sees an edge, and scores forecast quality.
- **A log row for every decision**: entries, exits, wins, losses, and **skipped trades with the reason**.
- **Terminal summary plus an HTML dashboard** for every run.
- **`config.json`**: change every risk limit without touching code.
- **No installs needed**: only the Python standard library (Python 3.9 or newer).

---

## Table of contents

1. [Quick start](#quick-start)
2. [How live trading is blocked](#how-live-trading-is-blocked)
3. [Commands](#commands)
4. [Getting fresh historical data](#getting-fresh-historical-data)
5. [Project structure](#project-structure)
6. [How a backtest works](#how-a-backtest-works)
7. [The trade log](#the-trade-log)
8. [Prediction-market experiments](#prediction-market-experiments)
9. [Config reference](#config-reference)
10. [Running the tests](#running-the-tests)
11. [Ideas to try](#ideas-to-try)
12. [Honest limitations](#honest-limitations)

---

## Quick start

You need **Python 3.9+**. Check with `python3 --version` (on Windows: `py --version`).

```bash
# 1. Get the code and go into the folder
git clone https://github.com/bachnguyen888-bn/ClaudeTrading.git
cd ClaudeTrading

# 2. Create your private settings file (optional but recommended)
cp .env.example .env          # Windows: copy .env.example .env

# 3. Check that everything is set up (and that paper mode is enforced)
python3 -m src.main check

# 4. Run your first backtest (uses bundled real BTC data from 2013-2017)
python3 -m src.main backtest

# 5. Run the prediction-market experiment
python3 -m src.main predict
```

On Windows, type `py` instead of `python3`.

Each run prints a summary like this (shortened):

```
==============================================================
  PAPER MODE ONLY - simulated trades, no real money, no orders
==============================================================
  BTC BACKTEST SUMMARY   run 20261010_053534_421_btc_backtest
------------------------------------------------------------------
  Strategy: sma_crossover
  Period:   2013-01-01 -> 2017-08-21 (4.64 years, 1691 bars)

                                      Strategy        Buy & hold
  Total return                         +20.20%        +30062.78%
  Max drawdown                          -2.81%           -84.86%
  Sharpe ratio                            1.37

  Trades
  Completed trades                          13   win rate 53.85%
  ...
  Skipped signals (2) - logged with reasons
  volatility_too_low                         1
  volatility_too_high                        1
```

Then open the HTML dashboard in your browser. Its path is printed at the
bottom of the summary, for example `results/<run_id>/report.html`. It works
offline and follows your light or dark system theme.

> Notice in the example how a careful, risk-limited strategy made +20% while
> simply holding BTC made +30,000% in that period, with an 85% crash along the way.
> Comparing against buy & hold is the most humbling and most useful number here.

---

## How live trading is blocked

Safety is layered, so no single mistake can turn this into a live trading bot:

| Layer | What it does |
|---|---|
| **No live code exists** | There is no exchange client, no order-sending code, and no wallet code anywhere in `src/`. The "broker" (`src/paper_broker.py`) only does arithmetic in memory. |
| **Hard-coded flag** | `PAPER_MODE_ONLY = True` in `src/safety.py`. It is never read from config or `.env`, and the simulated broker refuses to start if it's changed. |
| **Config check** | `config.json` must say `"mode": "paper"`. Anything else, a `"live_trading"` key, or a key like `wallet` or `private_key` stops every command. |
| **Environment check** | `TRADING_MODE` in `.env` must be `paper` (or unset). If `.env` contains a variable whose name includes `PRIVATE_KEY`, `MNEMONIC`, `SEED_PHRASE` or `WALLET` with a value, the program refuses to run. |
| **Library check** | If a live-trading library (`ccxt`, `web3`, `py_clob_client`, ...) gets imported, the program stops. |
| **`live` command** | `python3 -m src.main live` exists only to refuse, with exit code 2. |
| **Network allowlist** | Only `src/downloader.py` touches the internet: HTTP **GET** requests to two public price-history endpoints (Coinbase, Kraken), no credentials. Any other host is refused. |
| **Tests** | `tests/test_safety.py` checks all of the above, including scanning the source code for forbidden imports and network modules. |

**Secrets:** keep any API keys in `.env`, never in `config.json` or the code.
`.env` is in `.gitignore`, so it is never committed. This project never needs a
wallet key or an exchange trading key; don't put one anywhere near it.

---

## Commands

Run everything from the project folder:

| Command | What it does |
|---|---|
| `python3 -m src.main check` | Validates `config.json` and `.env`, runs the safety checks, shows which data files exist. |
| `python3 -m src.main backtest` | Runs the BTC strategy backtest. |
| `python3 -m src.main backtest --strategy donchian_breakout` | Tries another strategy without editing config. Options: `sma_crossover`, `rsi_mean_reversion`, `donchian_breakout`. |
| `python3 -m src.main backtest --start 2015-01-01 --end 2016-12-31` | Backtests only a date range. |
| `python3 -m src.main backtest --csv path/to/prices.csv` | Uses your own price file. |
| `python3 -m src.main predict` | Runs the prediction-market paper experiment. |
| `python3 -m src.main predict --markets my_markets.csv` | Uses your own prediction-market file. |
| `python3 -m src.main download` | Downloads fresh public BTC history (see below). |
| `python3 -m src.main make-sample-markets` | Rebuilds the sample prediction markets from your BTC data. |
| `python3 -m src.main summary` | Re-prints the latest run's summary. Add `--run <run_id>` for an older one. |
| `python3 -m src.main live` | Refuses. Always. |

Add `--config other.json` before the command to use a different config file,
for example `python3 -m src.main --config aggressive.json backtest`.

---

## Getting fresh historical data

The bundled sample covers 2013 to 2017. For recent history, run this on your own computer:

```bash
python3 -m src.main download                      # daily candles from 2016 (Coinbase public API)
python3 -m src.main download --start 2020-01-01   # choose a start date
python3 -m src.main download --source kraken      # alternative source (most recent 720 candles only)
python3 -m src.main download --granularity 1h --start 2024-01-01   # hourly candles
```

These are public, read-only endpoints. No account or API key is needed.
Daily data is saved to `data/btc_usd_1d.csv` and is used automatically from
then on. Hourly data goes to `data/btc_usd_1h.csv`; backtest it with
`--csv data/btc_usd_1h.csv`.

After downloading, rebuild the practice prediction markets from the newer data:

```bash
python3 -m src.main make-sample-markets
```

You can also drop in any CSV from a free data site. See [`data/README.md`](data/README.md) for the format.

---

## Project structure

```
ClaudeTrading/
├── config.json            <- all risk limits and settings (edit this!)
├── .env.example           <- copy to .env for private settings
├── README.md
├── requirements.txt       <- empty: standard library only
├── data/
│   ├── README.md          <- where the data comes from, CSV formats
│   └── sample/            <- bundled real BTC prices + sample markets
├── logs/                  <- trade_log.csv (every decision, all runs) + per-run text logs
├── results/               <- one folder per run: summary, equity curve, trades, report.html
├── src/
│   ├── main.py            <- command-line entry point
│   ├── safety.py          <- paper-mode guard (refuses anything live)
│   ├── config.py          <- loads and validates config.json
│   ├── env_loader.py      <- reads .env
│   ├── data_loader.py     <- reads price CSVs
│   ├── downloader.py      <- read-only public price downloads
│   ├── indicators.py      <- SMA, RSI, ATR, volatility (the math)
│   ├── signals.py         <- SIGNAL GENERATION: when to buy or sell
│   ├── volatility.py      <- VOLATILITY FILTER: is the market too wild or too dead?
│   ├── risk.py            <- RISK SIZING + limits: how much, and whether we may trade at all
│   ├── paper_broker.py    <- simulated fills with fees and slippage
│   ├── trade_logger.py    <- LOGGING: every entry, exit, bet and skip
│   ├── backtest.py        <- BTC backtest engine (wires the modules together)
│   ├── prediction_market.py  <- prediction-market experiment
│   ├── sample_markets.py  <- builds the sample markets
│   ├── metrics.py         <- return, drawdown, Sharpe, win rate, Brier score
│   ├── results_store.py   <- saves each run to results/
│   └── dashboard.py       <- terminal summary + HTML report
└── tests/                 <- run with: python3 -m unittest
```

Signal generation, risk sizing, volatility filtering and logging each live in
their own module. A signal never decides position size, the risk manager never
decides direction, and everything that happens goes through the logger.

---

## How a backtest works

For every bar (one day, or one hour for hourly data):

1. **At the open**, any order decided at the previous close is filled. Fees
   and slippage are charged.
2. **During the bar**, if the low touches the stop-loss, the position is sold
   at the stop, or at the open if the price gapped below it. If both the stop
   and the take-profit were touched in the same bar, the backtest assumes the
   worse outcome. With `trailing_stop` on, the stop then moves up behind the
   price (never down).
3. **At the close**, the account is marked to market and checked against the
   daily loss limit and the drawdown kill switch.
4. **At the close**, the strategy produces a signal (BUY, SELL or HOLD) using
   only data up to this close. A BUY must pass the **risk gate** and the
   **volatility filter**. If it passes, an order is queued for the next open.
   If not, a `SKIP` row records why.

Deciding at the close and acting at the next open means a strategy can never
trade on a price it couldn't have known (no "lookahead bias").
`tests/test_signals_and_volatility.py` checks this.

**Position sizing.** With `risk_per_trade_pct = 1` and a stop 2 ATRs below
entry, each trade is sized so that hitting the stop loses about 1% of the
account, whatever BTC's volatility. The position is then capped by
`max_position_pct` and by available cash (no leverage, long only).

**The strategies** (all long-only):

| Name | Buys when | Sells when |
|---|---|---|
| `sma_crossover` | the fast moving average crosses above the slow one | it crosses back below |
| `rsi_mean_reversion` | RSI drops below `buy_below` (oversold) | RSI rises above `sell_above` |
| `donchian_breakout` | the close breaks above the highest high of the last N bars | the close breaks below the lowest low of the last M bars |

Any of them can also exit through the stop-loss, take-profit, kill switch, or the end of the data.

---

## The trade log

`logs/trade_log.csv` collects every decision from every run. Each run's own
copy is at `results/<run_id>/trades.csv`. Open either one in Excel, Google
Sheets or Numbers.

| Column | Meaning |
|---|---|
| `run_id` | which run produced the row |
| `experiment` | `btc_backtest` or `prediction_markets` |
| `event` | `ENTRY`, `EXIT`, `SKIP`, `HALT`, `BET`, `RESOLVE` |
| `timestamp` | simulated time (UTC) |
| `market` | `BTC-USD` or the prediction market's id |
| `side` | `BUY` / `SELL`, or `YES` / `NO` |
| `reason` | why: `signal`, `stop_loss`, `volatility_too_high`, `WIN`, `LOSS`, ... |
| `price`, `quantity`, `notional`, `fee` | fill details |
| `pnl`, `pnl_pct` | profit or loss on exits and resolutions (negative = loss) |
| `cash_after`, `equity_after` | account state after the event |
| `details` | extra context as JSON: the signal text, stop level, volatility, model probability, edge... |

**Skip reasons you'll see:**

| Reason | Meaning |
|---|---|
| `volatility_too_high` / `volatility_too_low` | outside your `volatility_filter` band |
| `daily_loss_limit` | today's loss already reached `max_daily_loss_pct` |
| `max_trades_per_day` | already opened `max_trades_per_day` positions today |
| `max_drawdown_halt` | the kill switch has tripped; no new trades |
| `size_too_small` | the computed trade is below `min_trade_usd` (or less than 1 contract) |
| `edge_too_small` | (prediction markets) your probability isn't far enough from the price |
| `price_out_of_range` | (prediction markets) price outside `min_price`..`max_price` |
| `max_total_exposure` | (prediction markets) too much money already in open bets |
| `no_btc_history` / `volatility_not_ready` | not enough data to estimate a probability |

A text log of each run is also saved as `logs/run_<run_id>.log`.

---

## Prediction-market experiments

A binary contract pays **$1 if YES** and $0 if NO, so a YES price of $0.30 means
the market thinks there's about a 30% chance. The experiment:

1. Gets **your probability** for each market, either from a `my_probability`
   column you fill in, or, for "Will BTC close above $K?" markets, from a
   simple model (recent BTC volatility plus a lognormal price distribution).
2. Computes the **edge** for buying YES and for buying NO, after slippage and fees.
3. If the best edge is at least `min_edge`, places a simulated bet sized with
   **fractional Kelly**, capped by `max_stake_pct` and `max_total_exposure_pct`.
4. Pays out when the market resolves and logs a `RESOLVE` row (`WIN` or `LOSS`).

It also scores **forecast quality** with the **Brier score** (lower is better;
always guessing 50% scores 0.25) for your model *and* for the market prices,
plus a **calibration table**: when a forecast said 70%, did YES really happen
about 70% of the time? Beating the market's Brier score is a much harder and
more honest test than making money on one dataset.

> **The bundled sample markets have simulated prices** (outcomes are real BTC
> history). The simulated prices contain random noise that a model can
> exploit, so sample profits mean nothing about real markets. Use the sample
> to learn the workflow, then bring real data.

**Testing your own forecasts on any question:** make a CSV with
`market_id, question, decision_time, resolve_time, yes_price, outcome, my_probability`
(see [`data/README.md`](data/README.md)) and run
`python3 -m src.main predict --markets your_file.csv`.

---

## Config reference

Edit `config.json` and re-run. No code changes needed. Percentages are plain
numbers: `1.0` means 1%. Invalid values produce a plain-English error that
names the setting, and misspelled keys produce a warning. Keys starting with
`_` are comments.

**Top level**

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `"paper"` | must be `"paper"`; anything else is refused |
| `starting_cash_usd` | `10000` | pretend money for the BTC backtest |

**`data`**

| Setting | Default | Meaning |
|---|---|---|
| `btc_csv` | `data/btc_usd_1d.csv` | main price file (created by `download`) |
| `sample_btc_csv` | `data/sample/btc_usd_1d_sample.csv` | used when `btc_csv` doesn't exist |
| `prediction_markets_csv` | `data/sample/prediction_markets_sample.csv` | markets for `predict` |
| `download_source` | `coinbase` | `coinbase` or `kraken` |
| `download_start` | `2016-01-01` | first date to download |
| `download_granularity` | `1d` | `1d` or `1h` |

**`backtest`**: `start_date`, `end_date` (`"YYYY-MM-DD"` or `null` for all data).

**`costs`**

| Setting | Default | Meaning |
|---|---|---|
| `fee_pct` | `0.10` | exchange fee per fill, % of trade value |
| `slippage_pct` | `0.05` | you buy this % above and sell this % below the quoted price |

**`strategy`**: `name` picks the strategy. Each strategy has its own parameter block:
`sma_crossover` (`fast_period`, `slow_period`), `rsi_mean_reversion`
(`period`, `buy_below`, `sell_above`), `donchian_breakout` (`entry_lookback`, `exit_lookback`).

**`volatility_filter`**

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `true` | turn the filter on or off |
| `lookback_bars` | `20` | bars used to measure realized volatility |
| `min_annual_vol_pct` | `15` | skip entries when annualized volatility is below this |
| `max_annual_vol_pct` | `120` | skip entries when annualized volatility is above this |
| `atr_period` | `14` | bars used for ATR (used to place stops) |

**`risk`**

| Setting | Default | Meaning |
|---|---|---|
| `risk_per_trade_pct` | `1.0` | % of equity lost if the stop is hit |
| `stop_loss_atr_multiple` | `2.0` | stop distance below entry, in ATRs |
| `trailing_stop` | `true` | move the stop up as the price rises |
| `take_profit_atr_multiple` | `0` | take-profit distance above entry in ATRs (`0` = off) |
| `max_position_pct` | `50.0` | biggest position as % of equity (max 100 = no leverage) |
| `max_daily_loss_pct` | `3.0` | no new trades for the rest of the day after losing this much |
| `max_drawdown_pct` | `20.0` | **kill switch**: close everything and stop trading once equity falls this far below its peak |
| `max_trades_per_day` | `2` | most new positions per calendar day |
| `min_trade_usd` | `25` | skip trades smaller than this |

**`prediction_markets`**

| Setting | Default | Meaning |
|---|---|---|
| `starting_cash_usd` | `1000` | pretend bankroll |
| `vol_lookback_days` | `30` | days of BTC history the model uses for volatility |
| `min_edge` | `0.05` | minimum edge after costs, in $ per $1 contract (0.05 = 5 percentage points) |
| `kelly_fraction` | `0.25` | fraction of the Kelly bet to use (full Kelly is very aggressive) |
| `max_stake_pct` | `2.0` | biggest single bet, % of bankroll |
| `max_total_exposure_pct` | `20.0` | most of the bankroll allowed in open bets at once |
| `min_price` / `max_price` | `0.05` / `0.95` | skip extreme long shots and near-certainties |
| `price_slippage` | `0.01` | $ added to the price you pay per contract |
| `fee_per_contract` | `0.01` | $ fee per contract |
| `min_annual_vol_pct` / `max_annual_vol_pct` | `15` / `150` | volatility filter for BTC-model markets |
| `max_drawdown_pct` | `25.0` | kill switch for the betting bankroll |

**`output`**: `log_dir`, `results_dir`, `log_level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`), `terminal_chart` (`true`/`false`).

Every run saves the exact settings it used in `results/<run_id>/config_used.json`,
so you can always tell which settings produced which result.

---

## Running the tests

```bash
python3 -m unittest
```

The tests cover the safety guard, config validation, indicators, the
no-lookahead guarantee, risk sizing and limits, fill logic (including gaps
through a stop), logging of skips, prediction-market accounting, and data
loading. They never touch the network.

---

## Ideas to try

- Compare the three strategies: `--strategy rsi_mean_reversion`, `--strategy donchian_breakout`.
- Turn the volatility filter off (`"enabled": false`) and see what changes in the skips and the drawdown.
- Halve `risk_per_trade_pct` and see how return and drawdown scale.
- Set `take_profit_atr_multiple` to `4` and compare against the trailing stop alone.
- Test on one period (`--start 2014-01-01 --end 2015-12-31`), then check whether the settings hold up on another. If they only work on the period you tuned them on, they're probably overfit.
- Write down your own probabilities for real questions before they resolve, then score yourself with `my_probability`.
- Add a strategy: subclass `Strategy` in `src/signals.py`, register it in `build_strategy`, and add its name to `STRATEGIES` in `src/config.py`.

---

## Honest limitations

- **Backtests are optimistic.** Real fills, outages, liquidity and your own behaviour are messier than a simulation.
- **One dataset is one story.** 2013-2017 was a huge BTC bull market with brutal crashes. Results on it may not repeat.
- **Overfitting is easy.** Tweaking settings until the numbers look good mostly fits noise.
- **Daily bars hide intraday detail.** Stops are checked against each bar's high and low, but the order of moves inside a bar is unknown, so the simulation assumes the worse case.
- **The sample prediction-market prices are simulated.** See above.
- **This is not financial advice.** It's a learning and research tool.

And once more: **this project is simulation-only by design.** It refuses to
run in any live mode, and turning it into a real trading system would mean
rewriting it yourself, with all the risk that brings.
