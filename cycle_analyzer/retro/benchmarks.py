"""Point-in-time inflation benchmarks for retrospective editions.

The universe carries one benchmark per economy. A retrospective edition uses
the benchmark *publicly known at its cutoff*: a change applies only to
editions whose last eligible day is on or after the announcement date. The
benchmark in force at the cutoff is held constant through that edition's
historical fit (past target regimes are not reconstructed).
"""

from __future__ import annotations

from datetime import date

from ..universe import COUNTRIES
from .editions import Edition

# Benchmark changes announced after the universe benchmark was set.
CHANGES: dict[str, list[dict]] = {
    "CN": [{
        "announced": "2025-03-05",
        "target": 2.0,
        "label": ("2025 Report on the Work of the Government, delivered 5 March 2025: "
                  "main targets include a “CPI increase of around 2 percent”"),
        "url": "https://wb.beijing.gov.cn/en/express/202503/t20250305_4026328.html",
    }],
}


def change_in_force(cc: str, ed: Edition) -> dict | None:
    """Latest benchmark change for ``cc`` announced on or before the edition's
    last eligible day, or None if the universe benchmark still applies."""
    best = None
    for ch in CHANGES.get(cc, []):
        if date.fromisoformat(ch["announced"]) <= ed.last_eligible_day:
            if best is None or ch["announced"] > best["announced"]:
                best = ch
    return best


def targets_for(ed: Edition) -> dict[str, float]:
    out = {cc: c.infl_target for cc, c in COUNTRIES.items()}
    for cc in CHANGES:
        ch = change_in_force(cc, ed)
        if ch is not None:
            out[cc] = float(ch["target"])
    return out


def china_note(ed: Edition) -> str:
    ch = change_in_force("CN", ed)
    if ch is None:
        return ("China’s 3% is the government’s last announced annual CPI objective (for "
                "2024, “around 3%”), not a formal PBoC inflation target.")
    return (f"China’s 2% is the government’s annual CPI objective for 2025 (“around 2 "
            f"percent”, announced {ch['announced']} in the Report on the Work of the "
            "Government; it replaced 2024’s “around 3%”), not a formal PBoC inflation "
            "target.")
