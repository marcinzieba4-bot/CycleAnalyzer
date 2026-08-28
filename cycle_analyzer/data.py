"""Data layer: fetch monthly series from BIS, OECD (DBnomics) and FRED.

Every fetched series is cached as ``data/raw/<source>__<safe_code>.csv``
(columns: date,value). ``load_panel(refresh=False)`` reads the cache, so the
whole pipeline is reproducible offline; ``refresh=True`` re-downloads and
falls back to the cached copy when a source is unreachable.

HTTP is done through ``curl`` (some endpoints reject plain urllib through
proxies); a urllib fallback is kept for environments without curl.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import pandas as pd

from .universe import COUNTRIES

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


# ---------------------------------------------------------------- HTTP layer

def _http_get(url: str, timeout: int = 60, tries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(tries):
        try:
            proc = subprocess.run(
                ["curl", "-sS", "--fail", "-m", str(timeout), url],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                return proc.stdout
            last_err = RuntimeError(proc.stderr.strip()[:200])
        except FileNotFoundError:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "cycle-analyzer/0.1"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                last_err = e
        time.sleep(2 * (attempt + 1))
    raise ConnectionError(f"GET failed after {tries} tries: {url} ({last_err})")


# ------------------------------------------------------------------ fetchers

def fetch_bis(flow: str, key: str, start: str = "1990-01") -> pd.Series:
    """BIS SDMX v2 CSV, e.g. flow='WS_CBPOL', key='M.US'."""
    url = (f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}"
           f"?format=csv&startPeriod={start}")
    rows = list(csv.DictReader(io.StringIO(_http_get(url))))
    out = {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")}
    s = pd.Series(out, dtype=float)
    s.index = pd.PeriodIndex(s.index, freq="M").to_timestamp()
    return s.sort_index()


def fetch_dbnomics(provider: str, dataset: str, code: str) -> pd.Series:
    url = (f"https://api.db.nomics.world/v22/series/{provider}/{dataset}/{code}"
           f"?observations=1")
    j = json.loads(_http_get(url))
    docs = j["series"]["docs"]
    if not docs:
        raise KeyError(f"no series {provider}/{dataset}/{code}")
    d = docs[0]
    pairs = {p: v for p, v in zip(d["period"], d["value"]) if isinstance(v, (int, float))}
    s = pd.Series(pairs, dtype=float)
    s.index = pd.PeriodIndex(s.index, freq="M").to_timestamp()
    return s.sort_index()


def fetch_fred(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    rows = [r for r in csv.reader(io.StringIO(_http_get(url)))][1:]
    out = {r[0]: float(r[1]) for r in rows if len(r) == 2 and r[1] not in (".", "")}
    s = pd.Series(out, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


# ----------------------------------------------------------------- cache I/O

def _cache_path(source: str, code: str) -> Path:
    safe = code.replace("/", "-").replace(".", "_").replace("@", "-")
    return DATA_DIR / f"{source}__{safe}.csv"


def _read_cache(path: Path) -> pd.Series | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return pd.Series(df["value"].values, index=df["date"], dtype=float)


def _write_cache(path: Path, s: pd.Series) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": s.index, "value": s.values}).to_csv(path, index=False)


def get_series(source: str, code: str, refresh: bool = False) -> pd.Series | None:
    """Fetch one series with caching. source in {'bis:FLOW','oecd','fred'}."""
    path = _cache_path(source, code)
    if not refresh:
        cached = _read_cache(path)
        if cached is not None:
            return cached
    try:
        if source.startswith("bis:"):
            s = fetch_bis(source.split(":", 1)[1], code)
        elif source == "oecd":
            s = fetch_dbnomics("OECD", "DSD_STES@DF_CLI", code)
        elif source == "fred":
            s = fetch_fred(code)
        else:
            raise ValueError(source)
    except Exception as e:  # noqa: BLE001
        cached = _read_cache(path)
        if cached is not None:
            print(f"  [warn] {source}/{code}: fetch failed ({e}); using cache")
            return cached
        print(f"  [warn] {source}/{code}: unavailable ({e})")
        return None
    _write_cache(path, s)
    return s


# ------------------------------------------------------------- panel builder

def load_panel(refresh: bool = False, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Build indicator panels: dict of DataFrames indexed by month.

    Keys: 'policy', 'cpi', 'reer', 'cli', 'y10' — columns are iso2 codes.
    """
    panels: dict[str, dict[str, pd.Series]] = {
        "policy": {}, "cpi": {}, "reer": {}, "cli": {}, "y10": {},
    }
    for iso2, c in COUNTRIES.items():
        if verbose:
            print(f"loading {c.name} ({iso2})")
        panels["policy"][iso2] = get_series("bis:WS_CBPOL", f"M.{iso2}", refresh)
        panels["cpi"][iso2] = get_series("bis:WS_LONG_CPI", f"M.{iso2}.771", refresh)
        panels["reer"][iso2] = get_series("bis:WS_EER", f"M.R.B.{iso2}", refresh)
        if c.cli_code:
            panels["cli"][iso2] = get_series("oecd", c.cli_code, refresh)
        if c.fred_10y:
            panels["y10"][iso2] = get_series("fred", c.fred_10y, refresh)

    out: dict[str, pd.DataFrame] = {}
    for k, d in panels.items():
        d = {cc: s for cc, s in d.items() if s is not None}
        out[k] = pd.DataFrame(d).sort_index() if d else pd.DataFrame()
    return out
