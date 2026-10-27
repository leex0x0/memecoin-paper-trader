# memecoin-paper-trader

A **paper-trading backtester and live paper-trading logger** for Solana / Base
memecoins, built on **real** price data from free public APIs. No wallet, no
keys, no real transactions — ever. It exists to answer one honest question:

> If you systematically traded a basket of popular memecoins over the last year,
> would any simple strategy actually make money after fees and slippage?

**Short answer from the real data below: no.** Over the 12 months to
2026‑10‑27, *every* strategy tested lost money, and plain buy‑and‑hold lost the
most (‑71.7%). The full numbers, produced by the code in this repo, are below —
nothing here is cherry‑picked or invented.

---

## What it does

1. **`src/fetch_data.py`** — pulls real daily OHLCV candles for the basket from
   the **GeckoTerminal** free API (with a **DexScreener** fallback for pool
   resolution and live price), and saves them to `data/*.csv`.
2. **`src/backtest.py`** — backtests 5 strategies on that data with realistic
   frictions, logs every simulated trade, and writes honest result tables.
3. **`src/live_paper.py`** — a live paper-trading loop that pulls current prices
   and logs simulated buys/sells + P&L, safe to run on a schedule.

## Data (real, not fabricated)

- Source: GeckoTerminal OHLCV endpoint (`/networks/{net}/pools/{pool}/ohlcv/day`),
  no API key. DexScreener used as a fallback for pool resolution / live price.
- The free tier returns ~6 months per call and **caps daily history at ~1 year**
  (older pages return HTTP 401). So each token here has **365 daily candles,
  2025‑10‑28 → 2026‑10‑27**. That one-year window is the main data limitation.
- For each token we pick the **most liquid pool where the token is the base
  asset** (otherwise OHLCV would chart the wrong side of the pair — this bit us
  on DEGEN during development and is now handled).
- If a token/pool can't be fetched it is skipped and logged in
  `data/_fetch_manifest.csv`. In this run **9/9 tokens fetched successfully.**

### The basket actually used

| Token | Network | Pool (base/quote) | Pool liquidity (USD) |
|-------|---------|-------------------|----------------------|
| WIF    | solana   | $WIF / SOL        | ~$5.3M  |
| BONK   | solana   | Bonk / SOL        | ~$0.30M |
| POPCAT | solana   | POPCAT / SOL      | ~$3.4M  |
| MEW    | solana   | MEW / SOL         | ~$8.9M  |
| PNUT   | solana   | Pnut / SOL        | ~$3.0M  |
| BRETT  | base     | BRETT / WETH      | ~$1.1M  |
| TOSHI  | base     | TOSHI / WETH      | ~$1.0M  |
| DEGEN  | base     | DEGEN / WETH      | ~$0.25M |
| PEPE   | ethereum | PEPE / WETH       | ~$29.4M |

> Note: **PEPE is Ethereum-native, not a Solana/Base token.** It is included as
> a well-known reference memecoin and is clearly labelled `ethereum`. Everything
> else is Solana or Base, as requested. GIGA was dropped during development
> because its address returned HTTP 404 on GeckoTerminal.

## Strategies

| Key | Idea |
|-----|------|
| `momentum_breakout` | Donchian: long on a 20-day high breakout, exit on a 10-day low. |
| `dip_buy` | Buy 30% below the prior 20-day high; exit on +25% bounce, -35% stop, or 15 days. |
| `ma_crossover` | Long while 10-day SMA > 30-day SMA. |
| `fomo_baseline` | **Deliberately naive:** buy after a +20% single-day pump, hold 5 days. Meant to lose. |
| `buy_and_hold` | Reference: buy day 1, hold to the end. |

All signals are computed on data up to the **previous** close and executed at the
**next bar's open** — no look-ahead.

## Frictions (applied to every simulated trade)

- **Trading fee:** 30 bps (0.30%) **per side**.
- **Slippage, per side, scaled by pool liquidity:** ≥$3M → 50 bps, $1–3M → 100
  bps, $0.3–1M → 200 bps, <$0.3M → 400 bps.
- **Illiquidity / rug exit haircut (an explicit assumption, not market data):**
  extra 150 bps on exits for $0.3–1M pools and 300 bps for <$0.3M pools, to
  model wide spreads / failed sells / partial rugs when leaving a thin token.

---

## RESULTS (actual numbers this code produced)

Equal-weight portfolio, **$1,000 notional per token**, 9 tokens, 2025‑10‑28 →
2026‑10‑27. Straight from `results/summary_by_strategy.csv`:

| Strategy | Total return | Win rate | Max drawdown | Trades | Sharpe‑ish |
|----------|-------------:|---------:|-------------:|-------:|-----------:|
| `fomo_baseline`     | **‑13.4%** | 13.3% | ‑16.5% | 15 | ‑1.73 |
| `dip_buy`           | ‑14.2% | 41.0% | ‑29.9% | 39 | ‑0.20 |
| `momentum_breakout` | ‑40.5% | 22.6% | ‑43.0% | 62 | ‑1.29 |
| `ma_crossover`      | ‑58.6% | 10.0% | ‑58.6% | 60 | ‑2.22 |
| `buy_and_hold`      | **‑71.7%** | 0.0% | ‑75.4% | 9 | ‑1.01 |

### Which won / which lost

- **Nothing won.** Every strategy lost money over this window.
- **Least bad:** `fomo_baseline` (‑13.4%). This is *not* because chasing pumps is
  smart — it's because in a falling market the FOMO rule rarely triggered (only
  **15 trades across 9 tokens**), so it sat in cash most of the year and simply
  **avoided the carnage**. Its 13% win rate and ‑1.73 Sharpe show that when it
  *did* trade, it lost.
- **Best "real" strategy:** `dip_buy` (‑14.2%) had the highest win rate (41%) and
  the least-negative Sharpe (‑0.20), and actually produced winners on some
  tokens (TOSHI +36%, WIF +16%, PEPE +12%, POPCAT +8%). But averaged across the
  basket it still lost.
- **Worst:** `buy_and_hold` (‑71.7%). These memecoins dumped hard over the year;
  WIF fell from ~$0.53 to ~$0.18, and several lost 80%+. Holding = full exposure
  to that.
- The two trend-following strategies (`momentum_breakout`, `ma_crossover`) were
  chopped up badly: lots of trades, each paying fees + slippage, while the
  underlying trend was down.

### The lesson

In a **down year for memecoins**, systematic long-only strategies on real data,
after realistic frictions, **lost money** — and the more a strategy traded, the
more frictions ate it. The "winner" was the one that barely participated. This is
the honest, unglamorous reality: **most memecoin trading loses to variance and
costs**, and backtests that look great are usually overfit or ignore fees,
slippage, and the fact that you can't cleanly exit a thin token. Treat any
"turn $10 into $1M" story as survivorship bias.

Per-token detail is in `results/summary.csv`; every individual simulated trade is
in `results/trades_<strategy>.csv`.

---

## Reproduce it

```bash
# 1. install (Python 3.9+)
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt

# 2. pull real data (polite throttling + backoff for GeckoTerminal rate limits;
#    takes a few minutes). Writes data/*.csv and data/_fetch_manifest.csv
python src/fetch_data.py

# 3. backtest -> prints the tables and writes results/*.csv + backtest_summary.txt
python src/backtest.py

# 4. live paper loop (SIMULATION ONLY, no keys, no wallet)
python src/live_paper.py --once                 # one pass, good for cron
python src/live_paper.py --interval 900          # loop every 15 minutes
```

The committed `data/` and `results/` CSVs are exactly what these commands
produced on 2026‑10‑27, so the numbers above are reproducible from this repo.

### Live loop notes

- It logs current prices to `results/live_prices.csv` and only starts signalling
  once it has `--sma` samples (default 10) of its *own* logged history, so its
  signal cadence depends on how often you run it. Trades go to
  `results/live_paper_trades.csv`, portfolio snapshots to `results/live_equity.csv`.
- These live runtime files are git-ignored (they grow every run). The backtest
  data/trade-logs/summaries are committed.
- **Safety:** there is no signing, no private key, and no transaction-sending
  code anywhere in this project. It cannot move funds.

## Repo layout

```
data/      raw OHLCV CSVs pulled from the APIs + _fetch_manifest.csv  (committed)
results/   trade logs, summary.csv, summary_by_strategy.csv, backtest_summary.txt
src/       fetch_data.py, strategies.py, backtest.py, live_paper.py, tokens.py
```

## Honest blockers & caveats

- **API rate limits:** GeckoTerminal's free tier returns HTTP 429 aggressively
  from shared IPs; the fetcher throttles (~2.6s between calls) and backs off, so
  a full pull takes several minutes.
- **1-year history cap:** the free tier won't serve daily candles older than
  ~1 year (HTTP 401 on older pages), so backtests here are a single 12-month
  regime — and that regime was broadly *down* for memecoins. Results would differ
  in a bull regime; do not extrapolate.
- **Daily candles only:** intraday memecoin moves (the stuff people actually try
  to scalp) are not captured.
- **Frictions are modelled, not measured.** Real fills on thin tokens can be far
  worse than the 50–400 bps assumed; the rug/illiquidity haircut is a deliberate
  conservative assumption.
- **No survivorship correction beyond the basket:** tokens that fully rugged and
  delisted aren't in GeckoTerminal's served history, so the real average outcome
  for "pick a random memecoin" is likely *worse* than shown here.

## Disclaimer

This is research/educational tooling, not financial advice. It performs no real
trades. Memecoins are extremely high risk; most lose value.
