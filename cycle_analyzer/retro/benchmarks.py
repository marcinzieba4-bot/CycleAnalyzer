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
    "CN": [
        {"announced": "2025-03-05", "target": 2.0, "year": 2025,
         "label": ("2025 Report on the Work of the Government, delivered 5 March 2025: "
                   "main targets include a “CPI increase of around 2 percent”"),
         "url": "https://wb.beijing.gov.cn/en/express/202503/t20250305_4026328.html"},
        {"announced": "2026-03-05", "target": 2.0, "year": 2026,
         "label": ("Highlights of the 2026 Government Work Report, submitted 5 March 2026: "
                   "a “consumer price index increase of around 2 percent”"),
         "url": ("https://english.shanghai.gov.cn/en-Latest-WhatsNew/20260305/"
                 "9a66991969a5454d99efe5e8f40fa976.html")},
    ],
    "ZA": [
        {"announced": "2025-11-12", "target": 3.0,
         "label": ("Treasury and South African Reserve Bank announce new inflation target "
                   "for South Africa, 12 November 2025: 3% with a 1 percentage point "
                   "tolerance band, immediately replacing the 3–6% range"),
         "url": ("https://www.gov.za/news/media-statements/treasury-and-south-african-"
                 "reserve-bank-announce-new-inflation-target-south")},
    ],
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
    prev = ("it replaced 2024’s “around 3%”" if ch["year"] == 2025
            else "unchanged from 2025’s “around 2 percent”")
    return (f"China’s 2% is the government’s annual CPI objective for {ch['year']} (“around "
            f"2 percent”, announced {ch['announced']} in the Report on the Work of the "
            f"Government; {prev}), not a formal PBoC inflation target.")


def south_africa_note(ed: Edition) -> str:
    ch = change_in_force("ZA", ed)
    if ch is None:
        return "South Africa’s 4.5% the midpoint of its 3–6% target range."
    return (f"South Africa’s 3% is the point target with a ±1pp tolerance band announced "
            f"{ch['announced']} by the Minister of Finance in agreement with the SARB, "
            "immediately replacing the 3–6% range.")


def sources_in_force(ed: Edition) -> list[dict]:
    return [ch for cc in CHANGES if (ch := change_in_force(cc, ed)) is not None]
