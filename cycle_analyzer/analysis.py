"""Pipeline: raw panels -> indicators -> models -> one results bundle."""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

from .universe import COUNTRIES
from .indicators import build_indicators
from .models.cycle_clock import ClockReading, read_clock
from .models.mean_reversion import OUFit, DangerCheck, fit_ou, distance_to_danger
from .models.divergence import Stance, Standout, compute_stances, find_standouts, pack_summary
from .models.context import ContextVerdict, assess
from .models.trades import (FXScore, CurveSignal, score_fx, curve_signals,
                            fx_crosses, _PHASE_SLOPE, _PHASE_FX)

# Danger thresholds, in units of the underlying series:
#   inflation: gap z of +1.0 == "inflation-fight zone" for that economy
#   growth:    growth z of -1.0 == "recession-risk zone"
INFL_DANGER_Z = 1.0
GROWTH_DANGER_Z = -1.0


@dataclass
class Results:
    asof: str
    ind: dict = field(repr=False, default=None)
    clocks: dict[str, ClockReading] = None
    infl_fits: dict[str, OUFit] = None
    growth_fits: dict[str, OUFit] = None
    slope_fits: dict[str, OUFit] = None
    reer_fits: dict[str, OUFit] = None
    infl_danger: dict[str, DangerCheck] = None
    growth_danger: dict[str, DangerCheck] = None
    stances: dict[str, Stance] = None
    standouts: list[Standout] = None
    pack: dict = None
    fx: list[FXScore] = None
    curves: list[CurveSignal] = None
    crosses: list[dict] = None
    # context filter verdicts, keyed by country, per family
    infl_ctx: dict[str, ContextVerdict] = None
    slope_ctx: dict[str, ContextVerdict] = None
    reer_ctx: dict[str, ContextVerdict] = None

    def safe_list(self) -> list[str]:
        """Countries whose cycle is not endangered on either axis."""
        out = []
        for cc in self.clocks:
            i, g = self.infl_danger.get(cc), self.growth_danger.get(cc)
            if i and g and i.safe and g.safe:
                out.append(cc)
        return out


def _fit_all(df: pd.DataFrame, tail: int = 300) -> dict[str, OUFit]:
    fits = {}
    for cc in df.columns:
        f = fit_ou(df[cc].dropna().tail(tail))
        if f is not None:
            fits[cc] = f
    return fits


def run(panels: dict[str, pd.DataFrame]) -> Results:
    ind = build_indicators(panels)
    gz, iz = ind["growth_z"], ind["infl_z"]

    asof_candidates = [p.index[-1] for k, p in panels.items() if not p.empty]
    asof = max(asof_candidates).strftime("%Y-%m") if asof_candidates else "?"

    clocks: dict[str, ClockReading] = {}
    for cc in COUNTRIES:
        if cc in gz.columns and cc in iz.columns:
            r = read_clock(gz[cc].dropna(), iz[cc].dropna(), cc)
            if r is not None:
                clocks[cc] = r

    infl_fits = _fit_all(iz)
    growth_fits = _fit_all(gz)
    slope_fits = _fit_all(ind.get("slope", pd.DataFrame()))
    reer_fits = _fit_all(ind["reer_dev"])

    infl_danger = {cc: distance_to_danger(f, INFL_DANGER_Z, "inflation", direction=+1)
                   for cc, f in infl_fits.items()}
    growth_danger = {cc: distance_to_danger(f, GROWTH_DANGER_Z, "growth", direction=-1)
                     for cc, f in growth_fits.items()}

    stances = compute_stances(ind)
    standouts = find_standouts(stances)

    # ---- context filter: is each extreme supported or contradicted by the
    # prevailing cycle context? ------------------------------------------------
    def _t(x, s):
        return float(np.tanh((x if np.isfinite(x) else 0.0) / s))

    def _phase_push(cc: str, table: dict) -> float:
        """Phase-implied pressure, leaning on the heading when rotation is fast."""
        clk = clocks.get(cc)
        if clk is None:
            return 0.0
        p = table.get(clk.phase, 0.0)
        if clk.months_to_next is not None and clk.months_to_next <= 9:
            p = 0.5 * p + 0.5 * table.get(clk.heading, 0.0)
        return p

    _dir = {"hiking": 1.0, "on hold": 0.0, "cutting": -1.0}

    infl_ctx: dict[str, ContextVerdict] = {}
    for cc, f in infl_fits.items():
        st = stances.get(cc)
        g6 = float(gz[cc].diff(6).dropna().iloc[-1]) if cc in gz.columns and gz[cc].diff(6).dropna().size else 0.0
        r6 = float(ind["reer_dev"][cc].diff(6).dropna().iloc[-1]) if cc in ind["reer_dev"].columns and ind["reer_dev"][cc].diff(6).dropna().size else 0.0
        # inflationary impulse: leading growth accelerating, easy real policy,
        # a depreciating real exchange rate
        impulse = (0.55 * _t(g6, 0.5)
                   + 0.30 * _t(-(st.real_gap if st else 0.0), 1.5)
                   + 0.15 * _t(-r6, 4.0))
        ctx = -np.sign(f.z if np.isfinite(f.z) else 0.0) * impulse
        infl_ctx[cc] = assess(iz[cc], f, ctx, cc, "inflation")

    slope_ctx: dict[str, ContextVerdict] = {}
    for cc, f in slope_fits.items():
        st = stances.get(cc)
        steepen = (0.6 * _phase_push(cc, _PHASE_SLOPE)
                   - 0.4 * _dir.get(st.direction if st else "on hold", 0.0))
        ctx = -np.sign(f.z if np.isfinite(f.z) else 0.0) * steepen
        slope_ctx[cc] = assess(ind["slope"][cc], f, ctx, cc, "slope")

    reer_ctx: dict[str, ContextVerdict] = {}
    for cc, f in reer_fits.items():
        st = stances.get(cc)
        appreciate = (0.5 * _phase_push(cc, _PHASE_FX) / 0.9
                      + 0.5 * _dir.get(st.direction if st else "on hold", 0.0))
        ctx = -np.sign(f.z if np.isfinite(f.z) else 0.0) * appreciate
        reer_ctx[cc] = assess(ind["reer_dev"][cc], f, ctx, cc, "reer")

    fx = score_fx(clocks, stances, reer_fits, reer_ctx)
    curves = curve_signals(slope_fits, clocks, slope_ctx, stances)

    return Results(
        asof=asof, ind=ind, clocks=clocks,
        infl_fits=infl_fits, growth_fits=growth_fits,
        slope_fits=slope_fits, reer_fits=reer_fits,
        infl_danger=infl_danger, growth_danger=growth_danger,
        stances=stances, standouts=standouts, pack=pack_summary(stances),
        fx=fx, curves=curves, crosses=fx_crosses(fx, stances),
        infl_ctx=infl_ctx, slope_ctx=slope_ctx, reer_ctx=reer_ctx,
    )
