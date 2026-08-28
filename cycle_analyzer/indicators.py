"""Transform raw panels into the cycle variables the models consume.

All cycle variables are constructed to be mean-zero, unit-ish variance and
mean-reverting by design, so the OU machinery applies uniformly:

  growth_z     (CLI - 100) scaled by its own trailing dispersion
  infl_gap     CPI y/y minus the central-bank target, in pp
  infl_z       infl_gap scaled by own trailing dispersion (handles TR vs CH)
  slope        10y yield minus policy rate, pp
  slope_z      slope vs own trailing mean/dispersion
  reer_dev     % deviation of REER from its trailing 10y average
  real_rate    policy rate minus CPI y/y
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .universe import COUNTRIES

WIN = 180          # 15y trailing window for scaling
MIN_WIN = 60


def _roll_z(df: pd.DataFrame, demean: bool = True) -> pd.DataFrame:
    """Trailing z-score column-by-column (window WIN, min MIN_WIN)."""
    m = df.rolling(WIN, min_periods=MIN_WIN).mean() if demean else 0.0
    sd = df.rolling(WIN, min_periods=MIN_WIN).std()
    return (df - m) / sd


def build_indicators(panels: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    cli, cpi = panels["cli"], panels["cpi"]
    policy, y10, reer = panels["policy"], panels["y10"], panels["reer"]

    ind: dict[str, pd.DataFrame] = {}

    # Growth cycle: CLI is amplitude-adjusted around 100; scale the deviation
    # by its own dispersion so DM and EM amplitudes are comparable.
    dev = cli - 100.0
    sd = dev.rolling(WIN, min_periods=MIN_WIN).std()
    ind["growth_z"] = (dev / sd).clip(-3.5, 3.5)

    # Inflation gap vs target (pp) and its scaled version.
    targets = pd.Series({cc: COUNTRIES[cc].infl_target for cc in cpi.columns})
    gap = cpi.sub(targets, axis=1)
    ind["infl_gap"] = gap
    gsd = gap.rolling(WIN, min_periods=MIN_WIN).std()
    ind["infl_z"] = (gap / gsd).clip(-3.5, 3.5)

    # Inflation momentum: 3m change in y/y inflation, in pp (annualized feel).
    ind["infl_mom"] = gap.diff(3)

    # Policy and real rates.
    ind["policy"] = policy
    common = [c for c in policy.columns if c in cpi.columns]
    ind["real_rate"] = policy[common] - cpi[common]

    # Curve slope where a 10y exists.
    if not y10.empty:
        common = [c for c in y10.columns if c in policy.columns]
        slope = y10[common] - policy[common]
        ind["slope"] = slope
        ind["slope_z"] = _roll_z(slope)
        ind["y10"] = y10

    # REER deviation from trailing 10y mean, in percent (log approx).
    lr = np.log(reer)
    ind["reer_dev"] = (lr - lr.rolling(120, min_periods=60).mean()) * 100.0
    ind["reer"] = reer

    return ind


def latest(df: pd.DataFrame, cc: str, max_stale_m: int = 8) -> float:
    """Latest non-NaN value for a country, if recent enough."""
    if df is None or df.empty or cc not in df.columns:
        return np.nan
    s = df[cc].dropna()
    if s.empty:
        return np.nan
    age = (df.index[-1].to_period("M") - s.index[-1].to_period("M")).n
    if age > max_stale_m:
        return np.nan
    return float(s.iloc[-1])
