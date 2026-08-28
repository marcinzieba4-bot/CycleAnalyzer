"""Mean-reversion engine: treat cycle indicators as Ornstein-Uhlenbeck series.

Every cycle variable we track (inflation gap, growth gap, curve slope, REER
deviation) is modeled as an OU process estimated from the discrete AR(1)
regression

    dx_t = a + b * x_{t-1} + eps_t        (monthly)

which gives:

    speed of reversion   kappa      = -ln(1 + b)
    half-life (months)   HL         = ln(2) / kappa
    long-run mean        mu         = -a / b
    stationary sigma     sigma_inf  = sigma_eps / sqrt(1 - (1+b)^2)

From the fitted process we produce two families of signals:

1. STRETCH — current z-score vs the stationary distribution. |z| > ~1.5 on a
   fast-reverting series (short half-life) is a classic fade; |z| large on a
   slow series is a warning, not yet a trade.

2. DISTANCE TO DANGER — for each economy we define danger thresholds (e.g.
   inflation gap z = +1 means "inflation fight begins", growth z = -1 means
   "recession risk zone"). We project the OU expected path

       E[x_{t+h}] = mu + (x_t - mu) * exp(-kappa * h)

   and add the drift of the recent momentum. If the expected path never
   crosses the threshold (it reverts before reaching it), the economy is
   flagged NOT IN DANGER on that axis — "the cycle has far to go before it
   is endangered". Otherwise we report the months until the crossing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class OUFit:
    mu: float           # long-run mean
    kappa: float        # monthly mean-reversion speed
    half_life: float    # months
    sigma_inf: float    # stationary standard deviation
    z: float            # current deviation from mu in stationary sigmas
    last: float
    drift3m: float      # recent momentum (avg monthly change, last 3m)
    n: int

    @property
    def reverting(self) -> bool:
        return self.kappa > 0 and np.isfinite(self.half_life)


def fit_ou(x: pd.Series, min_obs: int = 60) -> OUFit | None:
    """Fit a discrete OU (AR(1)) to a monthly series."""
    x = x.dropna().astype(float)
    if len(x) < min_obs:
        return None
    dx = x.diff().dropna()
    lag = x.shift(1).reindex(dx.index)
    A = np.column_stack([np.ones(len(lag)), lag.values])
    coef, *_ = np.linalg.lstsq(A, dx.values, rcond=None)
    a, b = float(coef[0]), float(coef[1])
    if b >= 0 or b <= -2:          # explosive or oscillating — not OU-like
        return None
    resid = dx.values - A @ coef
    sigma_eps = float(np.std(resid, ddof=2))
    phi = 1.0 + b
    kappa = -np.log(phi)
    half_life = np.log(2.0) / kappa
    mu = -a / b
    sigma_inf = sigma_eps / np.sqrt(max(1e-12, 1.0 - phi ** 2))
    last = float(x.iloc[-1])
    z = (last - mu) / sigma_inf if sigma_inf > 0 else np.nan
    drift3m = float(x.diff().tail(3).mean())
    return OUFit(mu=mu, kappa=kappa, half_life=half_life, sigma_inf=sigma_inf,
                 z=z, last=last, drift3m=drift3m, n=len(x))


def expected_path(fit: OUFit, horizon: int = 36) -> np.ndarray:
    """OU expected path blended with recent momentum.

    Pure OU says the series decays to mu immediately; real cycle variables
    carry momentum first. We let the recent 3m drift fade with the same
    half-life, which produces the familiar hump: keep rising for a while,
    then turn back toward the mean.
    """
    h = np.arange(1, horizon + 1)
    decay = np.exp(-fit.kappa * h)
    base = fit.mu + (fit.last - fit.mu) * decay
    # cumulative faded drift: sum_{j=1..h} drift * exp(-kappa*j)
    fade = np.cumsum(fit.drift3m * np.exp(-fit.kappa * h))
    return base + fade


@dataclass
class DangerCheck:
    axis: str               # e.g. "inflation" / "growth" / "slope"
    threshold: float        # in raw units of the series
    breached: bool          # already beyond threshold now
    months_to_cross: float | None   # None = expected path never crosses
    peak_ratio: float       # max projected excursion / threshold distance
    safe: bool              # true when path stays comfortably clear

    def label(self) -> str:
        if self.breached:
            return "IN THE ZONE"
        if self.months_to_cross is not None:
            return f"~{self.months_to_cross:.0f}m away"
        if self.safe:
            return "NOT IN DANGER"
        return "watch"


def distance_to_danger(fit: OUFit, threshold: float, axis: str,
                       direction: int = +1, horizon: int = 36,
                       safe_margin: float = 0.6) -> DangerCheck:
    """Project the OU path and check if/when it crosses ``threshold``.

    ``threshold`` is in the raw units of the fitted series; ``direction``
    states which side is dangerous (+1 = danger above the threshold, as for
    an inflation gap; -1 = danger below, as for a growth gap). ``safe``
    requires the projected path to stay at least ``safe_margin`` stationary
    sigmas clear of the threshold over the whole horizon.
    """
    sign = float(direction)
    breached = (fit.last - threshold) * sign >= 0
    path = expected_path(fit, horizon)
    excess = (path - threshold) * sign        # >0 once crossed
    months = None
    if not breached:
        idx = np.where(excess >= 0)[0]
        if idx.size:
            months = float(idx[0] + 1)
    peak = float(excess.max())
    start_gap = abs(fit.last - threshold)
    peak_ratio = float((peak + start_gap) / start_gap) if start_gap > 0 else np.inf
    safe = (not breached and months is None
            and excess.max() <= -safe_margin * fit.sigma_inf)
    return DangerCheck(axis=axis, threshold=threshold, breached=breached,
                       months_to_cross=months, peak_ratio=peak_ratio, safe=safe)
