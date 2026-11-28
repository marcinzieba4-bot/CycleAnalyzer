#!/usr/bin/env python3
"""EX-POST: score the CV-A curve calls on real government 2s10s spreads instead of the model slope.

    python scripts/strategy_curves_real.py

The model's slope (10y yield minus policy rate, monthly averages) picks the calls; it is not a
tradable price. Here every selected call (context verdict SETUP or EARLY_TURN, as CV-A) is
traded as a DV01-neutral 2s10s position on daily official yields (data/strategy/yields/<CC>.csv):

  entry   first business day after the edition (as FX-A); hold 126 business days (6 months)
  stop    75bp against the call on the real spread
  P&L     daily change of (10y - 2y) in the call's favour, plus carry of the DV01-neutral package
          funded at the policy rate: per unit of DV01, (y2 - f)/D2 - (y10 - f)/D10 a year for a
          steepener (long 2y / short 10y), the negative for a flattener (D2 = 1.9, D10 = 8.5);
          1bp of spread per side in G10, 3bp in HU / PL / MX / CL; roll-down is not included
  size    1 / (63-day vol of daily spread changes scaled to a month, floor 10bp) per call, 12 overlapping
          tranches (two editions a month, 6-month hold); monthly book scaled to 10% vol by its
          expanding-window volatility, as CV-A

It prints, on the same calls, the model-slope result next to the real one (gains and losses
separately), the real curve book, and its mixes with FX-A, among them the reliable 65/35 mix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategy_backtest as B  # noqa: E402

YD = B.D / "yields"
D2, D10 = 1.9, 8.5
HOLD, STOP = 126, 0.75
# one-way cost in pp of spread: liquid G10 2s10s packages ~1bp, Central Europe / Latin America ~3bp
COST_EM = {"HU": 0.03, "PL": 0.03, "MX": 0.03, "CL": 0.03, "CZ": 0.03, "ZA": 0.03, "KR": 0.03}
COST_G10 = 0.01
COST = COST_G10
# Sweden's 2y/10y are benchmark-bond yields (Riksbank SWEA SEGVB2YC / SEGVB10YC): on these days the
# 2y benchmark changed (2y jumps, 10y flat), which a held position would simply roll. The spread
# change on such a day is not P&L.
ROLL_DAYS = {"SE": ["2008-06-09", "2008-09-01", "2009-12-11", "2011-06-01", "2014-01-02", "2016-03-16",
                    "2017-12-15", "2022-10-10", "2023-12-21"]}
# risk split of the reliable mix, chosen on 2008-18 only (Sharpe 0.85 / 0.86 / 0.85 at 60 / 65 / 70% FX)
FX_WEIGHT = 0.65
VOL_FLOOR = 0.10    # pp a month: a calm curve (Japan under yield-curve control) is sized as if at least 10bp


def load_yields() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(YD.glob("*.csv")):
        d = pd.read_csv(f, parse_dates=["date"]).set_index("date").sort_index()
        d = d[~d.index.duplicated(keep="last")].reindex(B.IDX).ffill(limit=5)
        out[f.stem] = d
    return out


def real_calls(Y: dict[str, pd.DataFrame]):
    pol = pd.DataFrame(B._polc.values, index=B.IDX, columns=B.CCYS)
    ccy = {cc: c.ccy for cc, c in B.COUNTRIES.items()}
    C = B.CRV[B.SEL_FINAL(B.CRV)]
    trades = []
    for r in C.itertuples():
        if r.cc not in Y or r.edition not in B.E0:
            continue
        d = Y[r.cc]
        i0 = B.E0[r.edition]
        i1 = min(i0 + HOLD, B.LAST)
        y2, y10 = d.y2.values, d.y10.values
        if not (np.isfinite(y2[i0]) and np.isfinite(y10[i0])):
            continue
        spread = y10 - y2
        roll = np.zeros(len(B.IDX), dtype=bool)
        for day in ROLL_DAYS.get(r.cc, []):
            roll[B.IDX.searchsorted(pd.Timestamp(day))] = True
        dsp = np.r_[np.nan, np.diff(spread)]
        dsp[roll] = 0.0
        hist = dsp[max(1, i0 - 62):i0 + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 40:
            continue
        vm = max(float(np.std(hist) * np.sqrt(21)), VOL_FLOOR)   # monthly vol of the spread, pp
        f = pol[ccy[r.cc]].values
        dP = np.zeros(i1 - i0)
        cum, end, out = 0.0, i1 - i0, "held"
        for k in range(1, i1 - i0 + 1):
            t = i0 + k
            if not np.isfinite(dsp[t]):
                continue
            carry = ((y2[t - 1] - f[t - 1]) / D2 - (y10[t - 1] - f[t - 1]) / D10) * r.sgn
            days = (B.IDX[t] - B.IDX[t - 1]).days
            x = dsp[t] * r.sgn + carry * days / 365
            dP[k - 1] = x
            cum += x
            if cum <= -STOP:
                end, out = k, "stop"
                break
        if i0 + end >= B.LAST and out == "held":
            out = "open"
        trades.append(dict(edition=r.edition, cc=r.cc, call=r.call, verdict=r.verdict, i0=i0, end=end,
                           dP=dP[:end], vm=vm, gain_bp=round(100 * float(dP[:end].sum())), exit=out,
                           price_bp=round(100 * float(np.nansum(dsp[i0 + 1:i0 + end + 1]) * r.sgn))))
    return trades


def book(trades, vol_target=0.10):
    pnl = np.zeros(len(B.IDX))
    for t in trades:
        w = 1.0 / t["vm"] / 12
        pnl[t["i0"] + 1:t["i0"] + 1 + len(t["dP"])] += w * t["dP"]
        c = COST_EM.get(t["cc"], COST_G10)
        pnl[t["i0"] + 1] -= w * c
        pnl[min(t["i0"] + len(t["dP"]), B.LAST)] -= w * c
    s = pd.Series(pnl, index=B.IDX)
    # monthly P&L scaled point-in-time to 10% a year by its expanding-window volatility, exactly as the
    # model-slope curve book (CV-A) is, so the two compare like for like
    m = s.groupby(s.index.to_period("M")).sum().loc["2008-02":]
    rv = m.expanding(12).std().shift(1)
    rv = rv.fillna(m.iloc[:12].std()) * np.sqrt(12)
    return m * vol_target / rv


def monthly_stats(m: pd.Series) -> dict:
    out = {}
    for nm, a, b in [("design", "2008-01", "2018-12"), ("oos", "2019-01", "2026-12"), ("all", "2008-01", "2026-12")]:
        x = m.loc[a:b]
        x = x.loc[x.ne(0).idxmax():] if x.ne(0).any() else x
        ann, vol = x.mean() * 12, x.std() * np.sqrt(12)
        eq = x.cumsum()
        yr = x.groupby(x.index.year).sum()
        out[nm] = dict(ret=round(100 * ann, 1), vol=round(100 * vol, 1), sharpe=round(ann / vol, 2),
                       maxdd=round(100 * (eq - eq.cummax()).min(), 1), worst_m=round(100 * x.min(), 1),
                       up_years=f"{(yr > 0).sum()}/{len(yr)}", worst_year=round(100 * yr.min(), 1))
    return out


def main():
    Y = load_yields()
    print("real 2y/10y data:", {cc: f"{d.dropna().index.min().date()}..{d.dropna().index.max().date()}" for cc, d in Y.items()})
    tr = real_calls(Y)
    T = pd.DataFrame([{k: v for k, v in t.items() if k not in ("dP",)} for t in tr])
    # model-slope outcome of the same calls (CV-A trade log)
    _, cvlog = B.curve_book(B.SEL_FINAL, log=True)
    T = T.merge(cvlog[["edition", "cc", "gain_bp"]].rename(columns={"gain_bp": "model_bp"}), on=["edition", "cc"], how="left")
    T["era"] = np.where(T.edition.str[:4].astype(int) <= 2018, "2008-18", "2019-26")
    print(f"\n{len(T)} selected calls in {T.cc.nunique()} countries with real data "
          f"(of {len(B.CRV[B.SEL_FINAL(B.CRV)])} CV-A calls in all countries)")
    print("\ncall by call, model slope vs real 2s10s (bp, 6 months or stop):")
    for era, g in [("all", T)] + list(T.groupby("era")):
        w, l = g[g.model_bp > 0], g[g.model_bp <= 0]
        print(f"  {era}: n={len(g)}  model {g.model_bp.mean():+.0f}bp ({(g.model_bp > 0).mean():.0%} up) | real {g.gain_bp.mean():+.0f}bp "
              f"({(g.gain_bp > 0).mean():.0%} up) | corr {g.model_bp.corr(g.gain_bp):.2f} | "
              f"model winners: model {w.model_bp.mean():+.0f} vs real {w.gain_bp.mean():+.0f} | "
              f"model losers: model {l.model_bp.mean():+.0f} vs real {l.gain_bp.mean():+.0f}")
    big = T.gain_bp.nsmallest(5)
    print("  worst real outcomes:", T.loc[big.index, ["edition", "cc", "call", "model_bp", "gain_bp", "exit"]].to_dict("records"))
    print("  by country (real bp, hit):", T.groupby("cc").gain_bp.agg(lambda s: f"{s.mean():+.0f} {int(100*(s>0).mean())}% n{len(s)}").to_dict())
    # books
    rm = book(tr).loc["2008-02":"2026-10"]
    # model-slope CV-A restricted to the same countries, for an apples-to-apples comparison
    cc_set = set(T.cc)
    model_same = B.curve_book(lambda c: B.SEL_FINAL(c) & c.cc.isin(cc_set))
    fxm = B.monthly(B.fx_final()).loc["2008-02":"2026-10"]
    model_all = B.curve_book(B.SEL_FINAL).loc["2008-02":"2026-10"]
    df = pd.DataFrame({"fx": fxm, "real_curves": rm, "model_curves_same": model_same.loc["2008-02":"2026-10"],
                       "model_curves_all": model_all}).fillna(0.0)
    df["mix_real"] = 0.5 * df.fx + 0.5 * df.real_curves
    df["mix_reliable"] = FX_WEIGHT * df.fx + (1 - FX_WEIGHT) * df.real_curves
    print("\nrisk split FX / real curves (Sharpe 2008-18 / 2019-26):", {f"{int(100*a)}/{int(100*(1-a))}":
          tuple(monthly_stats(a * df.fx + (1 - a) * df.real_curves)[e]["sharpe"] for e in ("design", "oos"))
          for a in (1.0, 0.8, 0.7, 0.6, 0.5, 0.4)})
    df["mix_model"] = 0.5 * df.fx + 0.5 * df.model_curves_all
    print("\ncorrelation FX-A vs real curve book:", round(df.fx.corr(df.real_curves), 2))
    rows = []
    for k, lab in [("model_curves_all", "Curve book, model slope, all 17 countries (CV-A as reported)"),
                   ("model_curves_same", f"Curve book, model slope, the {len(cc_set)} countries with real data"),
                   ("real_curves", f"Curve book, REAL 2s10s, {len(cc_set)} countries"),
                   ("fx", "FX-A"), ("mix_model", "50/50 mix with the model-slope curve book (as reported)"),
                   ("mix_real", "50/50 mix with the REAL 2s10s curve book"),
                   ("mix_reliable", f"RELIABLE MIX: {int(100*FX_WEIGHT)}% FX-A / {int(100*(1-FX_WEIGHT))}% real 2s10s curve book")]:
        st = monthly_stats(df[k])
        rows.append({"book": lab, **{f"{e}_{m}": v for e, d in st.items() for m, v in d.items()}})
    R = pd.DataFrame(rows).set_index("book")
    cols = ["all_ret", "all_vol", "all_sharpe", "design_sharpe", "oos_sharpe", "all_maxdd", "all_worst_m", "all_up_years", "all_worst_year"]
    pd.set_option("display.width", 250)
    print(R[cols].to_string())
    out = B.D / "backtest"
    T.drop(columns=["i0", "end", "vm"]).to_csv(out / "curve_trades_real.csv", index=False)
    df.round(6).to_csv(out / "monthly_returns_real_curves.csv", index_label="month")
    R.to_csv(out / "curve_real_summary.csv")
    print(f"\nwrote {out.relative_to(B.ROOT)}/curve_trades_real.csv, monthly_returns_real_curves.csv, curve_real_summary.csv")


if __name__ == "__main__":
    main()
