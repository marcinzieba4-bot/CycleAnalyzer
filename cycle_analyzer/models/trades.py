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
from .context import ContextVerdict, gate
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
             reer_fits: dict[str, OUFit],
             reer_ctx: dict[str, ContextVerdict] | None = None) -> list[FXScore]:
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

        # Valuation: REER mean-reversion pull, but only to the extent the
        # context filter allows — a rich currency whose richness is still fed
        # by the cycle (TREND_INTACT) earns no fade credit at all.
        fit = reer_fits.get(cc)
        valuation = 0.0
        if fit is not None and np.isfinite(fit.z):
            valuation = -0.45 * np.clip(fit.z, -2.5, 2.5)
            valuation *= gate(reer_ctx.get(cc)) if reer_ctx else 1.0

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
    expression: str       # the actual legs to put on
    context_verdict: str  # verdict from the context filter on the slope


def curve_expression(cc: str, direction: str) -> str:
    ccy = COUNTRIES[cc].ccy
    if direction == "flattener":
        return (f"2s10s flattener in {ccy}: pay 2y swap (or short 2y govvies / "
                f"front-end futures), receive 10y — DV01-neutral, so the P&L is "
                f"the slope, not the level")
    if direction == "steepener":
        return (f"2s10s steepener in {ccy}: receive 2y swap (or long 2y govvies), "
                f"pay 10y — DV01-neutral, so the P&L is the slope, not the level")
    return "no position — stay flat the curve"


def curve_signals(slope_fits: dict[str, OUFit],
                  clocks: dict[str, ClockReading],
                  slope_ctx: dict[str, ContextVerdict] | None = None,
                  stances: dict[str, Stance] | None = None) -> list[CurveSignal]:
    out: list[CurveSignal] = []
    for cc, fit in slope_fits.items():
        clk = clocks.get(cc)
        phase = clk.phase if clk else "?"
        phase_push = _PHASE_SLOPE.get(phase, 0.0)
        v = slope_ctx.get(cc) if slope_ctx else None
        # Mean reversion push: fade stretched slopes, weighted by reversion
        # speed AND gated by the context filter — a stretched slope whose
        # stretch the cycle still supports contributes nothing.
        speed = 1.0 if fit.half_life < 12 else (0.6 if fit.half_life < 24 else 0.3)
        mr_push = -np.clip(fit.z, -2.5, 2.5) / 2.5 * speed * gate(v)
        signal = 0.6 * phase_push + 0.4 * mr_push
        if signal > 0.15:
            direction = "steepener"
        elif signal < -0.15:
            direction = "flattener"
        else:
            direction = "neutral"
        conviction = 1 + (abs(signal) > 0.45) + (abs(signal) > 0.75)
        agree = np.sign(phase_push) == np.sign(mr_push) and abs(mr_push) > 0.2
        if v is not None and v.verdict == "EARLY_TURN" and agree:
            conviction = min(3, conviction + 1)

        bits = [f"phase '{phase}' implies "
                f"{'steeper' if phase_push>0 else 'flatter' if phase_push<0 else 'range'}"]
        st = stances.get(cc) if stances else None
        if st is not None and st.direction != "on hold":
            bits.append(f"{COUNTRIES[cc].cb} is {st.direction} ({st.d6:+.2f}pp/6m), "
                        f"which works through the front end")
        if abs(fit.z) > 1.0:
            bits.append(
                f"slope {fit.z:+.1f}σ vs own history (half-life {fit.half_life:.0f}m)"
                + (" — mean reversion agrees" if agree else " — mean reversion leans against"))
        if v is not None and v.verdict != "NONE":
            bits.append(f"context filter: {v.verdict} — {v.note}")
        out.append(CurveSignal(cc=cc, slope=fit.last, slope_z=fit.z,
                               half_life=fit.half_life, phase=phase,
                               direction=direction, conviction=int(conviction),
                               rationale="; ".join(bits),
                               expression=curve_expression(cc, direction),
                               context_verdict=v.verdict if v else "NONE"))
    out.sort(key=lambda s: (-s.conviction, -abs(s.slope_z)))
    return out


def fx_crosses(scores: list[FXScore], stances: dict[str, Stance] | None = None,
               n: int = 3) -> list[dict]:
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
        carry_pp = None
        if stances and lo.cc in stances and sh.cc in stances:
            carry_pp = round(stances[lo.cc].policy - stances[sh.cc].policy, 2)
        crosses.append({
            "long": lo.ccy, "short": sh.ccy,
            "edge": round(lo.total - sh.total, 2),
            "carry": round(lo.carry - sh.carry, 2),
            "carry_pp": carry_pp,
            "expression": (
                f"buy {lo.ccy}, sell {sh.ccy} via 3m FX forwards (rolled)"
                + (f"; indicative positive carry ≈ {carry_pp:+.1f}pp annualized "
                   f"from the policy-rate differential" if carry_pp is not None else "")),
        })
    return crosses
