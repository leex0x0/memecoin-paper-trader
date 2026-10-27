"""Live PAPER-trading loop (simulation only — never touches a chain or a wallet).

On each pass it:
  1. reads the resolved pools from data/_fetch_manifest.csv (made by fetch_data.py),
  2. pulls the CURRENT price for each token (GeckoTerminal, DexScreener fallback),
  3. appends the price to results/live_prices.csv,
  4. runs a simple SMA-momentum rule on the prices it has logged so far,
  5. records simulated BUY/SELL trades (with the same fee/slippage frictions as
     the backtest) to results/live_paper_trades.csv, and
  6. writes a portfolio snapshot (cash + mark-to-market) to results/live_equity.csv.

It is SAFE to run with no API keys and no wallet. It can NEVER send a real
transaction — there is no signing code anywhere in this file.

Usage:
    python src/live_paper.py --once                 # one pass (good for cron)
    python src/live_paper.py --interval 900          # loop every 15 min
    python src/live_paper.py --once --sma 10 --buffer 0.0
"""
import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone

import requests

from backtest import FEE_BPS, slippage_bps
from fetch_data import GECKO_NET

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
STATE_PATH = os.path.join(RESULTS_DIR, "live_state.json")
PRICES_CSV = os.path.join(RESULTS_DIR, "live_prices.csv")
TRADES_CSV = os.path.join(RESULTS_DIR, "live_paper_trades.csv")
EQUITY_CSV = os.path.join(RESULTS_DIR, "live_equity.csv")

START_CASH = 1000.0
GECKO = "https://api.geckoterminal.com/api/v2"
GECKO_HEADERS = {"Accept": "application/json;version=20230302"}
DEX = "https://api.dexscreener.com/latest/dex"


def load_pools():
    path = os.path.join(DATA_DIR, "_fetch_manifest.csv")
    pools = []
    if not os.path.exists(path):
        return pools
    import pandas as pd
    df = pd.read_csv(path)
    for _, r in df.iterrows():
        if str(r["status"]) == "ok":
            pools.append({
                "symbol": str(r["symbol"]),
                "network": str(r["network"]),
                "pool": str(r["pool"]),
                "reserve_usd": float(r["reserve_usd"]),
            })
    return pools


def get_price(network, pool):
    """Current USD price of the pool's base token. Gecko first, DexScreener next."""
    gnet = GECKO_NET.get(network, network)
    try:
        r = requests.get(f"{GECKO}/networks/{gnet}/pools/{pool}",
                         headers=GECKO_HEADERS, timeout=20)
        if r.status_code == 200:
            a = r.json().get("data", {}).get("attributes", {})
            p = a.get("base_token_price_usd")
            if p:
                return float(p), "geckoterminal"
    except requests.RequestException:
        pass
    try:
        r = requests.get(f"{DEX}/pairs/{network}/{pool}", timeout=20)
        if r.status_code == 200:
            pairs = r.json().get("pairs") or r.json().get("pair")
            if isinstance(pairs, dict):
                pairs = [pairs]
            if pairs and pairs[0].get("priceUsd"):
                return float(pairs[0]["priceUsd"]), "dexscreener"
    except requests.RequestException:
        pass
    return None, None


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def append_row(path, header, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def recent_prices(symbol, n):
    """Return the last n logged prices for a symbol from live_prices.csv."""
    if not os.path.exists(PRICES_CSV):
        return []
    out = []
    with open(PRICES_CSV) as f:
        for row in csv.DictReader(f):
            if row["symbol"] == symbol:
                try:
                    out.append(float(row["price_usd"]))
                except ValueError:
                    pass
    return out[-n:]


def one_pass(pools, sma_n, buffer):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    state = load_state()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fee = FEE_BPS / 10_000.0
    port_equity = 0.0

    print(f"\n[{now}] live paper pass")
    for p in pools:
        sym = p["symbol"]
        price, src = get_price(p["network"], p["pool"])
        st = state.get(sym, {"cash": START_CASH, "qty": 0.0, "pos": 0,
                             "entry": None})
        if price is None:
            print(f"  {sym:7} price unavailable (skipped)")
            # still count current equity at last known (cash if flat)
            port_equity += st["cash"] if st["pos"] == 0 else 0.0
            state[sym] = st
            continue

        append_row(PRICES_CSV, ["timestamp", "symbol", "network", "price_usd", "source"],
                   [now, sym, p["network"], price, src])

        hist = recent_prices(sym, sma_n)
        slip = slippage_bps(p["reserve_usd"]) / 10_000.0
        signal = "hold"
        if len(hist) >= sma_n:
            sma = sum(hist) / len(hist)
            long_ok = price > sma * (1 + buffer)
            flat_ok = price < sma * (1 - buffer)
            if st["pos"] == 0 and long_ok:
                # simulated BUY
                buy_px = price * (1 + slip)
                st["qty"] = (st["cash"] * (1 - fee)) / buy_px
                st["cash"] = 0.0
                st["pos"] = 1
                st["entry"] = buy_px
                signal = "BUY"
                append_row(TRADES_CSV,
                           ["timestamp", "symbol", "side", "price_exec", "qty",
                            "pnl_pct", "source"],
                           [now, sym, "BUY", buy_px, st["qty"], "", src])
            elif st["pos"] == 1 and flat_ok:
                # simulated SELL
                sell_px = price * (1 - slip)
                proceeds = st["qty"] * sell_px * (1 - fee)
                pnl_pct = (proceeds / (st["qty"] * st["entry"]) - 1) * 100
                append_row(TRADES_CSV,
                           ["timestamp", "symbol", "side", "price_exec", "qty",
                            "pnl_pct", "source"],
                           [now, sym, "SELL", sell_px, st["qty"],
                            round(pnl_pct, 2), src])
                st["cash"] = proceeds
                st["qty"] = 0.0
                st["pos"] = 0
                st["entry"] = None
                signal = "SELL"

        mtm = st["cash"] if st["pos"] == 0 else st["qty"] * price
        port_equity += mtm
        state[sym] = st
        print(f"  {sym:7} ${price:<14.8g} {src:13} sma_n={len(hist)}/{sma_n} "
              f"pos={st['pos']} eq=${mtm:,.0f} {signal}")

    save_state(state)
    append_row(EQUITY_CSV, ["timestamp", "portfolio_equity_usd", "tokens"],
               [now, round(port_equity, 2), len(pools)])
    start_total = START_CASH * len(pools)
    print(f"  portfolio paper equity: ${port_equity:,.0f} "
          f"({port_equity / start_total - 1:+.1%} vs ${start_total:,.0f} start)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single pass")
    ap.add_argument("--interval", type=int, default=0,
                    help="seconds between passes (loop). Ignored with --once")
    ap.add_argument("--sma", type=int, default=10,
                    help="number of logged samples for the SMA signal")
    ap.add_argument("--buffer", type=float, default=0.0,
                    help="fractional band around the SMA to reduce churn")
    args = ap.parse_args()

    pools = load_pools()
    if not pools:
        print("No resolved pools. Run src/fetch_data.py first.")
        return

    if args.once or args.interval <= 0:
        one_pass(pools, args.sma, args.buffer)
        return
    print(f"Looping every {args.interval}s. Ctrl-C to stop. PAPER ONLY.")
    while True:
        try:
            one_pass(pools, args.sma, args.buffer)
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            break


if __name__ == "__main__":
    main()
