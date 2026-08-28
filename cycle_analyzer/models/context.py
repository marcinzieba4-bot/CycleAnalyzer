"""Context filter: decide which extremes are tradable and which are traps.

Mean reversion alone is a bad idea. A z-score tells you a variable is far
from equilibrium; it does not tell you whether the prevailing context has
turned against the deviation or is still feeding it. This module scores
every stretched cycle variable on three dimensions and issues a verdict:

  STRETCH   how far from the OU mean, in stationary sigmas
  TURN      has the series itself started to correct? and how much of the
            move has already been retraced (early turn = the good entry;
            mostly-retraced = the edge is gone)
  CONTEXT   do the *other* indicators - leading growth momentum, policy
            direction, real-rate restrictiveness, cycle-clock heading -
            push the series back toward its mean, or do they support the
            deviation persisting?

Verdicts:

  EARLY_TURN    stretched, the correction has begun but only slightly
                (< ~40% retraced), and the context says the cycle change is
                coming anyway -> ride the reversal, best risk/reward.
  SETUP         still pinned at the extreme, no turn in the series itself,
                but the leading context is deteriorating hard from the top
                -> position for the counter-movement before it prints.
  TREND_INTACT  stretched, but the context still feeds the deviation
                (e.g. an early hiking cycle behind a rich currency)
                -> DO NOT fade; the extreme can get more extreme.
  LATE          the reversion has mostly happened; no edge left.
  WATCH         stretched but the evidence is mixed; monitor.
  NONE          not stretched enough to matter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass

from .mean_reversion import OUFit

MIN_STRETCH = 0.75      # |z| below this -> no signal
EARLY_RETRACE = 0.40    # correction beyond this share of the peak -> LATE-ish
TURN_EPS = 0.04         # normalized drift (sigma/month) to call a turn


@dataclass
class ContextVerdict:
    cc: str
    family: str          # "inflation" | "slope" | "reer"
    z: float             # signed OU stretch, stationary sigmas
    drift_n: float       # 3m drift, in sigmas/month (normalized)
    turning: bool        # series moving back toward its mean
    retraced: float      # share of 12m peak deviation already unwound (0..1)
    context: float       # -1..+1, >0 = context pushes back toward the mean
    verdict: str
    note: str


def _verdict(z: float, turning: bool, retraced: float, context: float) -> tuple[str, str]:
    side = "rich/high" if z > 0 else "cheap/low"
    if abs(z) < MIN_STRETCH:
        return "NONE", "not stretched"
    if turning:
        if retraced >= EARLY_RETRACE:
            return "LATE", (f"the {side} extreme has already retraced "
                            f"{retraced:.0%} of its peak — most of the mean "
                            f"reversion is behind us, the edge is gone")
        if context > 0.20:
            return "EARLY_TURN", (f"the correction has started but only "
                                  f"{retraced:.0%} of the extreme is unwound, "
                                  f"and the surrounding cycle context points the "
                                  f"same way — the rest of the move is the trade")
        return "WATCH", ("the series is turning but the context does not yet "
                         "confirm it — could be noise")
    # still pinned at the extreme
    if context > 0.45:
        return "SETUP", ("the level itself has not budged, but the leading "
                         "context is breaking against it hard — position for "
                         "the counter-movement before it shows in the series")
    if context < -0.20:
        return "TREND_INTACT", ("the extreme is CONFIRMED by the prevailing "
                                "context — the forces that created it are still "
                                "in place; do not fade this on statistics alone")
    return "WATCH", "stretched, but turn evidence and context are both mixed"


def assess(x: pd.Series, fit: OUFit, context: float, cc: str,
           family: str) -> ContextVerdict:
    """Combine OU stretch, own-series turn evidence and external context."""
    z = fit.z if np.isfinite(fit.z) else 0.0
    dev_sign = 1.0 if z >= 0 else -1.0
    drift_n = fit.drift3m / fit.sigma_inf if fit.sigma_inf > 0 else 0.0
    turning = (-dev_sign * drift_n) > TURN_EPS

    tail = x.dropna().tail(12)
    retraced = 0.0
    if len(tail) and fit.sigma_inf > 0:
        dev_now = dev_sign * (float(tail.iloc[-1]) - fit.mu) / fit.sigma_inf
        peak = float((dev_sign * (tail - fit.mu) / fit.sigma_inf).max())
        if peak > 0.25:
            retraced = float(np.clip(1.0 - dev_now / peak, 0.0, 1.0))

    context = float(np.clip(context, -1.0, 1.0))
    verdict, note = _verdict(z, turning, retraced, context)
    return ContextVerdict(cc=cc, family=family, z=z, drift_n=drift_n,
                          turning=turning, retraced=retraced, context=context,
                          verdict=verdict, note=note)


# Gate applied to mean-reversion contributions in the trade models: how much
# of the statistical fade signal survives the context check.
GATE = {"EARLY_TURN": 1.25, "SETUP": 1.0, "WATCH": 0.5, "NONE": 1.0,
        "LATE": 0.3, "TREND_INTACT": 0.0}


def gate(v: ContextVerdict | None) -> float:
    return GATE.get(v.verdict, 1.0) if v is not None else 1.0
