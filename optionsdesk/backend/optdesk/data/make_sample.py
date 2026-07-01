"""
Generate a small synthetic-but-realistic option store (full greeks) so the
whole pipeline runs end-to-end before real data lands. Self-contained BS so it
has no intra-package dependencies.

    python -m optdesk.data.make_sample
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import CHAINS_DIR, EQUITY_DIR, UNIVERSE_DIR

N = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
n = lambda x: math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_greeks(S, K, T, r, sigma, call):
    if T <= 0 or sigma <= 0 or S <= 0:
        intrinsic = max(0.0, (S - K) if call else (K - S))
        return intrinsic, (1.0 if call and S > K else (-1.0 if not call and S < K else 0.0)), 0, 0, 0, 0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if call:
        price = S * N(d1) - K * math.exp(-r * T) * N(d2)
        delta = N(d1)
        theta = (-S * n(d1) * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * N(d2)) / 365
        rho = K * T * math.exp(-r * T) * N(d2) / 100
    else:
        price = K * math.exp(-r * T) * N(-d2) - S * N(-d1)
        delta = N(d1) - 1.0
        theta = (-S * n(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * N(-d2)) / 365
        rho = -K * T * math.exp(-r * T) * N(-d2) / 100
    gamma = n(d1) / (S * sigma * math.sqrt(T))
    vega = S * n(d1) * math.sqrt(T) / 100
    return price, delta, gamma, theta, vega, rho


def _friday_on_or_after(d: date) -> date:
    """Next Friday on/after ``d`` — the fixed expiry grid."""
    return d + timedelta(days=(4 - d.weekday()) % 7)


def gen_ticker(ticker: str, seed: int, s0: float, vol: float, drift: float,
               start: date, days: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    S = s0
    r = 0.045
    inst_vol = vol  # instantaneous vol mean-reverts around `vol` (stochastic vol)
    dates = [start + timedelta(days=i) for i in range(days) if (start + timedelta(days=i)).weekday() < 5]
    for d in dates:
        # mean-reverting stochastic vol (vol-of-vol) so IV is a noisy, imperfect
        # forecast of realized vol -> options are sometimes mis-priced, like reality
        inst_vol += 5.0 * (vol - inst_vol) / 252 + 0.6 * vol / math.sqrt(252) * rng.standard_normal()
        inst_vol = float(min(max(inst_vol, 0.08), 1.5))
        # diffusive GBM step on the realized (instantaneous) vol
        z = rng.standard_normal()
        S *= math.exp((drift - 0.5 * inst_vol**2) / 252 + inst_vol / math.sqrt(252) * z)
        # occasional jumps (gap risk) NOT fully priced into IV -> short premium can lose
        if rng.random() < 0.02:
            S *= math.exp(rng.normal(-0.04, 0.06))
        # quoted IV tracks current vol with a small risk premium + estimation noise
        quote_vol = max(0.06, inst_vol * 1.05 + rng.normal(0, 0.015))
        # FIXED Friday expiry grid out to ~120 days. Pinning expiries to calendar
        # dates (instead of rolling asof+dte daily) means the same contract
        # exists on consecutive days — required for the engine's T+1 fills to
        # re-locate legs, and how real listed options behave.
        expiries = sorted({_friday_on_or_after(d + timedelta(days=dte))
                           for dte in (7, 14, 30, 60, 90, 120)})
        for expiry in expiries:
            dte = (expiry - d).days
            if dte <= 0:
                continue
            T = dte / 365
            atm = round(S / 5) * 5
            for k in range(-6, 7):
                K = max(1.0, atm + k * 2.5)
                # smile
                moneyness = math.log(K / S)
                sigma = quote_vol * (1 + 0.6 * moneyness**2 + 0.04 * (-moneyness))
                sigma = max(0.05, sigma)
                for call in (True, False):
                    price, delta, gamma, theta, vega, rho = bs_greeks(S, K, T, r, sigma, call)
                    half_spread = max(0.02, 0.01 * price + 0.01)
                    mid = max(0.01, price)
                    rows.append(dict(
                        asof=d, expiry=expiry, strike=round(K, 2),
                        option_type="C" if call else "P",
                        bid=round(max(0.01, mid - half_spread), 2),
                        ask=round(mid + half_spread, 2),
                        last=round(mid, 2),
                        volume=int(abs(rng.normal(200, 150)) * math.exp(-abs(moneyness) * 4)),
                        open_interest=int(abs(rng.normal(2000, 1200))),
                        implied_volatility=round(sigma, 4),
                        delta=round(delta, 4), gamma=round(gamma, 5),
                        theta=round(theta, 4), vega=round(vega, 4), rho=round(rho, 4),
                        underlying_close=round(S, 2),
                    ))
    return pd.DataFrame(rows)


def main():
    CHAINS_DIR.mkdir(parents=True, exist_ok=True)
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    EQUITY_DIR.mkdir(parents=True, exist_ok=True)
    start = date(2023, 1, 2)
    specs = [
        ("AAPL", 1, 180.0, 0.26, 0.10, None),
        ("MSFT", 2, 330.0, 0.24, 0.12, None),
        ("XYZ", 3, 45.0, 0.55, -0.20, date(2023, 9, 15)),  # delists mid-history
    ]
    uni = []
    for ticker, seed, s0, vol, drift, delisted in specs:
        days = 180 if delisted else 360
        df = gen_ticker(ticker, seed, s0, vol, drift, start, days)
        if delisted:
            df = df[df["asof"] <= delisted]
        df.to_parquet(CHAINS_DIR / f"{ticker}.parquet", index=False)
        # matching equity OHLCV store so signal gates + regime analytics run
        # on the sample exactly as they do on imported real data
        eq = (df.groupby("asof")["underlying_close"].first().reset_index()
                .rename(columns={"asof": "date", "underlying_close": "close"}))
        for c in ("open", "high", "low"):
            eq[c] = eq["close"]
        eq["adj_close"] = eq["close"]
        eq["volume"] = 1_000_000
        eq["date"] = eq["date"].astype(str)
        eq[["date", "open", "high", "low", "close", "adj_close", "volume"]].to_parquet(
            EQUITY_DIR / f"{ticker}.parquet", index=False)
        uni.append(dict(ticker=ticker, listed=start,
                        delisted=delisted or "", sector="Tech"))
        print(f"  {ticker}: {len(df):,} rows (+{len(eq)} equity days)")
    pd.DataFrame(uni).to_csv(UNIVERSE_DIR / "universe.csv", index=False)
    print(f"Sample store written to {CHAINS_DIR}")


if __name__ == "__main__":
    main()
