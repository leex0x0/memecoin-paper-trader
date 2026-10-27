"""Backtest several strategies on the REAL fetched memecoin OHLCV data.

Applies realistic frictions (trading fee, liquidity-scaled slippage, and an
illiquidity/rug exit haircut), logs every simulated trade to CSV, and writes
honest summary tables. No price data is fabricated here: it only reads the
CSVs produced by fetch_data.py.

Usage:
    python src/backtest.py
Outputs (committed to the repo):
    results/trades_<strategy>.csv     every simulated round-trip trade
    results/summary.csv               metrics per strategy x token
    results/summary_by_strategy.csv   equal-weight portfolio metrics per strategy
    results/backtest_summary.txt      human-readable report (printed too)
"""
import csv
import glob
import math
import os

import numpy as np
import pandas as pd

from strategies import STRATEGIES

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")

START_CASH = 1000.0           # notional per token
FEE_BPS = 30                  # 0.30% DEX swap fee, charged each side
ANNUALISATION = 365           # daily candles -> crypto trades every day


def slippage_bps(reserve_usd):
    """Lower-liquidity pools cost more to trade into/out of (each side)."""
    if reserve_usd >= 3_000_000:
        return 50
    if reserve_usd >= 1_000_000:
        return 100
    if reserve_usd >= 300_000:
        return 200
    return 400


def rug_exit_bps(reserve_usd):
    """Extra haircut applied ONLY on exits, modelling the real-world risk/cost
    of getting out of a thin memecoin (wide spreads, failed sells, partial
    rugs). This is an explicit assumption, not market data."""
    if reserve_usd >= 1_000_000:
        return 0
    if reserve_usd >= 300_000:
        return 150
    return 300


def load_manifest():
    path = os.path.join(DATA_DIR, "_fetch_manifest.csv")
    m = {}
    if os.path.exists(path):
        df = pd.read_csv(path)
        for _, r in df.iterrows():
            if str(r["status"]) == "ok":
                m[str(r["symbol"])] = {
                    "network": str(r["network"]),
                    "reserve_usd": float(r["reserve_usd"]),
                }
    return m


def run_single(df, desired, reserve_usd):
    """Simulate one strategy on one token. Returns (trades, equity_series)."""
    open_ = df["open"].tolist()
    close = df["close"].tolist()
    dates = df["datetime"].tolist()
    n = len(close)

    fee = FEE_BPS / 10_000.0
    slip = slippage_bps(reserve_usd) / 10_000.0
    rug = rug_exit_bps(reserve_usd) / 10_000.0

    cash = START_CASH
    qty = 0.0
    pos = 0
    entry_date = None
    entry_px = None
    entry_bar = None
    trades = []
    equity = []

    for i in range(n):
        want = desired[i]
        if want == 1 and pos == 0:
            buy_px = open_[i] * (1 + slip)
            if buy_px > 0:
                qty = (cash * (1 - fee)) / buy_px
                cash = 0.0
                pos = 1
                entry_date, entry_px, entry_bar = dates[i], buy_px, i
        elif want == 0 and pos == 1:
            sell_px = open_[i] * (1 - slip)
            proceeds = qty * sell_px * (1 - fee - rug)
            trades.append({
                "token": None, "network": None,
                "entry_date": entry_date, "entry_px_exec": entry_px,
                "exit_date": dates[i], "exit_px_exec": sell_px,
                "bars_held": i - entry_bar,
                "pnl_pct": (proceeds / (qty * entry_px) - 1) * 100,
                "pnl_usd": proceeds - (qty * entry_px),
            })
            cash = proceeds
            qty = 0.0
            pos = 0
            entry_date = entry_px = entry_bar = None
        # mark to market at close
        equity.append(cash if pos == 0 else qty * close[i])

    # force-close at final close so results are fully realised
    if pos == 1:
        sell_px = close[-1] * (1 - slip)
        proceeds = qty * sell_px * (1 - fee - rug)
        trades.append({
            "token": None, "network": None,
            "entry_date": entry_date, "entry_px_exec": entry_px,
            "exit_date": dates[-1], "exit_px_exec": sell_px,
            "bars_held": (n - 1) - entry_bar,
            "pnl_pct": (proceeds / (qty * entry_px) - 1) * 100,
            "pnl_usd": proceeds - (qty * entry_px),
        })
        equity[-1] = proceeds

    eq = pd.Series(equity, index=pd.to_datetime(df["datetime"]))
    return trades, eq


def metrics(eq, trades):
    total_return = eq.iloc[-1] / START_CASH - 1
    rets = eq.pct_change().dropna()
    if len(rets) > 1 and rets.std() > 0:
        sharpe = (rets.mean() / rets.std()) * math.sqrt(ANNUALISATION)
    else:
        sharpe = 0.0
    cummax = eq.cummax()
    max_dd = (eq / cummax - 1).min()
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    win_rate = (wins / len(trades)) if trades else 0.0
    return {
        "total_return_pct": total_return * 100,
        "win_rate_pct": win_rate * 100,
        "max_drawdown_pct": max_dd * 100,
        "num_trades": len(trades),
        "sharpe": sharpe,
    }


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    manifest = load_manifest()
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*_ohlcv_day.csv")))
    if not files:
        print("No data CSVs found. Run fetch_data.py first.")
        return

    tokens = []
    for f in files:
        base = os.path.basename(f)
        sym = base.split("_")[0]
        df = pd.read_csv(f).sort_values("timestamp").reset_index(drop=True)
        info = manifest.get(sym, {"network": base.split("_")[1], "reserve_usd": 0})
        tokens.append((sym, info["network"], info["reserve_usd"], df))

    print(f"Loaded {len(tokens)} tokens, {len(STRATEGIES)} strategies.\n")

    per_rows = []                       # strategy x token metric rows
    trades_by_strategy = {s: [] for s in STRATEGIES}
    equity_by_strategy = {s: [] for s in STRATEGIES}

    for sym, net, reserve, df in tokens:
        close = df["close"].tolist()
        for sname, sfunc in STRATEGIES.items():
            desired = sfunc(close)
            trades, eq = run_single(df, desired, reserve)
            for t in trades:
                t["token"], t["network"] = sym, net
            trades_by_strategy[sname].extend(trades)
            equity_by_strategy[sname].append((sym, eq))
            m = metrics(eq, trades)
            per_rows.append({"strategy": sname, "token": sym, "network": net,
                             "reserve_usd": reserve, **m})

    # ---- write per-strategy trade logs ----
    for sname, trades in trades_by_strategy.items():
        path = os.path.join(RESULTS_DIR, f"trades_{sname}.csv")
        cols = ["strategy", "token", "network", "entry_date", "entry_px_exec",
                "exit_date", "exit_px_exec", "bars_held", "pnl_pct", "pnl_usd"]
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for t in trades:
                row = {"strategy": sname, **t}
                w.writerow({k: row.get(k) for k in cols})

    # ---- per strategy x token summary ----
    sdf = pd.DataFrame(per_rows)
    sdf = sdf[["strategy", "token", "network", "reserve_usd", "total_return_pct",
               "win_rate_pct", "max_drawdown_pct", "num_trades", "sharpe"]]
    sdf = sdf.round({"reserve_usd": 0, "total_return_pct": 1, "win_rate_pct": 1,
                     "max_drawdown_pct": 1, "sharpe": 2})
    sdf.to_csv(os.path.join(RESULTS_DIR, "summary.csv"), index=False)

    # ---- equal-weight portfolio per strategy ----
    all_dates = pd.to_datetime(
        sorted({d for _, _, _, df in tokens for d in df["datetime"]}))
    agg_rows = []
    for sname in STRATEGIES:
        port = pd.Series(0.0, index=all_dates)
        for sym, eq in equity_by_strategy[sname]:
            e = eq.reindex(all_dates)
            e = e.ffill().fillna(START_CASH)  # uninvested before start
            port = port + e
        trades = trades_by_strategy[sname]
        m = metrics(port, trades)
        n_tokens = len(equity_by_strategy[sname])
        m["total_return_pct"] = (port.iloc[-1] / (START_CASH * n_tokens) - 1) * 100
        agg_rows.append({"strategy": sname, "tokens": n_tokens, **m})

    adf = pd.DataFrame(agg_rows).sort_values("total_return_pct", ascending=False)
    adf = adf[["strategy", "tokens", "total_return_pct", "win_rate_pct",
               "max_drawdown_pct", "num_trades", "sharpe"]]
    adf = adf.round({"total_return_pct": 1, "win_rate_pct": 1,
                     "max_drawdown_pct": 1, "sharpe": 2})
    adf.to_csv(os.path.join(RESULTS_DIR, "summary_by_strategy.csv"), index=False)

    # ---- human-readable report ----
    lines = []
    lines.append("MEMECOIN PAPER-TRADING BACKTEST — RESULTS")
    lines.append(f"Tokens: {', '.join(sym for sym, *_ in tokens)}")
    d0 = tokens[0][3]["datetime"].iloc[0]
    d1 = tokens[0][3]["datetime"].iloc[-1]
    lines.append(f"Period: {d0} .. {d1}  ({len(tokens[0][3])} daily candles each)")
    lines.append(f"Frictions: fee {FEE_BPS}bps/side, slippage 50-400bps/side by "
                 f"liquidity, illiquidity/rug exit haircut 0-300bps.")
    lines.append("")
    lines.append("EQUAL-WEIGHT PORTFOLIO PER STRATEGY ($1,000 per token):")
    lines.append(adf.to_string(index=False))
    lines.append("")
    lines.append("PER STRATEGY x TOKEN:")
    lines.append(sdf.to_string(index=False))
    report = "\n".join(lines)
    with open(os.path.join(RESULTS_DIR, "backtest_summary.txt"), "w") as fh:
        fh.write(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
