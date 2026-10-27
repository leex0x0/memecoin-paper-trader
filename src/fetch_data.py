"""Fetch REAL OHLCV data for the memecoin basket.

Primary source : GeckoTerminal free OHLCV endpoint (daily candles, no key).
Fallback       : DexScreener free API (pool resolution + current price).

We do NOT fabricate any price data. If a token/pool cannot be fetched we skip
it and record the reason in data/_fetch_manifest.csv so the README can be honest.

Notes learned from the live APIs:
  * GeckoTerminal uses the network slug "eth" for Ethereum (not "ethereum").
  * The OHLCV endpoint prices the pool's BASE token, so we must pick a pool
    where our target token is the base token (otherwise we'd chart the wrong
    asset).
  * A single daily call returns ~6 months of candles; we paginate backwards
    with `before_timestamp` to pull the full available history.

Usage:
    python src/fetch_data.py                 # daily candles, full history
    python src/fetch_data.py --limit 1000 --max-pages 8
"""
import argparse
import csv
import os
import time
from datetime import datetime, timezone

import requests

from tokens import BASKET

GECKO = "https://api.geckoterminal.com/api/v2"
GECKO_HEADERS = {"Accept": "application/json;version=20230302"}
DEX = "https://api.dexscreener.com/latest/dex"

# tokens.py uses DexScreener-style slugs; map to GeckoTerminal slugs here.
GECKO_NET = {"ethereum": "eth", "eth": "eth", "solana": "solana", "base": "base"}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

MIN_INTERVAL = 2.6  # polite minimum gap between GeckoTerminal calls (seconds)
_last_call = [0.0]


def _throttle():
    gap = time.time() - _last_call[0]
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_call[0] = time.time()


def norm_addr(network, address):
    """EVM addresses are case-insensitive; Solana mints are case-sensitive."""
    return address if network == "solana" else address.lower()


def gecko_get(path, params=None, max_tries=6):
    url = f"{GECKO}{path}"
    delay = 5.0
    for attempt in range(1, max_tries + 1):
        _throttle()
        try:
            r = requests.get(url, params=params, headers=GECKO_HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"   gecko network error ({e}); retry {attempt}/{max_tries}")
            time.sleep(delay)
            delay = min(delay * 1.8, 60)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            wait = float(ra) if (ra and ra.isdigit() and float(ra) > 0) else delay
            print(f"   gecko HTTP {r.status_code}; waiting {wait:.0f}s "
                  f"(try {attempt}/{max_tries})")
            time.sleep(wait)
            delay = min(delay * 1.8, 60)
            continue
        print(f"   gecko HTTP {r.status_code} for {path}")
        return None
    return None


def resolve_pool(network, address):
    """Return (gecko_net, pool_address, pool_name, reserve_usd, source) for the
    most liquid pool where `address` is the BASE token."""
    gnet = GECKO_NET.get(network, network)
    addr = norm_addr(network, address)

    j = gecko_get(f"/networks/{gnet}/tokens/{addr}/pools")
    if j and j.get("data"):
        base_pools = []
        for p in j["data"]:
            bt = (p.get("relationships", {}).get("base_token", {})
                  .get("data", {}).get("id", "")) or ""
            if addr.lower() in bt.lower():
                base_pools.append(p)
        pools = base_pools or j["data"]
        best = max(pools, key=lambda p: float(
            p["attributes"].get("reserve_in_usd") or 0))
        a = best["attributes"]
        note = "geckoterminal" if base_pools else "geckoterminal(base-token-fallback)"
        return (gnet, a["address"], a.get("name", "?"),
                float(a.get("reserve_in_usd") or 0), note)

    # Fallback: DexScreener for pool resolution
    try:
        r = requests.get(f"{DEX}/tokens/{address}", timeout=30)
        if r.status_code == 200:
            pairs = [p for p in (r.json().get("pairs") or [])
                     if p.get("chainId") == network
                     and (p.get("baseToken", {}).get("address", "").lower()
                          == address.lower())]
            if pairs:
                best = max(pairs, key=lambda p: float(
                    (p.get("liquidity") or {}).get("usd") or 0))
                return (gnet, best["pairAddress"],
                        f"{best['baseToken']['symbol']}/{best['quoteToken']['symbol']}",
                        float((best.get("liquidity") or {}).get("usd") or 0),
                        "dexscreener")
    except requests.RequestException:
        pass
    return None


def fetch_ohlcv(gnet, pool, limit=1000, max_pages=8):
    """Paginate backwards to pull as much daily history as the free API gives.
    Returns list of [ts,o,h,l,c,v]."""
    all_rows = {}
    before = None
    for page in range(max_pages):
        params = {"aggregate": 1, "limit": limit, "currency": "usd"}
        if before is not None:
            params["before_timestamp"] = before
        j = gecko_get(f"/networks/{gnet}/pools/{pool}/ohlcv/day", params=params)
        if not j:
            break
        rows = j.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        if not rows:
            break
        new = {int(r[0]): r for r in rows if int(r[0]) not in all_rows}
        if not new:
            break
        all_rows.update(new)
        oldest = min(r[0] for r in rows)
        before = oldest - 1
    return sorted(all_rows.values(), key=lambda r: r[0])


def save_csv(symbol, network, rows):
    rows = sorted(rows, key=lambda r: r[0])
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{symbol}_{network}_ohlcv_day.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "datetime", "open", "high", "low", "close", "volume"])
        for ts, o, h, l, c, v in rows:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            w.writerow([ts, dt, o, h, l, c, v])
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--max-pages", type=int, default=12)
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    manifest = []
    for symbol, network, address in BASKET:
        print(f"\n=== {symbol} ({network}) ===")
        res = resolve_pool(network, address)
        if not res:
            print("   SKIP: could not resolve a pool")
            manifest.append([symbol, network, "", "", 0, "skipped: no pool", 0, "", ""])
            continue
        gnet, pool, name, reserve, src = res
        print(f"   pool {pool} ({name}) reserve≈${reserve:,.0f} via {src}")
        rows = fetch_ohlcv(gnet, pool, args.limit, args.max_pages)
        if not rows:
            print("   SKIP: no OHLCV returned")
            manifest.append([symbol, network, pool, name, reserve,
                             "skipped: no ohlcv", 0, "", ""])
            continue
        path = save_csv(symbol, network, rows)
        first = datetime.fromtimestamp(rows[0][0], tz=timezone.utc).strftime("%Y-%m-%d")
        last = datetime.fromtimestamp(rows[-1][0], tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"   saved {len(rows)} candles ({first}..{last}) -> {os.path.relpath(path)}")
        manifest.append([symbol, network, pool, name, round(reserve, 2),
                         "ok", len(rows), first, last])

    mpath = os.path.join(DATA_DIR, "_fetch_manifest.csv")
    with open(mpath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "network", "pool", "pool_name", "reserve_usd",
                    "status", "candles", "first_date", "last_date"])
        w.writerows(manifest)
    print(f"\nManifest -> {os.path.relpath(mpath)}")
    ok = sum(1 for m in manifest if m[5] == "ok")
    print(f"Fetched {ok}/{len(BASKET)} tokens successfully.")


if __name__ == "__main__":
    main()
