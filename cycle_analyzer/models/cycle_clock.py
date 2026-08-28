"""Cycle clock: position each economy in growth x inflation phase space.

The clock is a two-dimensional oscillator:

    x-axis  G = growth-cycle z-score   (composite leading indicator vs trend)
    y-axis  I = inflation-gap z-score  (CPI vs target, scaled by own history)

Business cycles rotate counter-clockwise through the four quadrants:

    Q1  G>0, I<0   RECOVERY / GOLDILOCKS   growth improving, inflation tame
                   -> credit-friendly, risk-on, carry works
    Q2  G>0, I>0   OVERHEATING             growth above trend, inflation above
                   target -> hikes coming, long the currency, pay front end
    Q3  G<0, I>0   STAGFLATION / SLOWDOWN  growth rolling over, inflation
                   sticky -> curve steepeners, currency vulnerable
    Q4  G<0, I<0   DISINFLATION / EASING   both below trend -> cuts, receive
                   rates, funding currency

Phase angle theta = atan2(I, G) in degrees, measured counter-clockwise from
the +G axis. The canonical rotation Goldilocks -> Overheating -> Stagflation
-> Disinflation corresponds to theta increasing from -45deg through +45deg,
+135deg, +225deg (=-135deg). Angular velocity (median monthly d-theta over a
trailing window, unwrapped) tells us where the economy is heading and how
fast, i.e. "what is next in the current cycle".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

PHASES = ["Goldilocks", "Overheating", "Stagflation", "Disinflation"]

# Quadrant boundaries in degrees (counter-clockwise from +G axis).
# Goldilocks is centered on -45deg (G>0, I<0), Overheating on +45, etc.
_PHASE_BOUNDS = {
    "Goldilocks": (-90.0, 0.0),
    "Overheating": (0.0, 90.0),
    "Stagflation": (90.0, 180.0),
    "Disinflation": (180.0, 270.0),  # equivalently -180..-90
}


def phase_of(theta_deg: float) -> str:
    """Map a phase angle in degrees to its cycle-phase label."""
    t = (theta_deg + 90.0) % 360.0 - 90.0  # normalize into [-90, 270)
    for name, (lo, hi) in _PHASE_BOUNDS.items():
        if lo <= t < hi:
            return name
    return "Disinflation"


def next_phase(name: str) -> str:
    return PHASES[(PHASES.index(name) + 1) % 4]


@dataclass
class ClockReading:
    country: str
    g: float                    # growth z
    i: float                    # inflation z
    theta: float                # phase angle, degrees
    radius: float               # amplitude: how pronounced the cycle position is
    omega: float                # deg/month, >0 = rotating forward through cycle
    phase: str
    heading: str                # phase we are rotating toward
    months_to_next: float | None  # eta to next quadrant at current omega
    history: pd.DataFrame = field(repr=False, default=None)

    @property
    def is_forward(self) -> bool:
        return self.omega > 0


def _unwrap_deg(angles: np.ndarray) -> np.ndarray:
    return np.degrees(np.unwrap(np.radians(angles)))


def read_clock(g: pd.Series, i: pd.Series, country: str,
               omega_window: int = 9) -> ClockReading | None:
    """Compute the current clock reading from growth-z and inflation-z series.

    omega is the median monthly change of the unwrapped phase angle over the
    trailing ``omega_window`` months — median, not mean, so one noisy CPI or
    CLI print does not flip the rotation direction.
    """
    df = pd.concat({"g": g, "i": i}, axis=1).dropna()
    if len(df) < omega_window + 3:
        return None

    theta_raw = np.degrees(np.arctan2(df["i"].values, df["g"].values))
    theta_un = _unwrap_deg(theta_raw)
    d_theta = np.diff(theta_un[-(omega_window + 1):])
    omega = float(np.median(d_theta))

    g0, i0 = float(df["g"].iloc[-1]), float(df["i"].iloc[-1])
    theta0 = float(theta_raw[-1])
    ph = phase_of(theta0)

    # Distance (degrees) to the boundary we are rotating toward.
    t = (theta0 + 90.0) % 360.0 - 90.0
    lo, hi = _PHASE_BOUNDS[ph]
    if omega > 0.05:
        heading = next_phase(ph)
        dist = hi - t
    elif omega < -0.05:
        heading = PHASES[(PHASES.index(ph) - 1) % 4]
        dist = t - lo
    else:
        heading = ph  # effectively parked
        dist = np.nan

    months = float(dist / abs(omega)) if np.isfinite(dist) and abs(omega) > 0.05 else None
    # An economy sitting near the origin has no meaningful phase; cap eta.
    if months is not None and months > 48:
        months = None

    hist = df.copy()
    hist["theta"] = theta_raw
    return ClockReading(
        country=country, g=g0, i=i0, theta=theta0,
        radius=float(np.hypot(g0, i0)), omega=omega, phase=ph,
        heading=heading, months_to_next=months, history=hist,
    )
