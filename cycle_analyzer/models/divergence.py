"""Standout detector: who is out of step with the global policy cycle.

The interesting information in a cross-country cycle framework is rarely the
level — it is the *divergence*: the first central bank to hike while everyone
else cuts, the one still deliberating a hike while the pack is neutral, the
one cutting into rising inflation. This module scores every central bank's
stance against the universe median and emits labeled standout signals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass

from ..universe import COUNTRIES


@dataclass
class Stance:
    cc: str
    policy: float
    d3: float            # policy change over 3m, pp
    d6: float            # over 6m
    d12: float           # over 12m
    real_rate: float
    real_gap: float      # real rate vs own 10y median real rate
    infl_gap: float      # CPI y/y minus target, pp
    infl_mom: float      # 3m change in y/y inflation, pp
    direction: str       # "hiking" | "cutting" | "on hold"
    months_on_hold: int
    score: float = np.nan     # divergence score vs universe median
    labels: tuple = ()


def _direction(d3: float, d6: float) -> str:
    if d3 > 0.01 or (d3 >= 0 and d6 > 0.01):
        return "hiking"
    if d3 < -0.01 or (d3 <= 0 and d6 < -0.01):
        return "cutting"
    return "on hold"


def compute_stances(ind: dict[str, pd.DataFrame]) -> dict[str, Stance]:
    pol = ind["policy"]
    stances: dict[str, Stance] = {}
    for cc in pol.columns:
        s = pol[cc].dropna()
        if len(s) < 24:
            continue
        d3, d6, d12 = (float(s.iloc[-1] - s.iloc[-1 - k]) if len(s) > k else np.nan
                       for k in (3, 6, 12))
        rr = ind["real_rate"][cc].dropna() if cc in ind["real_rate"].columns else pd.Series(dtype=float)
        real_rate = float(rr.iloc[-1]) if len(rr) else np.nan
        real_gap = float(rr.iloc[-1] - rr.tail(120).median()) if len(rr) >= 24 else np.nan
        ig = ind["infl_gap"][cc].dropna() if cc in ind["infl_gap"].columns else pd.Series(dtype=float)
        im = ind["infl_mom"][cc].dropna() if cc in ind["infl_mom"].columns else pd.Series(dtype=float)
        # months since the policy rate last changed
        chg = s.diff().abs() > 0.01
        months_hold = 0
        for v in chg.values[::-1]:
            if v:
                break
            months_hold += 1
        stances[cc] = Stance(
            cc=cc, policy=float(s.iloc[-1]), d3=d3, d6=d6, d12=d12,
            real_rate=real_rate, real_gap=real_gap,
            infl_gap=float(ig.iloc[-1]) if len(ig) else np.nan,
            infl_mom=float(im.iloc[-1]) if len(im) else np.nan,
            direction=_direction(d3, d6), months_on_hold=months_hold,
        )
    return stances


@dataclass
class Standout:
    cc: str
    kind: str        # short machine label
    headline: str    # one-line human description
    strength: float  # 0..3-ish, for sorting


def find_standouts(stances: dict[str, Stance]) -> list[Standout]:
    if not stances:
        return []
    d6s = pd.Series({cc: s.d6 for cc, s in stances.items()}).dropna()
    med_d6 = float(d6s.median())
    mad = float((d6s - med_d6).abs().median()) or 0.25
    n_cut = int((d6s < -0.01).sum())
    n_hike = int((d6s > 0.01).sum())
    pack = ("easing" if n_cut > len(d6s) / 2 else
            "tightening" if n_hike > len(d6s) / 2 else "neutral")

    out: list[Standout] = []
    for cc, s in stances.items():
        name, cb = COUNTRIES[cc].name, COUNTRIES[cc].cb
        s.score = (s.d6 - med_d6) / (1.4826 * mad) if np.isfinite(s.d6) else np.nan
        labels = []

        if s.direction == "hiking" and pack in ("easing", "neutral") and n_hike <= max(3, len(d6s) // 6):
            labels.append(Standout(cc, "early_hiker",
                f"{cb} is an EARLY HIKER: +{s.d6:.2f}pp over 6m while the global pack is {pack}",
                2.5 + abs(s.score if np.isfinite(s.score) else 0)))
        if s.direction == "cutting" and s.infl_mom > 0.3 and s.infl_gap > 0:
            labels.append(Standout(cc, "cutting_into_inflation",
                f"{cb} keeps cutting while inflation is above target and re-accelerating "
                f"(+{s.infl_mom:.1f}pp over 3m) — credibility risk, watch the currency",
                2.0 + s.infl_mom))
        if (s.direction == "on hold" and s.months_on_hold >= 6
                and s.infl_mom > 0.3 and s.infl_gap > 0.3 and pack in ("easing", "neutral")):
            labels.append(Standout(cc, "deliberating_hike",
                f"{cb} on hold {s.months_on_hold}m with inflation {s.infl_gap:+.1f}pp above target "
                f"and rising — the debate shifts toward a hike while others are {pack}",
                1.5 + s.infl_mom))
        if s.real_rate < 0 and s.infl_gap > 0.5:
            labels.append(Standout(cc, "behind_curve",
                f"{cb} runs a NEGATIVE real rate ({s.real_rate:.1f}%) with inflation "
                f"{s.infl_gap:+.1f}pp above target — behind the curve",
                1.5 + abs(s.real_rate)))
        if s.real_gap > 1.5 and s.direction != "hiking":
            labels.append(Standout(cc, "room_to_cut",
                f"{cb}'s real rate is {s.real_gap:+.1f}pp above its own decade norm — "
                f"most room in the universe to ease without stoking inflation",
                1.0 + s.real_gap / 2))
        if np.isfinite(s.score) and abs(s.score) >= 2.5 and not labels:
            side = "tighter" if s.score > 0 else "easier"
            labels.append(Standout(cc, "pace_outlier",
                f"{cb} moved {abs(s.d6 - med_d6):.1f}pp {side} than the global median over 6m",
                abs(s.score) / 2))

        s.labels = tuple(l.kind for l in labels)
        out.extend(labels)

    out.sort(key=lambda x: -x.strength)
    return out


def pack_summary(stances: dict[str, Stance]) -> dict:
    d6s = pd.Series({cc: s.d6 for cc, s in stances.items()}).dropna()
    dirs = pd.Series({cc: s.direction for cc, s in stances.items()})
    return {
        "median_d6": float(d6s.median()),
        "n_hiking": int((dirs == "hiking").sum()),
        "n_cutting": int((dirs == "cutting").sum()),
        "n_hold": int((dirs == "on hold").sum()),
    }
