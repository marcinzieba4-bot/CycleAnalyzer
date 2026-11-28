#!/usr/bin/env python3
"""EX-POST test of position-management rules inside each FX-A trade.

    python scripts/strategy_sizing.py

The trades are exactly FX-A's (scripts/strategy_backtest.py): same crosses, entries, signal-fade
and 12-month exits, catastrophe stop at -2 quarterly sigmas, costs and 10% book volatility
target. Only the size held inside each trade changes, day by day, with the trade's own price path
(cumulative return incl. carry since entry). A "step" is k quarterly sigmas of the cross
(sigma_q = 63-day vol x sqrt(63/252)), so one rule fits every pair. Level = steps moved from entry,
truncated toward zero (one full step is needed before anything changes).

Families
  grid        start at U0 units; give back d units per step up (re-bought if price comes back);
              add d units per step down, until the stop        (the "scale out / average down" grid)
  take-profit only the scale-out half of the grid
  avg-down    only the scale-in half of the grid
  pyramid     start at 1 unit; +1 unit per step up, cap Umax; units follow the current level, so
              they are cut again when price falls back
  pyr-trail   start at 1 unit; +1 unit per new step high (ratchet, cap Umax); close the whole trade
              when price falls `trail` steps below its best level

Each variant's book is vol-targeted like FX-A, so Sharpe and drawdowns compare risk for risk.
Rules are judged on 2008-18 (design) and checked on 2019-26.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategy_backtest as B  # noqa: E402

OUT = B.D / "backtest"


def fx_a_trades(persist=6, min_hold=63, max_hold=252, stop_sigma=2.0, n=3):
    """FX-A's trades with their daily paths (identical selection, exits and stop to fx_final)."""
    sel, rk = B.pick_crosses(B.score_final, n=n), B.ranked(B.score_final)
    out = []
    for k, e in enumerate(B.EDS):
        i0 = B.E0[e]
        for lo, sh in sel[e]:
            i1 = min(i0 + max_hold, B.LAST)
            for e2 in B.EDS[k + 1:]:
                j = B.E0[e2]
                if j >= i1:
                    break
                if j - i0 >= min_hold and (lo not in rk[e2][:persist] or sh not in rk[e2][-persist:]):
                    i1 = j
                    break
            v = B.xvol(lo, sh, i0)
            p = B.path(lo, sh, i0, i1)
            kx = B.stop_exit(p, stop_sigma, v)
            out.append(dict(edition=e, lo=lo, sh=sh, i0=i0, kx=kx, v=v, p=p[:kx + 1],
                            w=(1 / (n * 12.6)) * 0.10 / v))
    return out


def level(p, s):
    return np.trunc(p / s).astype(int)


def units(scheme: str, p: np.ndarray, s: float, **kw) -> tuple[np.ndarray, int]:
    """Units held at the end of each day 0..L-1 (earning day k+1), relative to one base unit,
    and the last day held (a trailing exit can end the trade early)."""
    L = len(p) - 1
    lv = level(p[:L], s)
    if scheme == "base":
        return np.ones(L), L
    if scheme in ("grid", "take-profit", "avg-down"):
        U0, d = kw.get("U0", 10), kw.get("d", 1)
        up, down = np.maximum(lv, 0), np.maximum(-lv, 0)
        u = np.full(L, float(U0))
        if scheme != "avg-down":
            u -= d * up
        if scheme != "take-profit":
            u += d * down
        return np.maximum(u, 0.0) / U0, L
    if scheme == "pyramid":
        return np.minimum(1 + np.maximum(lv, 0), kw.get("Umax", 4)).astype(float), L
    if scheme == "pyr-trail":
        Umax, trail = kw.get("Umax", 4), kw.get("trail", 1)
        best = np.maximum.accumulate(np.maximum(lv, 0))
        u = np.minimum(1 + best, Umax).astype(float)
        out = np.where((best >= 1) & (p[:L] < (best - trail) * s))[0]
        if len(out):
            end = int(out[0])       # close at the end of that day
            return u[:end], end
        return u, L
    raise ValueError(scheme)


def run(trades, scheme, k=0.5, **kw):
    W = np.zeros((len(B.IDX), len(B.CCYS)))
    held, ends, rets = [], [], []
    for t in trades:
        s = k * t["v"] * np.sqrt(63 / 252)
        u, end = units(scheme, t["p"], s, **kw)
        if end <= 0:
            continue
        i0 = t["i0"]
        W[i0:i0 + end, B.CI[t["lo"]]] += t["w"] * u
        W[i0:i0 + end, B.CI[t["sh"]]] -= t["w"] * u
        held.append(u.mean())
        dr = np.diff(t["p"][:end + 1])
        rets.append(float((u * dr).sum()))
        ends.append(end)
    gross = np.r_[0.0, (W[:-1] * B.RET[1:]).sum(1)]
    dW = np.abs(np.diff(np.vstack([np.zeros(len(B.CCYS)), W]), axis=0))
    turn = (dW * B.COST).sum(1)
    roll = (np.abs(W) * B.COST).sum(1) / 63
    raw = pd.Series(gross - np.r_[0.0, turn[1:]] - np.r_[0.0, roll[:-1]], index=B.IDX)
    rv = raw.rolling(63, min_periods=21).std().shift(1) * np.sqrt(252)
    lev = (0.10 / rv).clip(upper=4.0)
    lv = pd.Series(np.nan, index=B.IDX)
    for d in B.EDS:
        lv.iloc[B.E0[d]] = lev.iloc[B.E0[d]]
    s = raw * lv.ffill().fillna(0.0)
    extra = dict(avg_units=float(np.mean(held)), avg_days=float(np.mean(ends)),
                 trade_win=float(np.mean(np.array(rets) > 0)),
                 # notional traded per year, in multiples of the average gross position
                 turnover=float(dW.sum() / np.abs(W).sum() * 252))
    return s, extra


VARIANTS = [("base", "FX-A as is (constant size)", {})]
for k in (0.25, 0.5, 1.0):
    for d in (1, 2):
        VARIANTS.append(("grid", f"grid 10u, -{d}u per step up / +{d}u per step down, step {k} sigma_q", dict(k=k, d=d)))
    VARIANTS.append(("take-profit", f"take-profit only, -1u per step up, step {k} sigma_q", dict(k=k, d=1)))
    VARIANTS.append(("avg-down", f"average-down only, +1u per step down, step {k} sigma_q", dict(k=k, d=1)))
    for um in (3, 5):
        VARIANTS.append(("pyramid", f"pyramid 1u, +1u per step up, max {um}u, step {k} sigma_q", dict(k=k, Umax=um)))
    for tr in (1, 2):
        VARIANTS.append(("pyr-trail", f"pyramid 1u +1u per new high, max 4u, exit {tr} step(s) off best, step {k} sigma_q",
                         dict(k=k, Umax=4, trail=tr)))


def continuation(trades, k=0.5):
    """What a trade does after its first move of one step: the rest of its return, per unit,
    once it is first up k sigma_q, and once it is first down k sigma_q (until its normal exit)."""
    out = {"up": [], "down": [], "all": []}
    for t in trades:
        s = k * t["v"] * np.sqrt(63 / 252)
        p = t["p"]
        out["all"].append(p[-1])
        for side, hit in (("up", np.where(p >= s)[0]), ("down", np.where(p <= -s)[0])):
            if len(hit):
                out[side].append(p[-1] - p[hit[0]])
    return {k2: (len(v), 100 * float(np.mean(v)), 100 * float(np.mean(np.array(v) > 0))) for k2, v in out.items()}


def main():
    trades = fx_a_trades()
    for k in (0.5, 1.0):
        c = continuation(trades, k)
        print(f"after the first {k} sigma_q move: " + "; ".join(
            f"{side}: n={n}, rest of trade {m:+.2f}% (positive {w:.0f}%)" for side, (n, m, w) in c.items()))
    rows = []
    for scheme, label, kw in VARIANTS:
        s, x = run(trades, scheme, **kw)
        t = B.summary(s, 252)
        rows.append({"scheme": scheme, "variant": label,
                     "sharpe_design": t.loc["Sharpe"].iloc[0], "sharpe_oos": t.loc["Sharpe"].iloc[1],
                     "sharpe_all": t.loc["Sharpe"].iloc[2], "ret_all": t.loc["return %/yr"].iloc[2],
                     "maxdd_all": t.loc["max DD %"].iloc[2], "worst_year": t.loc["worst year %"].iloc[2],
                     "pos_years": t.loc["positive years"].iloc[2],
                     "avg_units": round(x["avg_units"], 2), "avg_days": round(x["avg_days"]),
                     "trade_win_pct": round(100 * x["trade_win"]), "turnover_x": round(x["turnover"], 1)})
    r = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    r.to_csv(OUT / "sizing_variants.csv", index=False)
    pd.set_option("display.width", 220)
    print(r.drop(columns=["scheme"]).to_string(index=False))
    base = r.iloc[0]
    print("\nvs base (Sharpe design / out-of-sample):", f"{base.sharpe_design:+.2f} / {base.sharpe_oos:+.2f}")
    better = r[(r.sharpe_design > base.sharpe_design) & (r.sharpe_oos > base.sharpe_oos)]
    print("variants better in BOTH periods:", len(better))
    print(better[["variant", "sharpe_design", "sharpe_oos", "maxdd_all"]].to_string(index=False) if len(better) else "  none")
    print(f"\nwrote {(OUT / 'sizing_variants.csv').relative_to(B.ROOT)}")


if __name__ == "__main__":
    main()
