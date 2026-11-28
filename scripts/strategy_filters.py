#!/usr/bin/env python3
"""EX-POST test of momentum and regime filters on the two books of the reliable mix.

    python scripts/strategy_filters.py

Books: FX-A (scripts/strategy_backtest.py) and CV-R, the curve calls on real 2s10s
(scripts/strategy_curves_real.py). Every filter uses only information available at the trade's
entry (prices up to the entry fixing, the edition's own model output); market data after it only
scores the trade.

Two kinds of filter:
  entry filter   a trade that fails it is not opened; the book is still vol-targeted, so the
                 remaining trades carry the risk
  regime filter  the whole FX book is scaled down (0 or 0.5) after its vol targeting, decided at
                 each edition from data before it, so the leverage cannot undo the de-risking

Rules are judged on 2008-18 (design) and checked on 2019-26. A filter is accepted only if it
improves the Sharpe ratio in both periods; everything tested is printed, because with this many
candidates a few improve one period by chance.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategy_backtest as B  # noqa: E402
import strategy_curves_real as CR  # noqa: E402
from strategy_sizing import fx_a_trades, run as fx_run  # noqa: E402

OUT = B.D / "backtest"
ED = pd.read_csv(B.D / "editions.csv").set_index("edition")
ST = pd.read_csv(B.D / "stances.csv").set_index(["edition", "cc"])
SPOT = np.log(B.FXD).ffill().values               # log USD per unit, business days
USD = B.CI["USD"]
NONUSD = [i for c, i in B.CI.items() if c != "USD"]


def stats(m: pd.Series) -> dict:
    return CR.monthly_stats(m)


def monthly(s: pd.Series) -> pd.Series:
    return s.groupby(s.index.to_period("M")).sum().loc["2008-02":"2026-10"]


# ----------------------------------------------------------------------------- FX inputs at entry
def cross_ret(t, L):
    i0 = t["i0"]; a = max(i0 - L, 0)
    lo, sh = B.CI[t["lo"]], B.CI[t["sh"]]
    return (B.CUM[i0, lo] - B.CUM[a, lo]) - (B.CUM[i0, sh] - B.CUM[a, sh])


def usd_momentum(i0, L=63):
    """change of the dollar against an equal-weighted basket of the 23 currencies, spot"""
    a = max(i0 - L, 0)
    return -float(np.nanmean(SPOT[i0, NONUSD] - SPOT[a, NONUSD]))


_DEV = B.RET[:, NONUSD] - B.RET[:, [USD]]
_V21 = pd.DataFrame(_DEV).rolling(21, min_periods=15).std().mean(axis=1).values
_V252 = pd.Series(_V21).rolling(252, min_periods=120).mean().values


def vol_ratio(i0):
    return float(_V21[i0 - 1] / _V252[i0 - 1]) if i0 > 0 and np.isfinite(_V252[i0 - 1]) else 1.0


def run_fx(trades, regime=None):
    s, _ = fx_run(trades, "base")
    if regime is not None:          # multiplier decided at each edition from data before it
        mult = pd.Series(np.nan, index=B.IDX)
        for e in B.EDS:
            mult.iloc[B.E0[e]] = regime(e, B.E0[e])
        s = s * mult.ffill().fillna(1.0).shift(1).fillna(1.0)
    return s


def main():
    trades = fx_a_trades()
    base_fx = run_fx(trades)
    fx_eq = base_fx.cumsum()                       # FX-A's own equity curve, for the equity filter
    rows = []

    def record(book, name, s_monthly, kept):
        st = stats(s_monthly)
        rows.append({"book": book, "filter": name, "kept_pct": round(100 * kept),
                     "sharpe_design": st["design"]["sharpe"], "sharpe_oos": st["oos"]["sharpe"],
                     "sharpe_all": st["all"]["sharpe"], "ret_all": st["all"]["ret"], "maxdd_all": st["all"]["maxdd"],
                     "worst_month": st["all"]["worst_m"], "up_years": st["all"]["up_years"]})
        return s_monthly

    fx_variants = {"none (FX-A)": (lambda t: True, None)}
    for L, nm in ((21, "1m"), (63, "3m"), (126, "6m"), (252, "12m")):
        fx_variants[f"cross {nm} momentum > 0 (trend)"] = (lambda t, L=L: cross_ret(t, L) > 0, None)
    for thr in (0.04, 0.08):
        fx_variants[f"skip if cross ran > {int(100*thr)}% in 3m (anti-chase)"] = (lambda t, thr=thr: cross_ret(t, 63) <= thr, None)
    fx_variants["skip if cross fell > 4% in 1m (falling knife)"] = (lambda t: cross_ret(t, 21) >= -0.04, None)
    fx_variants["skip entries when FX vol is spiking (21d > 1.3x its 1y mean)"] = (lambda t: vol_ratio(t["i0"]) <= 1.3, None)
    fx_variants["skip entries when the dollar rose > 3% in 3m"] = (lambda t: usd_momentum(t["i0"]) <= 0.03, None)
    fx_variants["skip entries when > half the central banks are cutting"] = (
        lambda t: ED.at[t["edition"], "cutting"] / (ED.at[t["edition"], "hiking"] + ED.at[t["edition"], "cutting"] + ED.at[t["edition"], "on_hold"]) <= 0.5, None)
    fx_variants["skip entries when > 40% of economies are in Disinflation"] = (
        lambda t: ED.at[t["edition"], "disinflation"] / ED.at[t["edition"], "n_clocks"] <= 0.4, None)
    # regime filters on the whole book
    fx_variants["book x0.5 while FX vol is spiking (21d > 1.3x 1y mean)"] = (lambda t: True, lambda e, i: 0.5 if vol_ratio(i) > 1.3 else 1.0)
    fx_variants["book x0.5 while the dollar is up > 3% in 3m"] = (lambda t: True, lambda e, i: 0.5 if usd_momentum(i) > 0.03 else 1.0)
    fx_variants["book x0.5 while FX-A's own 6m P&L < 0 (equity filter)"] = (
        lambda t: True, lambda e, i: 0.5 if i > 126 and fx_eq.iloc[i - 1] - fx_eq.iloc[i - 127] < 0 else 1.0)
    fx_variants["book x0 while FX-A's own 3m P&L < -5%"] = (
        lambda t: True, lambda e, i: 0.0 if i > 63 and fx_eq.iloc[i - 1] - fx_eq.iloc[i - 64] < -0.05 else 1.0)

    fx_books = {}
    for name, (keep, regime) in fx_variants.items():
        sub = [t for t in trades if keep(t)]
        s = run_fx(sub, regime)
        fx_books[name] = record("FX-A", name, monthly(s), len(sub) / len(trades))

    # ----------------------------------------------------------------------------- curve inputs
    Y = CR.load_yields()
    ctr = CR.real_calls(Y)
    sgn = {"steepener": 1, "flattener": -1}
    us = Y["US"]

    def spread_mom(t, L):
        d = Y[t["cc"]]; i0 = t["i0"]
        s0, s1 = d.y10.iloc[i0] - d.y2.iloc[i0], d.y10.iloc[max(i0 - L, 0)] - d.y2.iloc[max(i0 - L, 0)]
        return (s0 - s1) * sgn[t["call"]] if np.isfinite(s0) and np.isfinite(s1) else 0.0

    def cb_agrees(t):
        try:
            d = ST.at[(t["edition"], t["cc"]), "direction"]
        except KeyError:
            return True
        return not ((t["call"] == "steepener" and d == "hiking") or (t["call"] == "flattener" and d == "cutting"))

    def us10_mom(t, L=63):
        i0 = t["i0"]; return float(us.y10.iloc[i0] - us.y10.iloc[max(i0 - L, 0)])

    cv_variants = {"none (CV-R)": lambda t: True}
    for L, nm in ((21, "1m"), (63, "3m"), (126, "6m")):
        cv_variants[f"real spread moved with the call over {nm} (momentum)"] = (lambda t, L=L: spread_mom(t, L) > 0)
        cv_variants[f"real spread moved against the call over {nm} (reversal)"] = (lambda t, L=L: spread_mom(t, L) < 0)
    cv_variants["central bank direction agrees (no steepener while hiking, no flattener while cutting)"] = cb_agrees
    cv_variants["skip when US 10y moved > 50bp in 3m (duration regime)"] = lambda t: abs(us10_mom(t)) <= 0.5
    cv_variants["G10 markets only"] = lambda t: t["cc"] not in ("HU", "PL", "MX", "CL")

    cv_books = {}
    for name, keep in cv_variants.items():
        sub = [t for t in ctr if keep(t)]
        cv_books[name] = record("CV-R", name, CR.book(sub).loc["2008-02":"2026-10"], len(sub) / len(ctr))

    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
    for book in ("FX-A", "CV-R"):
        g = R[R.book == book]
        b0 = g.iloc[0]
        g = g.assign(both=(g.sharpe_design > b0.sharpe_design) & (g.sharpe_oos > b0.sharpe_oos))
        print(f"\n== {book}: filters (accepted = better Sharpe in BOTH periods)")
        print(g.drop(columns=["book"]).to_string(index=False))

    # ----------------------------------------------------------------------------- mixes
    def pick(book):
        g = R[R.book == book]; b0 = g.iloc[0]
        ok = g[(g.sharpe_design > b0.sharpe_design) & (g.sharpe_oos > b0.sharpe_oos)]
        # among filters better in both periods, the one with the best DESIGN Sharpe
        return ok.sort_values("sharpe_design", ascending=False).iloc[0]["filter"] if len(ok) else g.iloc[0]["filter"]
    fx_pick, cv_pick = pick("FX-A"), pick("CV-R")
    print(f"\nselected: FX-A filter = {fx_pick!r}; CV-R filter = {cv_pick!r}")
    combos = {
        "reliable mix, no filters": (fx_books["none (FX-A)"], cv_books["none (CV-R)"]),
        "FX filter only": (fx_books[fx_pick], cv_books["none (CV-R)"]),
        "curve filter only": (fx_books["none (FX-A)"], cv_books[cv_pick]),
        "both filters": (fx_books[fx_pick], cv_books[cv_pick]),
    }
    mixrows = []
    for nm, (f, c) in combos.items():
        df = pd.DataFrame({"fx": f, "cv": c}).fillna(0.0)
        m = CR.FX_WEIGHT * df.fx + (1 - CR.FX_WEIGHT) * df.cv
        st = stats(m)
        mixrows.append({"mix (65/35)": nm, "ret": st["all"]["ret"], "vol": st["all"]["vol"],
                        "sharpe_design": st["design"]["sharpe"], "sharpe_oos": st["oos"]["sharpe"],
                        "sharpe_all": st["all"]["sharpe"], "maxdd": st["all"]["maxdd"],
                        "worst_month": st["all"]["worst_m"], "up_years": st["all"]["up_years"],
                        "worst_year": st["all"]["worst_year"], "corr": round(df.fx.corr(df.cv), 2)})
    M = pd.DataFrame(mixrows)
    print("\n== mixes"); print(M.to_string(index=False))
    R.to_csv(OUT / "filters_tested.csv", index=False)
    M.to_csv(OUT / "filters_mixes.csv", index=False)
    print(f"\nwrote {(OUT / 'filters_tested.csv').relative_to(B.ROOT)}, filters_mixes.csv")


if __name__ == "__main__":
    main()
