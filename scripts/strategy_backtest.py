#!/usr/bin/env python3
"""EX-POST backtest of the CycleAnalyzer trading rules (uses later market data by design).

    python scripts/strategy_extract.py     # 1. edition model outputs -> data/strategy/*.csv
    python scripts/strategy_market.py      # 2. market data            -> data/strategy/*_daily.csv
    python scripts/strategy_backtest.py    # 3. this: baselines, final rules, robustness, trade logs
    python scripts/strategy_backtest.py --live   # today's signals from data/raw (after run_analysis --refresh)

Every signal comes from the point-in-time editions (data/retro/<date>/, re-run by
strategy_extract.py, checked against each published page). Market data only scores them.
Design period 2008-2018, out-of-sample check 2019-2026. Rules: reports/strategy/STRATEGY.md.

FX P&L: long A / short B, entered at the BIS daily fixing on the Monday after the edition,
daily log spot change + daily policy-rate carry (proxy for the forward points). Costs:
one-way 3bp G10, 6bp CEE, 10bp other EM on every change in position, plus one one-way cost
per quarter held (forward rolls). Curve P&L: monthly change of (10y - policy rate) from the
edition month, signed by the call, 2bp of slope per side.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
D = ROOT / "data" / "strategy"
OUT = D / "backtest"

# ----------------------------------------------------------------------------- market data
FXD = pd.read_csv(D / "fx_daily.csv", index_col=0, parse_dates=True)
IDX = pd.bdate_range(FXD.index.min(), FXD.index.max())
FXD = FXD.reindex(IDX).ffill(limit=5)
FXD["USD"] = 1.0
CCYS = list(FXD.columns)
CI = {c: i for i, c in enumerate(CCYS)}
from cycle_analyzer.universe import COUNTRIES  # noqa: E402
CC_OF = {c.ccy: cc for cc, c in COUNTRIES.items()}
_pol = pd.read_csv(D / "policy_daily.csv", index_col=0, parse_dates=True)
_pol = _pol.reindex(pd.date_range(_pol.index.min(), IDX.max())).ffill()
_polc = pd.DataFrame({k: _pol[CC_OF[k]] for k in CCYS}).reindex(IDX).ffill()
_gap = np.r_[1, np.diff(IDX.values).astype("timedelta64[D]").astype(int)]
CARRY = (_polc.shift(1).mul(_gap, axis=0) / 36500.0).fillna(0.0).values
RET = np.log(FXD).diff().fillna(0.0).values + CARRY           # per-currency daily total return
CUM = np.cumsum(RET, axis=0)
G10 = {"EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "USD"}
CEE = {"PLN", "HUF", "CZK"}
COST = np.array([3e-4 if c in G10 else (6e-4 if c in CEE else 1e-3) for c in CCYS])

# ----------------------------------------------------------------------------- edition outputs
FXT = pd.read_csv(D / "fx.csv")
FXT["fund"] = FXT.penalty > -1.0                    # the framework's credibility screen
CRS = pd.read_csv(D / "crosses.csv")
CRV = pd.read_csv(D / "curves.csv")
EDS = sorted(FXT.edition.unique())
E0 = {d: int(IDX.searchsorted(pd.Timestamp(d) + pd.Timedelta(days=1))) for d in EDS}
LAST = len(IDX) - 1
_RV = pd.DataFrame(RET - RET[:, [CI["USD"]]], index=IDX, columns=CCYS).rolling(63, min_periods=40).std() * np.sqrt(252)
FXT["vol"] = [_RV.values[E0[d], CI[c]] for d, c in zip(FXT.edition, FXT.ccy)]
VOL_FLOOR = 0.04


def xvol(lo, sh, i0, n=63):
    r = RET[max(i0 - n, 0):i0, CI[lo]] - RET[max(i0 - n, 0):i0, CI[sh]]
    return max(float(r.std() * np.sqrt(252)), VOL_FLOOR)


def path(lo, sh, i0, i1):
    return (CUM[i0:i1 + 1, CI[lo]] - CUM[i0, CI[lo]]) - (CUM[i0:i1 + 1, CI[sh]] - CUM[i0, CI[sh]])


def book(trades, vol_target=0.10):
    """trades: dict(lo, sh, i0, i1, w). Net daily weights -> P&L after costs; book leverage
    reset at each edition to vol_target / trailing-63d realized vol (point-in-time)."""
    W = np.zeros((len(IDX), len(CCYS)))
    for t in trades:
        if t["i1"] > t["i0"]:
            W[t["i0"]:t["i1"], CI[t["lo"]]] += t["w"]
            W[t["i0"]:t["i1"], CI[t["sh"]]] -= t["w"]
    gross = np.r_[0.0, (W[:-1] * RET[1:]).sum(1)]
    turn = (np.abs(np.diff(np.vstack([np.zeros(len(CCYS)), W]), axis=0)) * COST).sum(1)
    roll = (np.abs(W) * COST).sum(1) / 63
    s = pd.Series(gross - np.r_[0.0, turn[1:]] - np.r_[0.0, roll[:-1]], index=IDX)
    if vol_target:
        rv = s.rolling(63, min_periods=21).std().shift(1) * np.sqrt(252)
        lev = (vol_target / rv).clip(upper=4.0)
        lv = pd.Series(np.nan, index=IDX)
        for d in EDS:
            lv.iloc[E0[d]] = lev.iloc[E0[d]]
        s = s * lv.ffill().fillna(0.0)
    return s


def stop_exit(p, stop_sigma, vol):
    """first day the trade is down stop_sigma quarterly sigmas (vol * sqrt(63/252))"""
    lvl = -stop_sigma * vol * np.sqrt(63 / 252)
    hit = np.where(p[1:] <= lvl)[0]
    return (1 + int(hit[0])) if len(hit) else len(p) - 1


# ----------------------------------------------------------------------------- FX rules
def score_published(g):
    return g.total


def score_final(g):
    """the editions' engines minus the clock (cycle) engine, per unit of currency risk"""
    return (g.total - g.cycle) / (g.vol.clip(lower=VOL_FLOOR) / 0.10)


def ranked(score):
    return {e: g[g.fund].assign(s=score(g[g.fund])).sort_values("s", ascending=False).ccy.tolist()
            for e, g in FXT.groupby("edition")}


def pick_crosses(score, n=3, depth=6):
    """greedy by score gap among the top/bottom `depth` credible currencies, distinct legs"""
    out = {}
    for e, g in FXT.groupby("edition"):
        g = g[g.fund].assign(s=lambda x: score(x)).sort_values("s", ascending=False)
        L, S = g.head(depth), g.tail(depth)[::-1]
        pairs = sorted(((a.s - b.s, a.ccy, b.ccy) for a in L.itertuples() for b in S.itertuples()
                        if a.ccy != b.ccy), reverse=True)
        used, pick = set(), []
        for _, lo, sh in pairs:
            if lo in used or sh in used:
                continue
            pick.append((lo, sh)); used |= {lo, sh}
            if len(pick) == n:
                break
        out[e] = pick
    return out


def fx_published(hold=63):
    """baseline: the three published crosses exactly as printed, fixed hold, equal notional"""
    trades = []
    for r in CRS.itertuples():
        i0 = E0[r.edition]
        trades.append(dict(lo=r.long, sh=r.short, i0=i0, i1=min(i0 + hold, LAST), w=1 / (3 * hold / 10)))
    return book(trades)


def fx_final(persist=6, min_hold=63, max_hold=252, stop_sigma=2.0, n=3, score=score_final, log=False):
    """FX-A. Each edition opens a tranche of n crosses sized to equal risk; a cross is held at least
    min_hold days, then closed at the first edition where its long leg is out of the top `persist`
    or its short leg out of the bottom `persist`; never longer than max_hold; catastrophe stop at
    -stop_sigma quarterly sigmas of the cross."""
    sel, rk = pick_crosses(score, n=n), ranked(score)
    trades, rows = [], []
    for k, e in enumerate(EDS):
        i0 = E0[e]
        for lo, sh in sel[e]:
            i1, why = min(i0 + max_hold, LAST), "max hold"
            for e2 in EDS[k + 1:]:
                j = E0[e2]
                if j >= i1:
                    break
                if j - i0 >= min_hold and (lo not in rk[e2][:persist] or sh not in rk[e2][-persist:]):
                    i1, why = j, f"signal faded {e2}"
                    break
            if i1 == LAST:
                why = "open"
            v = xvol(lo, sh, i0)
            p = path(lo, sh, i0, i1)
            kx = stop_exit(p, stop_sigma, v) if stop_sigma else len(p) - 1
            if kx < len(p) - 1:
                why = "catastrophe stop"
            trades.append(dict(lo=lo, sh=sh, i0=i0, i1=i0 + kx, w=(1 / (n * 12.6)) * 0.10 / v))
            rows.append(dict(edition=e, long=lo, short=sh, entry=IDX[i0].date(), exit=IDX[i0 + kx].date(),
                             days=kx, ret_pct=round(float(p[kx]) * 100, 2), cross_vol_pct=round(v * 100, 1),
                             stop_pct=round(-stop_sigma * v * 50, 1) if stop_sigma else None, exit_reason=why))
    s = book(trades)
    return (s, pd.DataFrame(rows)) if log else s


# ----------------------------------------------------------------------------- curve rules
_y10 = pd.read_csv(D / "y10_monthly.csv", index_col=0, parse_dates=True)
_y10.index = _y10.index.to_period("M")
_polm = _pol.resample("MS").mean()
_polm.index = _polm.index.to_period("M")
SLOPE = _y10 - _polm.reindex(_y10.index)[_y10.columns]
DSL = SLOPE.diff()
SVOL = DSL.rolling(24, min_periods=12).std().shift(1)
CRV = CRV[CRV.call != "neutral"].copy()
CRV["m0"] = pd.to_datetime(CRV.edition).dt.to_period("M")
CRV["sgn"] = np.where(CRV.call == "steepener", 1, -1)


def curve_book(select, hold=6, stop=0.75, cost_bp=2.0, log=False):
    """each edition opens a tranche of the selected calls, each sized 1/(slope-change vol), held
    `hold` months from the edition month, catastrophe stop at -stop pp of slope. Monthly P&L,
    scaled point-in-time to 10% annual vol (expanding-window realized vol)."""
    pnl = pd.Series(0.0, index=SLOPE.index)
    rows = []
    for r in CRV[select(CRV)].itertuples():
        v = SVOL.at[r.m0, r.cc] if r.m0 in SVOL.index else np.nan
        if not np.isfinite(v) or v <= 0:
            continue
        w = 1.0 / v / (2 * hold)
        cum, m, out = 0.0, r.m0, "held"
        nxt = r.m0 + 1 if (r.m0 + 1) in pnl.index else r.m0
        pnl[nxt] -= w * 2 * cost_bp / 100
        for _ in range(hold):
            m = m + 1
            if m not in DSL.index or not np.isfinite(DSL.at[m, r.cc]):
                out = "open"
                break
            d = DSL.at[m, r.cc] * r.sgn
            pnl[m] += w * d
            cum += d
            if stop is not None and cum <= -stop:
                out = "stop"
                break
        rows.append(dict(edition=r.edition, cc=r.cc, call=r.call, stars=r.stars, verdict=r.verdict,
                         gain_bp=round(cum * 100), exit=out))
    x = pnl.loc["2008-02":]
    rv = x.expanding(12).std().shift(1)
    rv = rv.fillna(x.iloc[:12].std()) * np.sqrt(12)
    s = x * 0.10 / rv
    return (s, pd.DataFrame(rows)) if log else s


SEL_ALL2 = lambda c: c.stars >= 2                                     # baseline: every >=2-star call
SEL_FINAL = lambda c: c.verdict.isin(["SETUP", "EARLY_TURN"])         # CV-A


# ----------------------------------------------------------------------------- reporting
ERAS = [("2008-18 (design)", "2008-01-01", "2018-12-31"), ("2019-26 (out-of-sample)", "2019-01-01", "2026-12-31"),
        ("2008-26 (all)", "2008-01-01", "2026-12-31")]


def summary(s, per_year):
    rows = {}
    for nm, a, b in ERAS:
        x = s[(s.index >= (pd.Period(a, "M") if per_year == 12 else pd.Timestamp(a)))
              & (s.index <= (pd.Period(b, "M") if per_year == 12 else pd.Timestamp(b)))]
        x = x.loc[x.ne(0).idxmax():] if x.ne(0).any() else x
        ann, vol = x.mean() * per_year, x.std() * np.sqrt(per_year)
        eq = x.cumsum()
        yr = x.groupby(x.index.year).sum()
        rows[nm] = {"return %/yr": round(ann * 100, 1), "vol %": round(vol * 100, 1),
                    "Sharpe": round(ann / vol, 2), "max DD %": round((eq - eq.cummax()).min() * 100, 1),
                    "positive years": f"{(yr > 0).sum()}/{len(yr)}", "worst year %": round(yr.min() * 100, 1)}
    return pd.DataFrame(rows)


def monthly(s):
    return s.groupby(s.index.to_period("M")).sum()


def main_backtest():
    OUT.mkdir(parents=True, exist_ok=True)
    print("== FX: published crosses as printed, 3m hold (baseline)")
    print(summary(fx_published(63), 252).to_string())
    print("\n== FX-A: final rule")
    fx, fxlog = fx_final(log=True)
    print(summary(fx, 252).to_string())
    print(fxlog.exit_reason.str.split(" 20").str[0].value_counts().to_string())
    print("\n== FX-A robustness (Sharpe 2008-18 / 2019-26)")
    for lab, kw in [("no catastrophe stop", dict(stop_sigma=None)), ("min hold 42d", dict(min_hold=42)),
                    ("min hold 84d", dict(min_hold=84)), ("exit depth 5", dict(persist=5)),
                    ("exit depth 7", dict(persist=7)), ("with cycle engine", dict(score=lambda g: g.total / (g.vol.clip(lower=VOL_FLOOR) / 0.10))),
                    ("no vol scaling", dict(score=lambda g: g.total - g.cycle)), ("5 crosses", dict(n=5))]:
        t = summary(fx_final(**kw), 252).loc["Sharpe"]
        print(f"  {lab:22s} {t.iloc[0]:+.2f} / {t.iloc[1]:+.2f}")
    print("\n== Curves: every >=2-star call, 3m hold (baseline)")
    print(summary(curve_book(SEL_ALL2, hold=3, stop=None), 12).to_string())
    print("\n== CV-A: final rule (SETUP / EARLY_TURN slope verdicts, 6m hold, 75bp stop)")
    cv, cvlog = curve_book(SEL_FINAL, log=True)
    print(summary(cv, 12).to_string())
    print("\n== Combined: 50% FX-A + 50% CV-A risk")
    fxm = monthly(fx)
    df = pd.DataFrame({"FX-A": fxm, "CV-A": cv}).loc["2008-02":"2026-10"].fillna(0.0)
    df["Combined"] = 0.5 * df["FX-A"] + 0.5 * df["CV-A"]
    print("correlation FX-A vs CV-A (monthly):", round(df["FX-A"].corr(df["CV-A"]), 2))
    print(summary(df["Combined"], 12).to_string())
    yr = df.groupby(df.index.year).sum().mul(100).round(1)
    print("\nCalendar-year returns, %:\n" + yr.to_string())
    fxlog.to_csv(OUT / "fx_trades.csv", index=False)
    cvlog.to_csv(OUT / "curve_trades.csv", index=False)
    df.round(6).to_csv(OUT / "monthly_returns.csv", index_label="month")
    print(f"\nwrote {OUT.relative_to(ROOT)}/fx_trades.csv, curve_trades.csv, monthly_returns.csv")


def main_diagnostics():
    """the evidence behind the rule choices (STRATEGY.md section 3)."""
    import warnings
    warnings.filterwarnings("ignore")
    era = lambda e: np.where(pd.Series(e).str[:4].astype(int).values <= 2018, "2008-18", "2019-26")
    print("== 1. Which FX engine predicts? mean cross-sectional rank IC vs forward return (incl. carry) vs USD")
    f = FXT[FXT.fund].copy()
    for h in (21, 63, 126):
        f[f"r{h}"] = [(CUM[min(E0[d] + h, LAST), CI[c]] - CUM[E0[d], CI[c]])
                      - (CUM[min(E0[d] + h, LAST), CI["USD"]] - CUM[E0[d], CI["USD"]])
                      if E0[d] + h <= LAST else np.nan for d, c in zip(f.edition, f.ccy)]
    f["era"] = era(f.edition)
    tab = {}
    for h in (21, 63, 126):
        for e, g in f.groupby("era"):
            tab[(f"{h}d", e)] = {k: g.groupby("edition").apply(
                lambda x: x[k].rank().corr(x[f"r{h}"].rank()) if x[f"r{h}"].notna().sum() > 5 else np.nan).mean()
                for k in ["carry", "cycle", "valuation", "momentum", "total"]}
    print(pd.DataFrame(tab).round(3).to_string())

    print("\n== 2. Holding period and stops on the published crosses (Sharpe at 10% vol, 2008-18 / 2019-26)")
    def pub(hold, stop=None, trail=None, vstop=None):
        trades = []
        for r in CRS.itertuples():
            i0 = E0[r.edition]; i1 = min(i0 + hold, LAST); p = path(r.long, r.short, i0, i1)
            k = len(p) - 1
            if stop is not None:
                hit = np.where(p[1:] <= -stop)[0]; k = 1 + int(hit[0]) if len(hit) else k
            if vstop is not None:
                k = min(k, stop_exit(p, vstop, xvol(r.long, r.short, i0)))
            if trail is not None:
                pk = np.maximum.accumulate(p); hit = np.where((p[1:] - pk[1:] <= -trail) & (pk[1:] > 0))[0]
                k = min(k, 1 + int(hit[0])) if len(hit) else k
            trades.append(dict(lo=r.long, sh=r.short, i0=i0, i1=i0 + k, w=1 / (3 * hold / 10)))
        t = summary(book(trades), 252).loc["Sharpe"]
        return f"{t.iloc[0]:+.2f} / {t.iloc[1]:+.2f}"
    for h in (21, 63, 126, 252):
        print(f"  hold {h:3d}d, no stop        {pub(h)}")
    for lab, kw in [("fixed -3%", dict(stop=0.03)), ("fixed -5%", dict(stop=0.05)), ("fixed -8%", dict(stop=0.08)),
                    ("-1.5 quarterly sigma", dict(vstop=1.5)), ("-2 quarterly sigma", dict(vstop=2.0)),
                    ("trailing 5%", dict(trail=0.05))]:
        print(f"  hold 126d, {lab:20s} {pub(126, **kw)}")

    print("\n== 3. Curve calls: 6-month gain of (10y - policy) in the call's favour, by context verdict and stars")
    c = CRV.copy()
    c["g6"] = [(SLOPE.at[r.m0 + 6, r.cc] - SLOPE.at[r.m0, r.cc]) * r.sgn
               if (r.m0 + 6) in SLOPE.index and r.m0 in SLOPE.index else np.nan for r in c.itertuples()]
    c["era"] = era(c.edition)
    for by in ("verdict", "stars"):
        t = c.groupby([by, "era"]).g6.agg(lambda s: f"{s.mean() * 100:+.0f}bp hit {(s > 0).mean():.0%} n={s.count()}")
        print(t.unstack().to_string())


def main_live():
    """today's FX-A / CV-A signals from the live pipeline's cached data (data/raw)."""
    import warnings
    warnings.filterwarnings("ignore")
    from cycle_analyzer.data import load_panel
    from cycle_analyzer.analysis import run
    res = run(load_panel(refresh=False))
    lr = np.log(FXD.drop(columns="USD")).diff().iloc[-63:]
    vol = (lr.std() * np.sqrt(252)).clip(lower=VOL_FLOOR)
    g = pd.DataFrame([dict(ccy=f.ccy, total=float(f.total), cycle=f.cycle, vol=vol.get(f.ccy, np.nan))
                      for f in res.fx if f.penalty > -1.0])
    g["score"] = score_final(g)
    g = g.sort_values("score", ascending=False).reset_index(drop=True)
    print(f"model anchor {res.asof}; FX data through {FXD.index[-1].date()}")
    print(g.round(3).to_string())
    L, S = g.head(6), g.tail(6)[::-1]
    pairs = sorted(((a.score - b.score, a.ccy, b.ccy) for a in L.itertuples() for b in S.itertuples()), reverse=True)
    used, n = set(), 0
    print("\nFX-A new tranche (long / short, cross vol, notional per 10% risk, catastrophe stop):")
    for _, lo, sh in pairs:
        if lo in used or sh in used:
            continue
        used |= {lo, sh}; n += 1
        v = max(float((lr[lo] - lr[sh]).std() * np.sqrt(252)), VOL_FLOOR)
        print(f"  long {lo} / short {sh}: vol {v:.1%}, notional {0.10 / v:.2f}x, stop {-2 * v * 0.5:.1%}")
        if n == 3:
            break
    print(f"  exit test for open crosses: long leg must stay in {g.head(6).ccy.tolist()}, "
          f"short leg in {g.tail(6).ccy.tolist()}")
    print("\nCV-A curve trades (SETUP / EARLY_TURN, 6m hold, 75bp stop):")
    for c in res.curves:
        if c.direction != "neutral" and c.context_verdict in ("SETUP", "EARLY_TURN"):
            print(f"  {COUNTRIES[c.cc].name}: {c.direction} ({c.context_verdict}, {c.conviction} stars, "
                  f"slope {c.slope:+.2f}pp, z {c.slope_z:+.2f}) - {c.expression}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="print today's signals from data/raw")
    ap.add_argument("--diagnostics", action="store_true", help="evidence behind the rule choices")
    a = ap.parse_args()
    main_live() if a.live else (main_diagnostics() if a.diagnostics else main_backtest())
