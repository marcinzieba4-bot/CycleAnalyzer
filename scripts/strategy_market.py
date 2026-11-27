#!/usr/bin/env python3
"""Download the EX-POST market data used to score the strategy (never an edition input).

    python scripts/strategy_market.py

  data/strategy/fx_daily.csv       BIS WS_XRU daily, USD per unit of each currency
  data/strategy/policy_daily.csv   BIS WS_CBPOL daily policy rates (carry accrual)
  data/strategy/y10_monthly.csv    FRED IRLTLT01* monthly 10y yields (curve scoring)
"""
from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cycle_analyzer.universe import COUNTRIES  # noqa: E402

OUT = ROOT / "data" / "strategy"
START, END = "2007-06-01", "2026-11-30"


def get(url: str) -> str:
    for _ in range(4):
        r = subprocess.run(["curl", "-sS", "--fail", "-m", "180", url], capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode()
    raise RuntimeError(f"failed: {url}")


def bis(flow: str, key: str) -> pd.Series:
    t = get(f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}?format=csv"
            f"&startPeriod={START}&endPeriod={END}")
    rows = [r for r in csv.DictReader(io.StringIO(t)) if r.get("OBS_VALUE") not in (None, "", "NaN")]
    s = pd.Series({r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows}).sort_index()
    s.index = pd.to_datetime(s.index)
    return s


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fx, pol, y10 = {}, {}, {}
    for cc, c in COUNTRIES.items():
        if cc != "US":
            fx[c.ccy] = 1.0 / bis("WS_XRU", f"D.{cc}.{c.ccy}.A")
        pol[cc] = bis("WS_CBPOL", f"D.{cc}")
        if c.fred_10y:
            t = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={c.fred_10y}"
                    f"&cosd={START}&coed={END}")
            r = [l.split(",") for l in t.strip().splitlines()[1:]]
            y10[cc] = pd.Series({pd.Timestamp(k): float(v) for k, v in r if v not in ("", ".")})
        print(cc, len(fx.get(c.ccy, [])), len(pol[cc]), len(y10.get(cc, [])), flush=True)
    pd.DataFrame(fx).sort_index().round(8).to_csv(OUT / "fx_daily.csv", index_label="date")
    pd.DataFrame(pol).sort_index().to_csv(OUT / "policy_daily.csv", index_label="date")
    pd.DataFrame(y10).sort_index().to_csv(OUT / "y10_monthly.csv", index_label="date")


if __name__ == "__main__":
    main()
