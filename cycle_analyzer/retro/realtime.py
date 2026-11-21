"""Point-in-time inputs for editions that predate the DBnomics archives.

The DBnomics git archives start in the late 2010s and ALFRED holds no
2007-08 vintages of the REER, CLI or long-rate series, so editions such as
Q1 2008 are built from:

  growth (21)       OECD composite leading indicator, amplitude adjusted
                    (LI_AA), from the OECD real-time revisions database
                    (DSD_STES_REVISIONS@DF_STES_REVISIONS). The edition used is
                    the newest whose CLI was demonstrably public before the
                    cutoff (``data/retro/oecd_rt_editions.json``).
  CPI y/y (21)      OECD consumer-price index (CP) from the newest edition of
                    the same database whose edition month ended before the
                    cutoff; y/y is computed inside that single vintage.
                    United States: ALFRED CPIAUCNS Friday vintage (BLS).
  CPI CL/CO/TH      present-day BIS WS_LONG_CPI; reference months gated by a
                    one-full-month publication lag (no 2008 vintage exists)
  REER (24)         present-day BIS broad REER, same one-full-month gate
  10y yields (17)   present-day OECD/FRED monthly market yields, completed
                    months only (market data are not revised)
  policy (24)       BIS daily decision history through the last day wholly
                    before the cutoff; BIS monthly (end of period) through
                    the last completed month

Every download is retained byte-for-byte in the source ledger; a gated
present-day download is requested with an explicit end period, so its bytes
contain nothing beyond the gate (``scripts/retro_audit.py`` re-checks this).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date

import numpy as np
import pandas as pd

from ..universe import COUNTRIES
from . import sources as S
from .editions import Edition
from .panels import (Evidence, PolicySnap, OUT_ROOT, _monthly, _quarterly_to_monthly,
                     _gaps, _cap, _ts, _daily, _value_on)

OECD_RT = ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,"
           "DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0")
OECD_RT_PROOF = ("https://data-explorer.oecd.org/vis?df[ds]=dsDisseminateFinalDMZ&"
                 "df[id]=DSD_STES_REVISIONS%40DF_STES_REVISIONS&df[ag]=OECD.SDD.STES")
EDITIONS_FILE = OUT_ROOT / "oecd_rt_editions.json"

NO_RT = ["CL", "CO", "TH"]                 # not in the 2008 revisions-database editions
RT_AREA = {cc: ("EA18" if cc == "XM" else c.iso3) for cc, c in COUNTRIES.items()
           if cc not in NO_RT}
YOY_INDEX = {"CN"}       # archive stores China's CPI as same month of previous year = 100
QUARTERLY_CPI = {"AU", "NZ"}
STALE_MONTHS = 9         # an input whose latest observation is older is not used
DAILY_START = "2006-01-01"
DECISION_WINDOW_DAYS = 190
DECISION_MIN_PP = 0.10   # smaller moves are rounding/data noise, not decisions
LEVEL_EPS = 0.005        # BIS daily levels within this are the same rate (e.g. 7.2498 vs 7.25)
# BIS series that are daily market rates before the given date (Mexico: the
# overnight interbank rate became Banxico's operational target from that day;
# before it the daily level drifts with the market).
MARKET_RATE_BEFORE = {"MX": date(2008, 1, 21)}
ERA_LAST_DAY = date(2016, 12, 31)          # editions on or before use this builder

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def is_realtime(ed: Edition) -> bool:
    return ed.date <= ERA_LAST_DAY


def register() -> dict:
    return {k: v for k, v in json.loads(EDITIONS_FILE.read_text()).items()
            if not k.startswith("_")}


def edition_label(e: str) -> str:
    return f"{MONTHS[int(e[4:]) - 1]} {e[:4]}"


def _month_end(e: str) -> date:
    return pd.Period(f"{e[:4]}-{e[4:]}", freq="M").end_time.date()


def _month_end_edition(ed: Edition) -> str:
    """Newest edition whose edition month ended on or before the last eligible day."""
    d = ed.last_eligible_day
    p = pd.Period(d, freq="M")
    p = p if d == p.end_time.date() else p - 1
    return f"{p.year}{p.month:02d}"


def cli_edition(ed: Edition) -> tuple[str, str, str]:
    """(edition, public-by date, basis) for the growth input: the newest edition
    either evidenced public before the cutoff in the register, or whose edition
    month has ended."""
    reg = register()
    cands = {_month_end_edition(ed): (_month_end(_month_end_edition(ed)).isoformat(),
                                      "edition month end (conservative rule)")}
    for k, v in reg.items():
        if date.fromisoformat(v["cli_public_by"]) <= ed.last_eligible_day:
            if k not in cands or v["cli_public_by"] < cands[k][0]:
                cands[k] = (v["cli_public_by"], v["basis"])
    k = max(cands)
    return k, cands[k][0], cands[k][1]


def cpi_edition(ed: Edition) -> tuple[str, str, str]:
    e = _month_end_edition(ed)
    return e, _month_end(e).isoformat(), "edition month end (conservative rule)"


def gate_lag1(ed: Edition) -> pd.Period:
    """Newest reference month m whose whole following month (m+1) ended on or
    before the last eligible day: a conservative publication-lag gate for
    monthly statistics normally released within a few weeks."""
    d = ed.last_eligible_day
    p = pd.Period(d, freq="M")
    return p - 1 if d == p.end_time.date() else p - 2


# ------------------------------------------------------------------ fetchers

def oecd_rt(measure: str, edition: str, public_by: str, basis: str) -> tuple[bytes, S.LedgerEntry]:
    areas = "+".join(sorted(set(RT_AREA.values()) | {"OECD"}))
    url = f"{OECD_RT}/{areas}..{measure}...{edition}?format=csvfile"
    b, sha, got = S.cached_get(url)
    what = ("composite leading indicator, amplitude adjusted (LI_AA)" if measure == "LI_AA"
            else "consumer price index (CP)")
    e = S.LedgerEntry(
        id=f"oecd-rt-{measure.lower().replace('_', '')}-{edition}", url=url, sha256=sha,
        nbytes=len(b), retrieved_at=got, available_by=f"{public_by} ({basis})",
        kind="oecd-rt",
        note=(f"OECD real-time revisions database, {edition_label(edition)} edition, {what}: "
              "the values as published in that month's Main Economic Indicators edition, "
              "never revised afterwards. Eligibility: " + basis + "."),
        proof_url=OECD_RT_PROOF)
    return b, e


def parse_rt(b: bytes) -> dict[tuple[str, str], list[tuple[str, float]]]:
    out: dict[tuple[str, str], list] = {}
    for r in csv.DictReader(io.StringIO(b.decode("utf-8"))):
        v = r.get("OBS_VALUE")
        if v in (None, "", "NaN"):
            continue
        out.setdefault((r["REF_AREA"], r["FREQ"]), []).append((r["TIME_PERIOD"], float(v)))
    return {k: sorted(v) for k, v in out.items()}


def bis_gated(flow: str, key: str, gate: pd.Period, start: str, what: str,
              rule: str) -> tuple[bytes, S.LedgerEntry]:
    url = (f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}"
           f"?format=csv&startPeriod={start}&endPeriod={gate}")
    b, sha, got = S.cached_get(url)
    e = S.LedgerEntry(
        id=f"bis-{flow.lower().replace('_', '')}-{key.lower().replace('.', '')}-to-{gate}",
        url=url, sha256=sha, nbytes=len(b), retrieved_at=got,
        available_by=f"reference months through {gate} ({rule})", kind="present-day-gated",
        note=(f"{what}: present-day BIS history requested with endPeriod={gate}, so the "
              f"retained bytes stop at {gate}. No historical vintage of this series is "
              "retrievable; later revisions to these reference months are not removed."))
    return b, e


def fred_gated(series_id: str, gate: pd.Period, what: str, rule: str) -> tuple[bytes, S.LedgerEntry]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&coed={gate}-01"
    b, sha, got = S.cached_get(url)
    e = S.LedgerEntry(
        id=f"fred-{series_id.lower()}-to-{gate}", url=url, sha256=sha, nbytes=len(b),
        retrieved_at=got, available_by=f"reference months through {gate} ({rule})",
        kind="present-day-gated",
        note=(f"{what}: present-day FRED (OECD Main Economic Indicators) monthly history "
              f"requested with coed={gate}-01, so the retained bytes stop at {gate}. A "
              "completed month's average market yield was observable when the month ended."),
        proof_url=f"https://fred.stlouisfed.org/series/{series_id}")
    return b, e


def _yoy_monthly(idx: pd.Series) -> pd.Series:
    if idx.empty:
        return idx
    full = pd.period_range(idx.index.min(), idx.index.max(), freq="M")
    idx = idx.reindex(full)
    return (100.0 * (idx / idx.shift(12) - 1.0)).dropna()


def _yoy_quarterly(rows: list[tuple[str, float]]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    q = pd.Series({pd.Period(p, freq="Q"): v for p, v in rows}, dtype=float).sort_index()
    q = q.reindex(pd.period_range(q.index.min(), q.index.max(), freq="Q"))
    y = (100.0 * (q / q.shift(4) - 1.0)).dropna()
    return _quarterly_to_monthly([(str(p), float(v)) for p, v in y.items()])


def _content_check(ed: str, rows: list[tuple[str, float]]) -> dict | None:
    chk = register().get(ed, {}).get("content_check")
    if not chk:
        return None
    s = _monthly(rows)
    m = pd.Period(chk["month"], freq="M")
    got = {"level": float(s.loc[m]), "mom": float(s.loc[m] - s.loc[m - 1]),
           "yoy": float(s.loc[m] - s.loc[m - 12])}
    res = {"edition": ed, "area": chk["area"], "month": chk["month"], "ok": True, "items": []}
    for k in ("level", "mom", "yoy"):
        rep = chk.get(f"reported_{k}")
        if rep is None:
            continue
        ok = abs(round(got[k], 1) - rep) <= chk["tol"] + 1e-9
        res["items"].append({"what": k, "reported": rep, "edition": round(got[k], 2), "ok": ok})
        res["ok"] &= ok
    if not res["ok"]:
        raise RuntimeError(f"edition {ed} CLI does not match the dated public report: {res}")
    return res


# ------------------------------------------------------------------- build

def build(ed: Edition, verbose: bool = True) -> tuple[dict[str, pd.DataFrame], Evidence]:
    if not is_realtime(ed):
        raise ValueError(f"{ed.iso} is not a real-time-era edition")
    log = print if verbose else (lambda *a, **k: None)
    ev = Evidence(edition=ed.iso, cutoff_utc=ed.cutoff_iso, anchor=str(ed.anchor), era="realtime")
    led = ed.last_eligible_day
    panels: dict[str, dict[str, pd.Series]] = {k: {} for k in
                                               ("policy", "cpi", "reer", "cli", "y10")}

    def record(family: str, cc: str, s: pd.Series):
        s = s.dropna()
        ev.obs.setdefault(cc, {})[family] = str(s.index.max()) if len(s) else None
        g = _gaps(s)
        if g:
            ev.gaps[f"{family}/{cc}"] = g

    def fresh(family: str, cc: str, s: pd.Series, what: str) -> bool:
        lag = (ed.anchor - s.index.max()).n
        if lag > STALE_MONTHS:
            ev.notes.append(f"{family}/{cc}: {what} ends {s.index.max()}, {lag} months before "
                            f"the {ed.anchor} anchor (more than {STALE_MONTHS}); not used.")
            return False
        return True

    # ---- growth: real-time CLI ------------------------------------------
    cli_ed, cli_pub, cli_basis = cli_edition(ed)
    log(f"growth: OECD real-time CLI, {edition_label(cli_ed)} edition (public by {cli_pub})")
    b, e = oecd_rt("LI_AA", cli_ed, cli_pub, cli_basis)
    ev.add(e)
    cli = parse_rt(b)
    chk = _content_check(cli_ed, cli.get(("OECD", "M"), []))
    ev.rt["cli"] = {"edition": cli_ed, "label": edition_label(cli_ed), "public_by": cli_pub,
                      "basis": cli_basis, "content_check": chk,
                      "evidence": [x for x in register().get(cli_ed, {}).get("evidence", [])
                                   if date.fromisoformat(x["date"]) <= led]}
    for cc, area in RT_AREA.items():
        s = _cap(_monthly(cli.get((area, "M"), [])), ed)
        if not len(s) or not fresh("cli", cc, s, f"the {edition_label(cli_ed)} CLI edition"):
            continue
        panels["cli"][cc] = s
        ev.growth_def[cc] = (f"OECD composite leading indicator, amplitude adjusted, as published "
                             f"in the {edition_label(cli_ed)} edition (real-time database, "
                             + (f"euro-area aggregate as published, database code {area}" if cc == "XM"
                              else f"LI_AA {area}") + ")")
        record("cli", cc, s)

    ev.rt["cli"]["ref"] = max(ev.obs[cc]["cli"] for cc in panels["cli"]) if panels["cli"] else ""

    # ---- inflation --------------------------------------------------------
    cpi_ed, cpi_pub, cpi_basis = cpi_edition(ed)
    log(f"inflation: OECD real-time CPI, {edition_label(cpi_ed)} edition; US ALFRED "
        f"{ed.alfred_vintage}")
    b, cpi_e = oecd_rt("CP", cpi_ed, cpi_pub, cpi_basis)
    cp = parse_rt(b)
    ev.rt["cpi"] = {"edition": cpi_ed, "label": edition_label(cpi_ed), "public_by": cpi_pub,
                      "basis": cpi_basis}
    ab, ae = S.alfred("CPIAUCNS", ed.alfred_vintage.isoformat())
    us_yoy = _yoy_monthly(_monthly([(p[:7], v) for p, v in S.parse_alfred_csv(ab)]))
    lag1 = gate_lag1(ed)
    used_cpi_rt = False
    for cc in COUNTRIES:
        cands = []
        if cc == "US":
            cands.append(("alfred", us_yoy, ae, "BLS CPI-U all items NSA (CPIAUCNS), ALFRED "
                          f"{ed.alfred_vintage.isoformat()} vintage, calendar-month y/y"))
        if cc in RT_AREA:
            area = RT_AREA[cc]
            if cc in QUARTERLY_CPI:
                s = _yoy_quarterly(cp.get((area, "Q"), []))
                lbl = (f"OECD real-time CPI index {area} (quarterly), {edition_label(cpi_ed)} "
                       "edition, y/y within the vintage")
            else:
                idx = _monthly(cp.get((area, "M"), []))
                if cc in YOY_INDEX:
                    s = (idx - 100.0).dropna()
                    lbl = (f"OECD real-time CPI {area}, {edition_label(cpi_ed)} edition (stored as "
                           "same month of previous year = 100; y/y = value − 100)")
                else:
                    s = _yoy_monthly(idx)
                    lbl = (("OECD real-time CPI index, euro-area aggregate as published "
                            f"(database code {area})" if cc == "XM"
                            else f"OECD real-time CPI index {area}") + ", "
                           f"{edition_label(cpi_ed)} edition, y/y within the vintage")
            cands.append(("oecd_rt", s, cpi_e, lbl))
        if cc in NO_RT:
            bb, be = bis_gated("WS_LONG_CPI", f"M.{cc}.771", lag1, "1985-01",
                               f"BIS WS_LONG_CPI M.{cc}.771 (CPI y/y)",
                               "one-full-month publication-lag gate")
            cands.append(("bis_gated", _monthly(S.parse_bis_csv(bb)), be,
                          f"BIS WS_LONG_CPI M.{cc}.771, present-day history gated at {lag1}"))
        considered, best = [], None
        for k, s, e, lbl in cands:
            s = _cap(s.dropna(), ed)
            if s.empty:
                continue
            considered.append({"candidate": lbl, "last": str(s.index.max()),
                               "last_value": round(float(s.iloc[-1]), 3)})
            if best is None or s.index.max() > best[1].index.max():
                best = (k, s, e, lbl)
        if best is None:
            continue
        k, s, e, lbl = best
        if not fresh("cpi", cc, s, lbl):
            continue
        ev.add(e)
        used_cpi_rt |= k == "oecd_rt"
        panels["cpi"][cc] = s
        ev.cpi_choice[cc] = {"chosen": lbl, "ledger": e.id, "last": str(s.index.max()),
                             "last_value": round(float(s.iloc[-1]), 3), "considered": considered,
                             "supplements": [], "mean_abs_diff_vs_bis_60m": None,
                             "quarterly": cc in QUARTERLY_CPI, "kind": k}
        record("cpi", cc, s)
    if used_cpi_rt:
        ev.add(cpi_e)

    # ---- REER + 10y ---------------------------------------------------------
    log(f"REER: BIS broad, gated at {lag1}; 10y yields: completed months to {ed.anchor}")
    for cc, c in COUNTRIES.items():
        bb, be = bis_gated("WS_EER", f"M.R.B.{cc}", lag1, "1994-01",
                           f"BIS broad real effective exchange rate M.R.B.{cc}",
                           "one-full-month publication-lag gate")
        s = _cap(_monthly(S.parse_bis_csv(bb)), ed)
        if len(s):
            ev.add(be)
            panels["reer"][cc] = s
            record("reer", cc, s)
        if c.fred_10y:
            fb, fe = fred_gated(c.fred_10y, ed.anchor, f"10-year government bond yield "
                                f"({c.fred_10y})", "completed months")
            s = _cap(_monthly([(p[:7], v) for p, v in S.parse_alfred_csv(fb)]), ed)
            if len(s):
                ev.add(fe)
                panels["y10"][cc] = s
                record("y10", cc, s)

    # ---- policy ---------------------------------------------------------------
    log(f"policy: BIS daily decision history to {led}, monthly to {ed.anchor}")
    for cc in COUNTRIES:
        mb, me = bis_gated("WS_CBPOL", f"M.{cc}", ed.anchor, "1985-01",
                           f"BIS central bank policy rate M.{cc} (end of period)",
                           "completed months")
        m = _cap(_monthly(S.parse_bis_csv(mb)), ed)
        db, de = S.bis_daily_current(cc, DAILY_START, led.isoformat())
        d = _daily(S.parse_bis_csv(db))
        d = d[d.index <= pd.Timestamp(led)].round(3)   # 7.2498 -> 7.25 (BIS daily blips)
        if not len(m) and not len(d):
            continue
        ev.add(me)
        ev.add(de)
        # month-ends inside the daily window must agree with the monthly rows
        bad = [str(q) for q in m.index if q.start_time >= pd.Timestamp(DAILY_START)
               and (v := _value_on(d, q.end_time.date())) is not None
               and abs(v - float(m.loc[q])) > LEVEL_EPS]
        if bad:
            ev.notes.append(f"policy/{cc}: BIS monthly differs from the daily month-end in "
                            f"{', '.join(bad)}; monthly rows retained.")
        last_m = m.index.max() if len(m) else None
        if last_m is None or last_m < ed.anchor:
            start = (last_m + 1) if last_m is not None else ed.anchor
            for p in pd.period_range(start, ed.anchor, freq="M"):
                v = _value_on(d, p.end_time.date())
                if v is not None:
                    m.loc[p] = v
                    ev.extensions.append({"cc": cc, "month": str(p), "value": v,
                                          "source": "BIS daily month-end (monthly row absent)"})
            m = m.sort_index()
        cur = _value_on(d, led)
        if cur is None:
            cur = float(m.iloc[-1])
        mkt = MARKET_RATE_BEFORE.get(cc)
        dd = d[d.index >= pd.Timestamp(mkt)] if mkt else d
        chg = dd[(dd - cur).abs() > LEVEL_EPS]
        if mkt and led < mkt:
            since = "daily market rate"
        elif len(chg):
            since = dd[dd.index > chg.index.max()].index.min().date().isoformat()
        elif mkt:
            since = f"{mkt.isoformat()} (first day of the flat target level)"
        else:
            since = f"on or before {dd.index.min().date().isoformat()}" if len(dd) else "n/a"
        # recent level changes of at least DECISION_MIN_PP
        lvl = None
        for t, v in dd.items():
            if lvl is None:
                lvl = v
                continue
            if abs(v - lvl) >= DECISION_MIN_PP - 1e-9:
                if (pd.Timestamp(led) - t).days <= DECISION_WINDOW_DAYS:
                    ev.decisions.append({"cc": cc, "effective": t.date().isoformat(),
                                         "from": lvl, "to": v})
                lvl = v
        panels["policy"][cc] = m
        record("policy", cc, m)
        ev.policy[cc] = PolicySnap(
            cc=cc, monthly_last=str(m.index.max()), monthly_value=float(m.iloc[-1]),
            current=float(cur), effective_since=since, archive_daily_end=led.isoformat(),
            source=me.id)

    out = {}
    for k, dct in panels.items():
        dct = {cc: _ts(s) for cc, s in dct.items() if len(s)}
        out[k] = pd.DataFrame(dct).sort_index() if dct else pd.DataFrame()
    return out, ev
