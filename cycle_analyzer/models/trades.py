"""Trade generation: turn cycle readings into FX and yield-curve ideas.

FX score (per currency, higher = want to be long):
    carry       policy-rate pickup vs USD, credibility-weighted
    cycle       clock position: overheating/early-hike phases attract flows,
                easing phases fund
    valuation   mean-reversion pull of the BIS broad REER vs its 10y average
    momentum    inflation-adjusted policy direction

Curve signal (per country with a 10y):
    stretch     OU z-score of the slope (10y - policy) vs own history
    phase       what the clock says should happen to the slope next
    -> steepener / flattener with conviction 1..3
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

from ..universe import COUNTRIES
from .cycle_clock import ClockReading
from .divergence import Stance
from .mean_reversion import OUFit

# How each phase treats the local currency (risk-adjusted, sign only).
_PHASE_FX = {"Goldilocks": +0.6, "Overheating": +0.9,
             "Stagflation": -0.6, "Disinflation": -0.9}

# What each phase implies for the slope 10y minus policy over the next
# 6-12 months: +1 steeper, -1 flatter.
_PHASE_SLOPE = {
    "Goldilocks": +0.4,      # term premium rebuilds as growth firms
    "Overheating": -1.0,     # front end reprices hikes -> bear flattening
    "Stagflation": +0.6,     # peak-rates trade: steepening starts
    "Disinflation": +1.0,    # cuts land in the front end -> bull steepening
}


@dataclass
class FXScore:
    cc: str
    ccy: str
    carry: float
    cycle: float
    valuation: float
    momentum: float
    penalty: float
    total: float = field(init=False)

    def __post_init__(self):
        self.total = self.carry + self.cycle + self.valuation + self.momentum + self.penalty


def score_fx(clocks: dict[str, ClockReading], stances: dict[str, Stance],
             reer_fits: dict[str, OUFit]) -> list[FXScore]:
    us = stances.get("US")
    us_pol = us.policy if us else 0.0
    out: list[FXScore] = []
    for cc, st in stances.items():
        if cc == "US":
            continue
        c = COUNTRIES[cc]
        # Carry: rate pickup vs USD, haircut when inflation eats it.
        pickup = st.policy - us_pol
        real_pickup = pickup - max(0.0, st.infl_gap if np.isfinite(st.infl_gap) else 0.0)
        carry = 0.25 * np.clip(pickup, -6, 6) * (0.5 if real_pickup < 0 else 1.0)

        clk = clocks.get(cc)
        cycle = 0.0
        if clk is not None:
            cycle = _PHASE_FX[clk.phase] * min(1.5, clk.radius) * 0.5
            # heading matters more than position when rotation is fast
            if clk.months_to_next is not None and clk.months_to_next <= 9:
                cycle = 0.5 * cycle + 0.5 * _PHASE_FX[clk.heading] * min(1.5, clk.radius) * 0.5

        fit = reer_fits.get(cc)
        valuation = 0.0
        if fit is not None and np.isfinite(fit.z):
            valuation = -0.45 * np.clip(fit.z, -2.5, 2.5)

        momentum = {"hiking": +0.4, "on hold": 0.0, "cutting": -0.4}[st.direction]
        if st.direction == "hiking" and st.infl_mom < 0:
            momentum += 0.2      # hiking into falling inflation: best combo

        # Credibility penalty: big positive inflation gaps destroy carry.
        # Capped at -3: beyond that the message is "uninvestable", not "more short".
        penalty = -min(3.0, 0.6 * max(0.0, (st.infl_gap if np.isfinite(st.infl_gap) else 0.0) - 2.0))

        out.append(FXScore(cc=cc, ccy=c.ccy, carry=round(carry, 2),
                           cycle=round(cycle, 2), valuation=round(valuation, 2),
                           momentum=round(momentum, 2), penalty=round(penalty, 2)))
    out.sort(key=lambda x: -x.total)
    return out


@dataclass
class CurveSignal:
    cc: str
    slope: float          # current 10y - policy, pp
    slope_z: float        # OU z vs own history
    half_life: float
    phase: str
    direction: str        # "steepener" | "flattener" | "neutral"
    conviction: int       # 1..3
    rationale: str


def curve_signals(slope_fits: dict[str, OUFit],
                  clocks: dict[str, ClockReading]) -> list[CurveSignal]:
    out: list[CurveSignal] = []
    for cc, fit in slope_fits.items():
        clk = clocks.get(cc)
        phase = clk.phase if clk else "?"
        phase_push = _PHASE_SLOPE.get(phase, 0.0)
        # Mean reversion push: fade stretched slopes, weighted by speed.
        speed = 1.0 if fit.half_life < 12 else (0.6 if fit.half_life < 24 else 0.3)
        mr_push = -np.clip(fit.z, -2.5, 2.5) / 2.5 * speed
        signal = 0.6 * phase_push + 0.4 * mr_push
        if signal > 0.15:
            direction = "steepener"
        elif signal < -0.15:
            direction = "flattener"
        else:
            direction = "neutral"
        conviction = 1 + (abs(signal) > 0.45) + (abs(signal) > 0.75)
        agree = np.sign(phase_push) == np.sign(mr_push) and abs(mr_push) > 0.2
        rationale_bits = [f"phase '{phase}' implies {'steeper' if phase_push>0 else 'flatter' if phase_push<0 else 'range'}"]
        if abs(fit.z) > 1.0:
            rationale_bits.append(
                f"slope is {fit.z:+.1f} sigma vs own history (half-life {fit.half_life:.0f}m)"
                + (" — mean reversion agrees" if agree else " — mean reversion leans against"))
        out.append(CurveSignal(cc=cc, slope=fit.last, slope_z=fit.z,
                               half_life=fit.half_life, phase=phase,
                               direction=direction, conviction=int(conviction),
                               rationale="; ".join(rationale_bits)))
    out.sort(key=lambda s: (-s.conviction, -abs(s.slope_z)))
    return out


def fx_crosses(scores: list[FXScore], n: int = 3) -> list[dict]:
    """Pair the strongest longs against the weakest *fundable* currencies.

    A currency whose score is destroyed by the credibility penalty (TRY-style)
    is excluded from the short leg: shorting a 30-40% carry currency is a
    financing bleed, not a funding trade. Fund from credible low-scorers.
    """
    fundable = [s for s in scores if s.penalty > -1.0]
    if len(fundable) < 2:
        return []
    longs, shorts = fundable[:n], fundable[-n:][::-1]
    crosses = []
    for lo, sh in zip(longs, shorts):
        crosses.append({
            "long": lo.ccy, "short": sh.ccy,
            "edge": round(lo.total - sh.total, 2),
            "carry": round(lo.carry - sh.carry, 2),
        })
    return crosses
