"""Trading strategies for the paper backtester.

Convention (no look-ahead):
  Each strategy returns a list `desired` of target positions (1 = fully long,
  0 = flat), one per bar. `desired[i]` is the position we want to HOLD during
  bar i, and it is decided using ONLY information available up to the close of
  bar i-1. The backtester then executes any change at the OPEN of bar i.

This guarantees signals never peek at the same bar's close/high/low that they
trade on.
"""
from typing import List


def _sma(xs: List[float], end: int, n: int):
    """Simple moving average of the n closes ending at index end (inclusive)."""
    if end + 1 < n:
        return None
    window = xs[end - n + 1:end + 1]
    return sum(window) / n


def donchian_breakout(close, entry_n=20, exit_n=10):
    """(a) Momentum / breakout. Go long when yesterday's close breaks above the
    highest of the prior `entry_n` closes; exit when it breaks below the lowest
    of the prior `exit_n` closes (classic Donchian channel)."""
    n = len(close)
    desired = [0] * n
    pos = 0
    for i in range(1, n):
        j = i - 1  # last fully-known bar
        if j >= entry_n:
            hi = max(close[j - entry_n:j])
            if close[j] > hi:
                pos = 1
        if j >= exit_n:
            lo = min(close[j - exit_n:j])
            if close[j] < lo:
                pos = 0
        desired[i] = pos
    return desired


def dip_buy(close, lookback=20, dip=0.30, bounce=0.25, stop=0.35, max_hold=15):
    """(b) Dip-buy. Enter when price is `dip` below the prior `lookback` high;
    exit on a `bounce` gain, a `stop` loss, or after `max_hold` bars."""
    n = len(close)
    desired = [0] * n
    pos = 0
    entry = None
    held = 0
    for i in range(1, n):
        j = i - 1
        if pos == 0:
            if j >= lookback:
                hi = max(close[j - lookback:j])
                if hi > 0 and close[j] <= (1 - dip) * hi:
                    pos = 1
                    entry = close[j]
                    held = 0
        else:
            held += 1
            ret = close[j] / entry - 1 if entry else 0
            if ret >= bounce or ret <= -stop or held >= max_hold:
                pos = 0
                entry = None
        desired[i] = pos
    return desired


def ma_crossover(close, fast=10, slow=30):
    """(c) Moving-average crossover. Long while fast SMA > slow SMA."""
    n = len(close)
    desired = [0] * n
    pos = 0
    for i in range(1, n):
        j = i - 1
        f = _sma(close, j, fast)
        s = _sma(close, j, slow)
        if f is not None and s is not None:
            pos = 1 if f > s else 0
        desired[i] = pos
    return desired


def fomo_baseline(close, pump=0.20, hold=5):
    """(d) Naive FOMO baseline (expected to LOSE). Buy after a big single-day
    pump, then hold for `hold` bars and sell. Demonstrates chasing green candles."""
    n = len(close)
    desired = [0] * n
    pos = 0
    held = 0
    for i in range(1, n):
        j = i - 1
        if pos == 0:
            if j >= 1 and close[j - 1] > 0 and (close[j] / close[j - 1] - 1) >= pump:
                pos = 1
                held = 0
        else:
            held += 1
            if held >= hold:
                pos = 0
        desired[i] = pos
    return desired


def buy_and_hold(close):
    """Reference: buy on day 1 and hold to the end."""
    return [1] * len(close)


STRATEGIES = {
    "momentum_breakout": donchian_breakout,
    "dip_buy": dip_buy,
    "ma_crossover": ma_crossover,
    "fomo_baseline": fomo_baseline,
    "buy_and_hold": buy_and_hold,
}
