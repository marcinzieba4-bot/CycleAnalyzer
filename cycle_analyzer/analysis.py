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
from .models.trades import FXScore, CurveSignal, score_fx, curve_signals, fx_crosses

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
    fx = score_fx(clocks, stances, reer_fits)
    curves = curve_signals(slope_fits, clocks)

    return Results(
        asof=asof, ind=ind, clocks=clocks,
        infl_fits=infl_fits, growth_fits=growth_fits,
        slope_fits=slope_fits, reer_fits=reer_fits,
        infl_danger=infl_danger, growth_danger=growth_danger,
        stances=stances, standouts=standouts, pack=pack_summary(stances),
        fx=fx, curves=curves, crosses=fx_crosses(fx),
    )
