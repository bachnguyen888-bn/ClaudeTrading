# Data folder

| File | What it is |
|---|---|
| `sample/btc_usd_1d_sample.csv` | **Real** historical BTC/USD daily bars from Bitstamp, 2013-01-01 to 2017-08-21 (1,691 days). Bundled so the project works offline on first run. |
| `sample/prediction_markets_sample.csv` | **Sample** weekly "Will BTC close above $K?" markets built from the file above. Outcomes are real; **market prices are simulated** (see below). |
| `btc_usd_1d.csv` | Created by `python -m src.main download`. Fresh daily history from a public exchange API. When it exists, backtests use it instead of the sample. |
| `btc_usd_1h.csv` | Created by `python -m src.main download --granularity 1h`. |

## Where the sample BTC data comes from

Hourly Bitstamp BTC/USD candles published as test data in the open-source
[`ta` library](https://github.com/bukosabino/ta) (`test/data/datas.csv`, MIT
license), rolled up into daily bars (UTC days): first open, highest high,
lowest low, last close, summed BTC volume. Three days in January 2015 are
missing because Bitstamp was offline after a security incident. The loader
handles the gap.

## About the sample prediction markets

Free historical prediction-market price data is hard to find, so
`python -m src.main make-sample-markets` creates practice markets:

- every Monday, three markets: "Will BTC close above 95% / 100% / 105% of today's price in 7 days?"
- **outcome**: taken from the real BTC close 7 days later
- **yes_price**: simulated with a noisy pricing model (seeded, so it's reproducible)

Because the prices are simulated, a model can find "edge" in the random noise
that real traders would never leave on the table. **Profits on the sample
markets say nothing about real markets.** Use the file to learn the workflow,
then replace it with real data.

## Using your own data

**Price CSVs** need these columns (names are case-insensitive):
`timestamp` (or `date`/`time`), `open`, `high`, `low`, `close`, and optionally `volume`.
Timestamps can be dates (`2021-03-01`), ISO datetimes, or unix seconds/milliseconds.

**Prediction-market CSVs** need:

| column | required | meaning |
|---|---|---|
| `market_id` | yes | any unique name |
| `question` | no | shown in logs and reports |
| `decision_time` | yes | when you would have placed the bet (the price is observed at this time) |
| `resolve_time` | yes | when the outcome became known |
| `yes_price` | yes | price of one YES share at decision time, between 0 and 1 |
| `outcome` | yes | 1 if it resolved YES, 0 if NO |
| `strike` | one of these two | for "BTC above $strike at resolve_time" markets: the built-in model estimates the probability |
| `my_probability` | one of these two | your own forecast (0 to 1). Overrides the model, and works for any question, not just BTC |
