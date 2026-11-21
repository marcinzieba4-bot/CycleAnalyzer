"""Vintage-aware fetchers with byte retention and a source ledger.

Every download is cached by URL (raw bytes, never modified) and recorded in
a ledger entry carrying the URL, SHA-256 of the exact bytes, the retrieval
time and the *availability bound* that makes the source eligible for an
edition (git commit time, ALFRED vintage date, ...).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.parse
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "retro_cache"          # raw bytes (gitignored)

GITLAB = "https://git.nomics.world/api/v4/projects"
OECD_PROJECT = 140      # dbnomics-json-data/oecd-json-data
BIS_PROJECT = 145       # dbnomics-json-data/bis-json-data
REPO_WEB = {OECD_PROJECT: "https://git.nomics.world/dbnomics-json-data/oecd-json-data",
            BIS_PROJECT: "https://git.nomics.world/dbnomics-json-data/bis-json-data"}


@dataclass
class LedgerEntry:
    id: str
    url: str
    sha256: str
    nbytes: int
    retrieved_at: str
    available_by: str      # ISO timestamp: upper bound on when this was public
    kind: str              # "dbnomics-git" | "alfred" | "bis-current" | ...
    note: str
    proof_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str, timeout: int = 300, tries: int = 4) -> bytes:
    err = ""
    for k in range(tries):
        p = subprocess.run(["curl", "-sS", "--fail", "-L", "-m", str(timeout), url],
                           capture_output=True)
        if p.returncode == 0 and p.stdout:
            return p.stdout
        err = p.stderr.decode(errors="replace")[:200]
        time.sleep(3 * (k + 1))
    raise ConnectionError(f"GET failed: {url} ({err})")


def cached_get(url: str) -> tuple[bytes, str, str]:
    """Return (bytes, sha256, retrieved_at); downloads once per URL."""
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    body, meta = CACHE / f"{key}.bin", CACHE / f"{key}.json"
    if body.exists() and meta.exists():
        b = body.read_bytes()
        m = json.loads(meta.read_text())
        if hashlib.sha256(b).hexdigest() == m["sha256"]:
            return b, m["sha256"], m["retrieved_at"]
    b = http_get(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    body.write_bytes(b)
    sha = hashlib.sha256(b).hexdigest()
    meta.write_text(json.dumps({"url": url, "sha256": sha, "retrieved_at": _now(),
                                "nbytes": len(b)}))
    return b, sha, json.loads(meta.read_text())["retrieved_at"]


# ------------------------------------------------------------ DBnomics git

def _q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def latest_commit_before(project: int, path: str, cutoff_utc: str) -> dict:
    """Newest commit touching ``path`` whose created_at AND committed_date are
    strictly before the cutoff. Commit listings are fetched live (they are
    metadata about immutable history, not data)."""
    cut = datetime.fromisoformat(cutoff_utc.replace("Z", "+00:00"))
    commits = None
    # Path-filtered history on a large repository is expensive and the API
    # intermittently 500s; bound the window and widen it only if empty.
    for days in (45, 120, 400):
        since = (cut - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (f"{GITLAB}/{project}/repository/commits?path={_q(path)}"
               f"&since={since}&until={cutoff_utc}&per_page=50")
        for k in range(6):
            try:
                commits = json.loads(http_get(url, tries=2))
                break
            except ConnectionError:
                time.sleep(10 * (k + 1))
        if isinstance(commits, list) and commits:
            break
    if not isinstance(commits, list):
        raise RuntimeError(f"commit listing failed for {path}: {commits}")
    for c in commits:          # newest first
        ts = [datetime.fromisoformat(c[k]) for k in ("created_at", "committed_date")]
        if all(t < cut for t in ts):
            return c
    raise RuntimeError(f"no pre-cutoff commit for {path} before {cutoff_utc}")


def dbnomics_file(project: int, path: str, cutoff_utc: str, ledger_id: str,
                  note: str) -> tuple[bytes, LedgerEntry]:
    c = latest_commit_before(project, path, cutoff_utc)
    sha_commit = c["id"]
    url = f"{GITLAB}/{project}/repository/files/{_q(path)}/raw?ref={sha_commit}"
    b, sha, got = cached_get(url)
    e = LedgerEntry(
        id=f"{ledger_id}-{sha_commit[:12]}", url=url, sha256=sha, nbytes=len(b),
        retrieved_at=got, available_by=c["committed_date"], kind="dbnomics-git",
        note=(f"{note} Immutable DBnomics git commit {sha_commit} "
              f"(created {c['created_at']}, committed {c['committed_date']}), "
              f"both before the cutoff. Commit time is an availability upper bound; "
              f"no exact original release time is claimed."),
        proof_url=f"{REPO_WEB[project]}/-/commit/{sha_commit}")
    return b, e


def read_jsonl_series(b: bytes, codes: set[str] | None = None) -> dict[str, list]:
    """DBnomics series.jsonl -> {code: [(period, value), ...]} (numeric only)."""
    out: dict[str, list] = {}
    for line in b.decode("utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        code = d["code"]
        if codes is not None and code not in codes:
            continue
        obs = d.get("observations") or []
        rows = []
        for o in obs[1:]:
            v = o[1]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rows.append((str(o[0]), float(v)))
        out[code] = rows
    return out


# ------------------------------------------------------------------ ALFRED

def alfred(series_id: str, vintage_date: str) -> tuple[bytes, LedgerEntry]:
    url = (f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series_id}"
           f"&vintage_date={vintage_date}")
    b, sha, got = cached_get(url)
    e = LedgerEntry(
        id=f"alfred-{series_id.lower()}-{vintage_date}", url=url, sha256=sha,
        nbytes=len(b), retrieved_at=got,
        available_by=f"{vintage_date}T23:59:59-06:00", kind="alfred",
        note=("Historical ALFRED vintage_date is the requested information set. "
              "Conservative availability bound is the end of that Friday in "
              "America/Chicago, strictly before Sunday 00:00 Europe/Warsaw. No "
              "exact original release intraday time is invented."),
        proof_url=f"https://alfred.stlouisfed.org/series?seid={series_id}")
    return b, e


def parse_alfred_csv(b: bytes) -> list[tuple[str, float]]:
    lines = b.decode("utf-8").strip().splitlines()
    rows = []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) >= 2 and parts[1] not in (".", "", "NA"):
            try:
                rows.append((parts[0], float(parts[1])))
            except ValueError:
                pass
    return rows


# ------------------------------------------------------ BIS current (daily)

def bis_daily_current(iso2: str, start: str, end: str) -> tuple[bytes, LedgerEntry]:
    """Current BIS daily policy history between two dates. Used only to date
    publicly announced decisions; never as an archived statistical vintage."""
    url = (f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{iso2}"
           f"?format=csv&startPeriod={start}&endPeriod={end}")
    b, sha, got = cached_get(url)
    e = LedgerEntry(
        id=f"bis-daily-{iso2.lower()}-{start}-{end}", url=url, sha256=sha,
        nbytes=len(b), retrieved_at=got, available_by="n/a (decision facts)",
        kind="bis-current",
        note=("Current BIS daily policy history, read only for the dates of "
              "publicly announced decisions effective before the cutoff; not an "
              "archived statistical vintage."))
    return b, e


def parse_bis_csv(b: bytes) -> list[tuple[str, float]]:
    import csv
    import io
    rows = []
    for r in csv.DictReader(io.StringIO(b.decode("utf-8"))):
        v = r.get("OBS_VALUE")
        if v not in (None, "", "NaN"):
            rows.append((r["TIME_PERIOD"], float(v)))
    return sorted(rows)
