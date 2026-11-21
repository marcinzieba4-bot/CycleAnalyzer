"""Build the model's input panels from pre-cutoff vintages only.

Output mirrors ``cycle_analyzer.data.load_panel``: a dict of monthly
DataFrames ('policy', 'cpi', 'reer', 'cli', 'y10') indexed by month start,
plus an ``Evidence`` bundle that documents every source, observation date,
gap, CPI candidate decision and the policy snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..universe import COUNTRIES
from . import sources as S
from .editions import Edition

OUT_ROOT = S.ROOT / "data" / "retro"

# Growth inputs ------------------------------------------------------------
KEI_PATH = "DSD_KEI@DF_KEI/series.jsonl"
BTS_PATH = "DSD_STES@DF_BTS/series.jsonl"
CLI_13 = ["US", "JP", "GB", "CA", "AU", "CN", "IN", "BR", "MX", "ZA", "TR", "ID", "KR"]
BCI_MONTHLY = {"XM": "EA19", "CH": "CHE", "SE": "SWE", "PL": "POL", "HU": "HUN",
               "CZ": "CZE", "CL": "CHL", "CO": "COL"}
BCI_QUARTERLY = {"NO": "NOR", "NZ": "NZL"}

# Inflation inputs ---------------------------------------------------------
BIS_CPI_PATH = "WS_LONG_CPI/series.jsonl"
PRICES_PATH = "DSD_PRICES@DF_PRICES_ALL/series.jsonl"
# Matching-definition candidates, in tie-break priority order. UK: CPI (the
# OECD "national" UK series is CPIH, so only BIS and the HICP-coded CPI
# qualify). India: Combined CPI only (BIS); the OECD India series is a
# different index. Japan, Thailand: BIS only (OECD archive stale/absent).
CPI_CANDIDATES = {
    "US": ["alfred_cpiaucns", "bis"],
    "XM": ["bis", "oecd_hicp", "kei_m"],
    "GB": ["bis", "oecd_hicp"],
    "IN": ["bis"],
    "JP": ["bis"],
    "TH": ["bis"],
    "AU": ["bis", "oecd_q", "kei_q"],
    "NZ": ["bis", "oecd_q", "kei_q"],
}
CPI_DEFAULT = ["bis", "oecd_n", "kei_m"]

# Policy -------------------------------------------------------------------
BIS_POL_PATH = "WS_CBPOL/series.jsonl"
DAILY_START = "2023-06-01"    # decision-history window start; the window ends on
                              # each edition's last eligible day (never later)

REER_ALFRED = {cc: f"RB{cc}BIS" for cc in COUNTRIES}


@dataclass
class PolicySnap:
    cc: str
    monthly_last: str           # last completed month in the training matrix
    monthly_value: float
    current: float              # effective at the cutoff
    effective_since: str        # date the current rate took effect
    archive_daily_end: str      # last day covered by the archived daily series
    source: str


@dataclass
class Evidence:
    edition: str
    cutoff_utc: str
    anchor: str
    ledger: dict = field(default_factory=dict)          # id -> LedgerEntry
    obs: dict = field(default_factory=dict)             # cc -> family -> 'YYYY-MM'
    gaps: dict = field(default_factory=dict)            # 'family/cc' -> [months]
    cpi_choice: dict = field(default_factory=dict)      # cc -> dict
    growth_def: dict = field(default_factory=dict)      # cc -> str
    policy: dict = field(default_factory=dict)          # cc -> PolicySnap
    announcements: list = field(default_factory=list)   # decisions after archive
    extensions: list = field(default_factory=list)      # month-ends filled from decisions
    notes: list = field(default_factory=list)

    def add(self, e: S.LedgerEntry) -> str:
        self.ledger[e.id] = e
        return e.id

    def to_json(self) -> dict:
        return {
            "edition": self.edition, "cutoff_utc": self.cutoff_utc, "anchor": self.anchor,
            "ledger": {k: v.to_dict() for k, v in self.ledger.items()},
            "obs": self.obs, "gaps": self.gaps, "cpi_choice": self.cpi_choice,
            "growth_def": self.growth_def,
            "policy": {k: v.__dict__ for k, v in self.policy.items()},
            "announcements": self.announcements, "extensions": self.extensions,
            "notes": self.notes,
        }


# ----------------------------------------------------------------- helpers

def _monthly(rows: list[tuple[str, float]]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({p: v for p, v in rows}, dtype=float)
    s.index = pd.PeriodIndex(s.index, freq="M")
    return s.sort_index()


def _quarterly_to_monthly(rows: list[tuple[str, float]]) -> pd.Series:
    """Repeat each known quarter across its own three reference months."""
    out = {}
    for p, v in rows:
        q = pd.Period(p, freq="Q")
        for m in pd.period_range(q.asfreq("M", "s"), q.asfreq("M", "e"), freq="M"):
            out[m] = v
    return pd.Series(out, dtype=float).sort_index()


def _ts(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = s.index.to_timestamp()
    return s


GAP_FROM = pd.Period("1985-01", freq="M")   # earliest month the fits/rolling windows touch


def _gaps(s: pd.Series) -> list[str]:
    s = s.dropna()
    if s.empty:
        return []
    full = pd.period_range(max(s.index.min(), GAP_FROM), s.index.max(), freq="M")
    return [str(p) for p in full.difference(s.index)]


def _cap(s: pd.Series, ed: Edition) -> pd.Series:
    """Belt and braces: drop any reference month at or after the edition month
    (a monthly observation for the current month cannot be complete yet)."""
    return s[s.index <= ed.anchor]


# ------------------------------------------------------------------ build

def build(ed: Edition, verbose: bool = True) -> tuple[dict[str, pd.DataFrame], Evidence]:
    ev = Evidence(edition=ed.iso, cutoff_utc=ed.cutoff_iso, anchor=str(ed.anchor))
    cut = ed.cutoff_iso
    log = print if verbose else (lambda *a, **k: None)

    # ---- archives (one immutable commit each) ----------------------------
    log("archives: OECD KEI / BTS / PRICES, BIS CPI / CBPOL")
    kei_b, kei_e = S.dbnomics_file(S.OECD_PROJECT, KEI_PATH, cut, "dbnomics-oecd-kei",
                                   "OECD Key Economic Indicators (CLI, CPI).")
    bts_b, bts_e = S.dbnomics_file(S.OECD_PROJECT, BTS_PATH, cut, "dbnomics-oecd-bts",
                                   "OECD business tendency surveys (composite confidence).")
    pr_b, pr_e = S.dbnomics_file(S.OECD_PROJECT, PRICES_PATH, cut, "dbnomics-oecd-prices",
                                 "OECD consumer prices (DF_PRICES_ALL).")
    bcpi_b, bcpi_e = S.dbnomics_file(S.BIS_PROJECT, BIS_CPI_PATH, cut, "dbnomics-bis-cpi",
                                     "BIS WS_LONG_CPI (model-native CPI y/y).")
    bpol_b, bpol_e = S.dbnomics_file(S.BIS_PROJECT, BIS_POL_PATH, cut, "dbnomics-bis-cbpol",
                                     "BIS WS_CBPOL (policy rates, monthly + daily).")
    for e in (kei_e, bts_e, pr_e, bcpi_e, bpol_e):
        ev.add(e)
    kei = S.read_jsonl_series(kei_b)
    bts = S.read_jsonl_series(bts_b)
    prices = S.read_jsonl_series(pr_b)
    bcpi = S.read_jsonl_series(bcpi_b)
    bpol = S.read_jsonl_series(bpol_b)

    panels: dict[str, dict[str, pd.Series]] = {k: {} for k in
                                               ("policy", "cpi", "reer", "cli", "y10")}

    def record(family: str, cc: str, s: pd.Series):
        s = s.dropna()
        ev.obs.setdefault(cc, {})[family] = str(s.index.max()) if len(s) else None
        g = _gaps(s)
        if g:
            ev.gaps[f"{family}/{cc}"] = g

    # ---- growth -----------------------------------------------------------
    for cc in CLI_13:
        code = f"{COUNTRIES[cc].iso3}.M.LI.IX._T.AA._Z"
        s = _cap(_monthly(kei.get(code, [])), ed)
        if len(s):
            panels["cli"][cc] = s
            ev.growth_def[cc] = (f"OECD composite leading indicator, amplitude adjusted "
                                 f"({code}, KEI archive {kei_e.proof_url.rsplit('/', 1)[-1][:12]})")
            record("cli", cc, s)
    for cc, i3 in {**BCI_MONTHLY, **BCI_QUARTERLY}.items():
        q = cc in BCI_QUARTERLY
        code = f"{i3}.{'Q' if q else 'M'}.BCICP.PB.C.Y._Z._Z.N"
        rows = bts.get(code, [])
        if not rows:
            continue
        s = _quarterly_to_monthly(rows) if q else _monthly(rows)
        s = _cap(s, ed)
        # Normalized proxy on the model's CLI scale: 100 + deviation from the
        # series' own full pre-cutoff average. The model divides by its own
        # trailing dispersion, so only the centring matters, and it uses
        # nothing published after the cutoff.
        s = 100.0 + (s - s.mean())
        panels["cli"][cc] = s
        ev.growth_def[cc] = (
            f"OECD composite business confidence ({code}), percent balance normalized "
            f"to 100 + deviation from its own pre-cutoff average — a proxy for the "
            f"amplitude-adjusted confidence index, not a CLI"
            + ("; quarterly survey repeated across its three reference months" if q else "")
            + ("; EA19 aggregate used as euro-area proxy against EA20 inflation"
               if cc == "XM" else ""))
        record("cli", cc, s)

    # ---- inflation ----------------------------------------------------------
    alfred_us_b, alfred_us_e = S.alfred("CPIAUCNS", ed.alfred_vintage.isoformat())
    us_idx = _monthly([(p[:7], v) for p, v in S.parse_alfred_csv(alfred_us_b)])
    us_full = pd.period_range(us_idx.index.min(), us_idx.index.max(), freq="M")
    us_idx = us_idx.reindex(us_full)
    us_yoy = (100.0 * (us_idx / us_idx.shift(12) - 1.0)).dropna()

    for cc, c in COUNTRIES.items():
        i3 = "EA20" if cc == "XM" else c.iso3
        cands = {
            "bis": (_monthly(bcpi.get(f"M.{cc}.771", [])), bcpi_e,
                    f"BIS WS_LONG_CPI M.{cc}.771"),
            "oecd_n": (_monthly(prices.get(f"{i3}.M.N.CPI.PA._T.N.GY", [])), pr_e,
                       f"OECD {i3}.M.N.CPI.PA._T.N.GY"),
            "oecd_hicp": (_monthly(prices.get(f"{i3}.M.HICP.CPI.PA._T.N.GY", [])), pr_e,
                          f"OECD {i3}.M.HICP.CPI.PA._T.N.GY (HICP-coded; UK CPI)"),
            "oecd_q": (_quarterly_to_monthly(prices.get(f"{i3}.Q.N.CPI.PA._T.N.GY", [])),
                       pr_e, f"OECD {i3}.Q.N.CPI.PA._T.N.GY (quarterly)"),
            "kei_m": (_monthly(kei.get(f"{i3}.M.CP.GR._Z._Z.GY", [])), kei_e,
                      f"OECD KEI {i3}.M.CP.GR._Z._Z.GY"),
            "kei_q": (_quarterly_to_monthly(kei.get(f"{i3}.Q.CP.GR._Z._Z.GY", [])),
                      kei_e, f"OECD KEI {i3}.Q.CP.GR._Z._Z.GY (quarterly)"),
            "alfred_cpiaucns": (us_yoy, alfred_us_e,
                                "BLS CPI-U all items NSA (CPIAUCNS), ALFRED vintage, "
                                "true calendar-month y/y"),
        }
        order = CPI_CANDIDATES.get(cc, CPI_DEFAULT)
        best, best_last = None, None
        considered = []
        for k in order:
            s, e, lbl = cands[k]
            s = _cap(s.dropna(), ed)
            if s.empty:
                continue
            considered.append({"candidate": lbl, "last": str(s.index.max()),
                               "last_value": round(float(s.iloc[-1]), 3)})
            if best is None or s.index.max() > best_last:
                best, best_last = (k, s, e, lbl), s.index.max()
        if best is None:
            continue
        k, s, e, lbl = best
        ev.add(e)
        s, supp = _apply_original_releases(cc, s, ed, ev)
        panels["cpi"][cc] = s
        ref_bis = _cap(cands["bis"][0].dropna(), ed)
        agree = None
        if k != "bis" and len(ref_bis):
            j = pd.concat([s, ref_bis], axis=1).dropna().tail(60)
            if len(j):
                agree = round(float((j.iloc[:, 0] - j.iloc[:, 1]).abs().mean()), 3)
        ev.cpi_choice[cc] = {"chosen": lbl + (" + original releases" if supp else ""),
                             "ledger": e.id, "last": str(s.index.max()),
                             "last_value": round(float(s.iloc[-1]), 3),
                             "considered": considered, "supplements": supp,
                             "mean_abs_diff_vs_bis_60m": agree,
                             "quarterly": k in ("oecd_q", "kei_q") or cc in ("AU", "NZ")}
        record("cpi", cc, s)

    # ---- REER + 10y (ALFRED Friday vintages) ------------------------------
    vint = ed.alfred_vintage.isoformat()
    for cc in COUNTRIES:
        b, e = S.alfred(REER_ALFRED[cc], vint)
        s = _cap(_monthly([(p[:7], v) for p, v in S.parse_alfred_csv(b)]), ed)
        if len(s):
            ev.add(e)
            panels["reer"][cc] = s
            record("reer", cc, s)
        fid = COUNTRIES[cc].fred_10y
        if fid:
            b, e = S.alfred(fid, vint)
            s = _cap(_monthly([(p[:7], v) for p, v in S.parse_alfred_csv(b)]), ed)
            if len(s):
                ev.add(e)
                panels["y10"][cc] = s
                record("y10", cc, s)

    # ---- policy -------------------------------------------------------------
    _build_policy(ed, ev, bpol, bpol_e, panels, record, log)

    out = {}
    for k, d in panels.items():
        d = {cc: _ts(s) for cc, s in d.items() if len(s)}
        out[k] = pd.DataFrame(d).sort_index() if d else pd.DataFrame()
    return out, ev


RELEASES_FILE = OUT_ROOT / "original_releases.json"


def _apply_original_releases(cc: str, s: pd.Series, ed: Edition, ev: Evidence):
    """Append verified original national releases for reference months after
    the archived history ends — only releases published on or before the last
    day wholly before the cutoff, only contiguous months, never overwriting an
    archived value. Returns (series, list of applied releases)."""
    if not RELEASES_FILE.exists():
        return s, []
    rel = [r for r in json.loads(RELEASES_FILE.read_text()).get("cpi", [])
           if r["cc"] == cc and date.fromisoformat(r["released"]) <= ed.last_eligible_day]
    latest: dict[str, dict] = {}          # latest eligible print per reference month
    for r in rel:
        if r["ref"] not in latest or r["released"] > latest[r["ref"]]["released"]:
            latest[r["ref"]] = r
    applied = []
    s = s.copy()
    for r in sorted(latest.values(), key=lambda r: r["ref"]):
        p = pd.Period(r["ref"], freq="M")
        if p in s.index or p > ed.anchor or p != s.index.max() + 1:
            continue
        s.loc[p] = float(r["value"])
        e = S.LedgerEntry(
            id=f"original-{cc.lower()}-cpi-{r['ref']}", url=r["url"],
            sha256=r.get("sha256", "n/a"), nbytes=0, retrieved_at=r.get("verified", ""),
            available_by=f"{r['released']} (publication date)", kind="original-release",
            note=(f"{r['label']}: {r['ref']} headline y/y {r['value']}% as printed at first "
                  f"release on {r['released']}, before the cutoff. Appended after the "
                  f"archived history; no archived value is overwritten."))
        ev.add(e)
        applied.append({"ref": r["ref"], "value": r["value"], "released": r["released"],
                        "label": r["label"], "url": r["url"]})
    return s.sort_index(), applied


def _daily(rows: list[tuple[str, float]]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(p): v for p, v in rows}, dtype=float)
    return s.sort_index()


def _value_on(s: pd.Series, day: date) -> float | None:
    s = s[s.index <= pd.Timestamp(day)]
    return float(s.iloc[-1]) if len(s) else None


def _build_policy(ed, ev, bpol, bpol_e, panels, record, log):
    last_day = ed.last_eligible_day
    for cc in COUNTRIES:
        m = _monthly(bpol.get(f"M.{cc}", []))
        d_arch = _daily(bpol.get(f"D.{cc}", []))
        b, e_cur = S.bis_daily_current(cc, DAILY_START, last_day.isoformat())
        d_cur = _daily(S.parse_bis_csv(b))
        d_cur = d_cur[d_cur.index <= pd.Timestamp(last_day)]
        if len(d_arch) and len(d_cur):
            # consistency: decision facts must agree with the archived daily
            j = pd.concat([d_arch, d_cur], axis=1, keys=["a", "c"]).dropna()
            bad = j[(j.a - j.c).abs() > 1e-6]
            if len(bad):
                ev.notes.append(f"policy/{cc}: current daily history differs from the "
                                f"archived daily on {len(bad)} days; archive retained.")
        arch_end = d_arch.index.max().date() if len(d_arch) else None
        # merged daily: archive where it exists, decision facts afterwards
        tail = d_cur[d_cur.index > pd.Timestamp(arch_end)] if arch_end else d_cur
        d_all = pd.concat([d_arch, tail]).sort_index()
        d_all = d_all[d_all.index <= pd.Timestamp(last_day)]

        # completed months: archived monthly, extended to the anchor with
        # month-end values of publicly announced targets
        m = m[m.index <= ed.anchor]
        last_m = m.index.max() if len(m) else None
        ext = []
        if last_m is not None and last_m < ed.anchor:
            for p in pd.period_range(last_m + 1, ed.anchor, freq="M"):
                v = _value_on(d_all, p.end_time.date())
                if v is not None:
                    m.loc[p] = v
                    src = ("archived daily" if arch_end and p.end_time.date() <= arch_end
                           else "announced target (BIS daily decision history)")
                    ext.append({"cc": cc, "month": str(p), "value": v, "source": src})
        m = m.sort_index()
        ev.extensions += ext
        if len(ext) and any(x["source"].startswith("announced") for x in ext):
            ev.add(e_cur)

        cur = _value_on(d_all, last_day)
        if cur is None:
            cur = float(m.iloc[-1])
        # date the current level took effect (first day after the last
        # different value); unknown if unchanged over the whole window
        chg = d_all[(d_all - cur).abs() > 1e-9]
        if len(chg):
            since_txt = d_all[d_all.index > chg.index.max()].index.min().date().isoformat()
        else:
            since_txt = f"on or before {d_all.index.min().date().isoformat()}" if len(d_all) else "n/a"
        # decisions effective after the archived daily ends
        if arch_end is not None:
            post = d_all[d_all.index > pd.Timestamp(arch_end)]
            prev = _value_on(d_arch, arch_end)
            for t, v in post.items():
                if prev is not None and abs(v - prev) > 1e-9:
                    ev.announcements.append({"cc": cc, "effective": t.date().isoformat(),
                                             "from": prev, "to": v})
                    ev.add(e_cur)
                prev = v
        panels["policy"][cc] = m
        record("policy", cc, m)
        ev.policy[cc] = PolicySnap(
            cc=cc, monthly_last=str(m.index.max()), monthly_value=float(m.iloc[-1]),
            current=cur, effective_since=since_txt,
            archive_daily_end=arch_end.isoformat() if arch_end else "",
            source=bpol_e.id)


def save(ed: Edition, panels: dict[str, pd.DataFrame], ev: Evidence) -> Path:
    """Retain the exact model inputs and evidence in the repository."""
    out = OUT_ROOT / ed.iso
    out.mkdir(parents=True, exist_ok=True)
    for k, df in panels.items():
        df.to_csv(out / f"{k}.csv", index_label="date")
    (out / "evidence.json").write_text(json.dumps(ev.to_json(), indent=1, default=str))
    return out
