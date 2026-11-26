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
# The database files the euro-area aggregate under EA18 in every edition through
# January 2015; from the February 2015 edition (after Lithuania joined on
# 1 January 2015) only EA19 is carried. The aggregate is used as published.
EA19_FROM = "201502"


def rt_areas(edition: str) -> dict[str, str]:
    """Database area code per economy for one real-time edition."""
    if edition >= EA19_FROM:
        return {**RT_AREA, "XM": "EA19"}
    return RT_AREA
# China's CP is stored as "same month of the previous year = 100" in the
# editions through the one given; later editions (from 200911, the first to
# carry China again) hold a fixed-base index: e.g. 2009-07 111.08 against
# 2008-07 113.11, i.e. -1.8% y/y, the NBS figure, not +11.1%.
YOY_INDEX = {"CN": "200812"}
# A fixed-base China index is derived by the OECD from NBS rates, and several
# vintages' 12-month ratios deviate from the published y/y by up to ~0.9pp
# (e.g. 2009-10 in the February-June 2010 editions). For such editions the
# published y/y behind the one-full-month gate competes; the fresher series is
# used, the vintage on a tie.
BIS_COMPETES_FIXED_BASE = {"CN"}


def stored_as_yoy(cc: str, edition: str) -> bool:
    return cc in YOY_INDEX and edition <= YOY_INDEX[cc]
QUARTERLY_CPI = {"AU", "NZ"}
STALE_MONTHS = 9         # an input whose latest observation is older is not used
CPI_FALLBACK_EDITIONS = 3  # look back this many editions for a series missing from one
DAILY_START = "2006-01-01"
DECISION_WINDOW_DAYS = 190
DECISION_MIN_PP = 0.10   # smaller moves are rounding/data noise, not decisions
LEVEL_EPS = 0.005        # BIS daily levels within this are the same rate (e.g. 7.2498 vs 7.25)
# BIS series that are daily market rates before the given date (Mexico: the
# overnight interbank rate became Banxico's operational target from that day;
# before it the daily level drifts with the market).
MARKET_RATE_BEFORE = {"MX": date(2008, 1, 21)}
# Instrument switches inside a BIS daily series: the level change on the switch
# day is not a policy decision. For editions on or after the switch, earlier
# history (daily and month-ends before the switch) is spliced onto the new
# instrument by the switch-day difference, so policy changes and holds are
# measured on one instrument; the current level is the new instrument's own.
INSTRUMENT_SWITCH = {
    "TR": {"date": date(2010, 5, 20), "old": "overnight borrowing rate",
           "new": "one-week repo rate",
           "source": ("CBRT Monetary Policy Committee decision No. 2010-16, 18 May 2010: "
                      "overnight rates kept unchanged; as a 'technical rate adjustment', "
                      "'the one week repo rate, which becomes the new policy rate, is set at 7 "
                      "percent—50 basis points above the overnight borrowing rates'")},
    "ID": {"date": date(2016, 8, 19), "old": "BI Rate",
           "new": "BI 7-Day (Reverse) Repo Rate",
           "source": "Bank Indonesia press release No. 18/67/DKom, 19 Aug 2016: the Board of Governors "
                      "(18–19 Aug 2016) held the BI 7-day Reverse Repo Rate at 5.25% and, as announced on "
                      "15 Apr 2016, 'terhitung mulai hari ini Bank Indonesia menggunakan BI 7-day RR Rate "
                      "sebagai suku bunga kebijakan menggantikan BI Rate' (from today the BI 7-day RR "
                      "Rate replaces the BI Rate as the policy rate); the BI Rate had stood at 6.50%"},
}
# Levels the BIS daily history leaves blank although they were announced and in
# force. Japan's series is empty from 4 Apr 2013 (QQE made the monetary base the
# main operating target) until the short-term policy interest rate of 21 Sep 2016.
# From 16 Feb 2016 the BoJ applied -0.1% to Policy-Rate Balances (announced
# 29 Jan 2016); that rate is used for the blank days from its effective date, so
# the easing is dated when it took effect. Only days without a BIS observation are
# filled; each bridge cites its announcement (data/retro/announcement_sources.json).
DAILY_BRIDGE = {
    "JP": [{"effective": date(2016, 2, 16), "until": date(2016, 9, 20), "value": -0.1,
            "announced": "2016-01-29", "what": "rate applied to Policy-Rate Balances"}],
}
# Editions of the revisions database that carry no CLI (LI_AA) at all: the July
# and August 2016 editions hold CP and the other MEI measures but no leading
# indicator (the query returns no records). They are never eligible as growth
# input; the newest earlier edition with a CLI is used instead. (The OECD suspended
# CLI publication over the summer of 2016 and on 8 Sep 2016 "released three months'
# worth of data" - Simon Ward, Money Moves Markets, 8 Sep 2016. That source is
# dated after the affected editions, so it is cited here, not on their pages.)
NO_CLI_EDITIONS = {"201607", "201608"}
ERA_LAST_DAY = date(2018, 12, 31)          # editions on or before use this builder
# Operational policy facts that the BIS series does not show (e.g. Turkiye in 2017: the
# CBRT kept the one-week repo rate at 8% but funded the market at the late liquidity
# window rate). Disclosed on the page with their sources, never model inputs; an item is
# shown only in editions whose last eligible day is on or after its source date.
POLICY_CONTEXT_FILE = OUT_ROOT / "policy_context.json"


def policy_context(ed: Edition) -> list[dict]:
    if not POLICY_CONTEXT_FILE.exists():
        return []
    reg = json.loads(POLICY_CONTEXT_FILE.read_text())
    return [{"cc": cc, **x} for cc, xs in reg.items() if not cc.startswith("_")
            for x in xs if date.fromisoformat(x["date"]) <= ed.last_eligible_day]

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


def _with_cli(e: str) -> str:
    """``e``, or the newest earlier edition that carries a CLI at all."""
    p = pd.Period(f"{e[:4]}-{e[4:]}", freq="M")
    while f"{p.year}{p.month:02d}" in NO_CLI_EDITIONS:
        p -= 1
    return f"{p.year}{p.month:02d}"


def cli_edition(ed: Edition) -> tuple[str, str, str]:
    """(edition, public-by date, basis) for the growth input: the newest edition
    either evidenced public before the cutoff in the register, or whose edition
    month has ended (editions without a CLI are skipped)."""
    reg = register()
    me = _with_cli(_month_end_edition(ed))
    cands = {me: (_month_end(me).isoformat(), "edition month end (conservative rule)")}
    for k, v in reg.items():
        if date.fromisoformat(v["cli_public_by"]) <= ed.last_eligible_day:
            if k not in cands or v["cli_public_by"] < cands[k][0]:
                cands[k] = (v["cli_public_by"], v["basis"])
    k = max(cands)
    return k, cands[k][0], cands[k][1]


def eligible_cli(ed: Edition, e: str) -> tuple[str, str] | None:
    """(public-by, basis) if CLI edition ``e`` was eligible for ``ed``, else None."""
    led = ed.last_eligible_day
    if e in NO_CLI_EDITIONS:
        return None
    v = register().get(e)
    if v and date.fromisoformat(v["cli_public_by"]) <= led:
        return v["cli_public_by"], v["basis"]
    if _month_end(e) <= led:
        return _month_end(e).isoformat(), "edition month end (conservative rule)"
    return None


def _withheld_fallback(ed: Edition, cli_ed: str, area: str, depth: int = 3):
    """Series for an area withheld from ``cli_ed``'s release: the newest earlier
    eligible edition carrying it, capped at that release's reference month when
    it was admitted by a press report. Returns (edition, rows, ledger entry)."""
    p = pd.Period(f"{cli_ed[:4]}-{cli_ed[4:]}", freq="M")
    for k in range(1, depth + 1):
        q = p - k
        e = f"{q.year}{q.month:02d}"
        el = eligible_cli(ed, e)
        if el is None:
            continue
        b, entry = oecd_rt("LI_AA", e, el[0], el[1])
        a = rt_areas(e)["XM"] if area in ("EA18", "EA19") else area
        rows = parse_rt(b).get((a, "M"), [])
        rm = register().get(e, {}).get("cli_ref_month")
        if rm and el[1] != "edition month end (conservative rule)":
            rows = [(t, v) for t, v in rows if pd.Period(t, freq="M") <= pd.Period(rm, freq="M")]
        if rows:
            return e, rows, entry
    return cli_ed, [], None


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
    extra = set()
    if measure == "LI_AA":       # an edition whose content check uses another area
        chk = register().get(edition, {}).get("content_check") or {}
        extra = {chk["area"]} if chk.get("area") else set()
    areas = "+".join(sorted(set(rt_areas(edition).values()) | {"OECD"} | extra))
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


def _rt_cpi(cc: str, cp: dict, edition: str) -> tuple[pd.Series, str]:
    """CPI y/y for one economy from one real-time CP edition (empty if absent)."""
    area = rt_areas(edition)[cc]
    if cc in QUARTERLY_CPI:
        return (_yoy_quarterly(cp.get((area, "Q"), [])),
                f"OECD real-time CPI index {area} (quarterly), {edition_label(edition)} "
                "edition, y/y within the vintage")
    idx = _monthly(cp.get((area, "M"), []))
    if stored_as_yoy(cc, edition):
        return ((idx - 100.0).dropna(),
                f"OECD real-time CPI {area}, {edition_label(edition)} edition (stored as "
                "same month of previous year = 100; y/y = value − 100)")
    return (_yoy_monthly(idx),
            ("OECD real-time CPI index, euro-area aggregate as published "
             f"(database code {area})" if cc == "XM" else
             f"OECD real-time CPI index {area} (fixed base)" if cc in YOY_INDEX else
             f"OECD real-time CPI index {area}")
            + f", {edition_label(edition)} edition, y/y within the vintage")


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
    skipped = sorted(e for e in NO_CLI_EDITIONS if cli_ed < e <= _month_end_edition(ed))
    if skipped:
        ev.notes.append(
            "cli: the " + " and ".join(edition_label(e) for e in skipped)
            + (" editions" if len(skipped) > 1 else " edition")
            + " of the real-time database " + ("carry" if len(skipped) > 1 else "carries")
            + " no composite leading indicator (no records for any area); the newest edition "
            f"with one ({edition_label(cli_ed)}) is used.")
    b, e = oecd_rt("LI_AA", cli_ed, cli_pub, cli_basis)
    ev.add(e)
    cli = parse_rt(b)
    chk_area = (register().get(cli_ed, {}).get("content_check") or {}).get("area", "OECD")
    chk = _content_check(cli_ed, cli.get((chk_area, "M"), []))
    ev.rt["cli"] = {"edition": cli_ed, "label": edition_label(cli_ed), "public_by": cli_pub,
                      "basis": cli_basis, "content_check": chk,
                      "evidence": [x for x in register().get(cli_ed, {}).get("evidence", [])
                                   if date.fromisoformat(x["date"]) <= led]}
    mn = register().get(cli_ed, {}).get("method_note")
    if mn and date.fromisoformat(mn["date"]) <= led:
        ev.rt["cli"]["method_note"] = mn
    # An edition admitted by a dated press report is shown public only up to that
    # release's reference month; a country row the database edition carries beyond
    # it (e.g. Jan-2010 values in the February 2010 edition) is not used until the
    # edition month has ended.
    ref_cap = None
    if cli_basis != "edition month end (conservative rule)":
        rm = register().get(cli_ed, {}).get("cli_ref_month")
        ref_cap = pd.Period(rm, freq="M") if rm else None
    # An area the release itself withheld (e.g. Japan in April 2011, after the
    # earthquake) is not shown public by the press report even though the database
    # edition carries it: until the edition month has ended, that area's series
    # comes from the newest earlier edition that was itself eligible.
    withheld = (register().get(cli_ed, {}).get("withheld", {})
                if _month_end(cli_ed) > led else {})
    if cli_ed >= EA19_FROM:
        ev.notes.append(
            f"cli/XM, cpi/XM: from the {edition_label(EA19_FROM)} edition the real-time database "
            "carries the euro-area aggregate as EA19 (Lithuania joined the euro area on "
            "1 January 2015) instead of EA18; the aggregate is used as published.")
    for cc, area in rt_areas(cli_ed).items():
        src_ed = cli_ed
        if area in withheld:
            src_ed, rows, e_prev = _withheld_fallback(ed, cli_ed, area)
            s = _cap(_monthly(rows), ed)
            if e_prev is not None:
                ev.add(e_prev)
            ev.notes.append(
                f"cli/{cc}: withheld from the {edition_label(cli_ed)} release "
                f"({withheld[area]}); the newest earlier eligible edition "
                f"({edition_label(src_ed)}, through {s.index.max() if len(s) else 'n/a'}) is used.")
            if not len(s) or not fresh("cli", cc, s, f"the {edition_label(src_ed)} CLI edition"):
                continue
            panels["cli"][cc] = s
            ev.growth_def[cc] = (f"OECD composite leading indicator, amplitude adjusted, as "
                                 f"published in the {edition_label(src_ed)} edition (real-time "
                                 f"database, LI_AA {area}; withheld from the "
                                 f"{edition_label(cli_ed)} release)")
            record("cli", cc, s)
            continue
        s = _cap(_monthly(cli.get((area, "M"), [])), ed)
        if ref_cap is not None and len(s) and s.index.max() > ref_cap:
            ev.notes.append(
                f"cli/{cc}: the {edition_label(cli_ed)} edition carries {s.index.max()}, beyond "
                f"the release's reference month {ref_cap}; later months are not used (not "
                f"shown public by {cli_pub}).")
            s = s[s.index <= ref_cap]
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
        missing_note = None
        if cc in RT_AREA:
            s, lbl = _rt_cpi(cc, cp, cpi_ed)
            e_rt = cpi_e
            if s.empty:
                # absent from this edition: candidates are the newest earlier
                # (equally eligible) edition still carrying the series, and the
                # present-day BIS history behind the one-full-month gate; the
                # fresher one is used (as for any candidate set)
                prev = pd.Period(f"{cpi_ed[:4]}-{cpi_ed[4:]}", freq="M")
                found = None
                for k in range(1, CPI_FALLBACK_EDITIONS + 1):
                    pe = f"{(prev - k).year}{(prev - k).month:02d}"
                    pb, pe_e = oecd_rt("CP", pe, _month_end(pe).isoformat(),
                                       "edition month end (conservative rule)")
                    s, lbl = _rt_cpi(cc, parse_rt(pb), pe)
                    if not s.empty:
                        e_rt, found = pe_e, pe
                        break
                bb, be = bis_gated("WS_LONG_CPI", f"M.{cc}.771", lag1, "1985-01",
                                   f"BIS WS_LONG_CPI M.{cc}.771 (CPI y/y)",
                                   "one-full-month publication-lag gate")
                cands.append(("bis_gated", _monthly(S.parse_bis_csv(bb)), be,
                              f"BIS WS_LONG_CPI M.{cc}.771, present-day history gated at {lag1}"))
                missing_note = (cpi_ed, found)
            cands.append(("oecd_rt", s, e_rt, lbl))
            if (cc in BIS_COMPETES_FIXED_BASE and missing_note is None and not s.empty
                    and not stored_as_yoy(cc, cpi_ed)):
                bb, be = bis_gated("WS_LONG_CPI", f"M.{cc}.771", lag1, "1985-01",
                                   f"BIS WS_LONG_CPI M.{cc}.771 (CPI y/y)",
                                   "one-full-month publication-lag gate")
                cands.append(("bis_gated", _monthly(S.parse_bis_csv(bb)), be,
                              f"BIS WS_LONG_CPI M.{cc}.771, present-day history gated at {lag1}"))
                missing_note = ("fixed-base", None)
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
        if missing_note and missing_note[0] == "fixed-base":
            ev.notes.append(
                f"cpi/{cc}: the {edition_label(cpi_ed)} CPI edition stores a fixed-base index "
                "(y/y = 12-month ratio inside the vintage); the published y/y behind the "
                "one-full-month publication gate competes, and the "
                + ("vintage" if k == "oecd_rt" else f"published y/y (latest {s.index.max()})")
                + " is used as the fresher series.")
        elif missing_note:
            me, found = missing_note
            ev.notes.append(
                f"cpi/{cc}: absent from the {edition_label(me)} CPI edition; "
                + (f"the newest earlier edition carrying it ({edition_label(found)}) is used."
                   if k == "oecd_rt" else
                   "the present-day BIS history behind the one-full-month publication gate "
                   f"(latest {s.index.max()}) is fresher than "
                   + (f"the newest earlier edition carrying it ({edition_label(found)})"
                      if found else f"any of the previous {CPI_FALLBACK_EDITIONS} editions")
                   + " and is used."))
        if not fresh("cpi", cc, s, lbl):
            continue
        ev.add(e)
        used_cpi_rt |= k == "oecd_rt" and e is cpi_e
        panels["cpi"][cc] = s
        ev.cpi_choice[cc] = {"chosen": lbl, "ledger": e.id, "last": str(s.index.max()),
                             "last_value": round(float(s.iloc[-1]), 3), "considered": considered,
                             "supplements": [], "mean_abs_diff_vs_bis_60m": None,
                             "quarterly": cc in QUARTERLY_CPI, "kind": k,
                             "reason": ("fixed-base" if missing_note and
                                        missing_note[0] == "fixed-base" else
                                        "absent" if missing_note else "")}
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
        bridged: set = set()
        for br in DAILY_BRIDGE.get(cc, []):
            if led < br["effective"]:
                continue
            days = pd.date_range(br["effective"], min(led, br["until"]), freq="D")
            fill = days.difference(d.index)
            if not len(fill):
                continue
            before = d[d.index < pd.Timestamp(br["effective"])]
            d = pd.concat([d, pd.Series(br["value"], index=fill, dtype=float)]).sort_index()
            bridged |= set(fill)
            ev.announcements.append({"cc": cc, "effective": br["effective"].isoformat(),
                                     "from": float(before.iloc[-1]) if len(before) else None,
                                     "to": br["value"], "source": "daily bridge"})
            resumes = pd.Timestamp(br["until"]) + pd.Timedelta(days=1)
            ev.notes.append(
                f"policy/{cc}: the BIS daily series is blank from "
                f"{(before.index.max() + pd.Timedelta(days=1)).date().isoformat()}"
                + (f" to {br['until'].isoformat()}" if led >= resumes.date() else "")
                + "; months without a BIS row carry the last BIS level as a proxy. From "
                f"{br['effective'].isoformat()} the {br['what']}, {br['value']:.2f}% (announced "
                f"{br['announced']}; source below the policy decisions), fills the blank days"
                + (f"; the BIS series resumes at the same level on {resumes.date().isoformat()}"
                   if led >= resumes.date() else "") + ".")
        sw = INSTRUMENT_SWITCH.get(cc)
        if sw and led >= sw["date"]:
            t = pd.Timestamp(sw["date"])
            pre, post = d[d.index < t], d[d.index >= t]
            if len(pre) and len(post):
                jump = round(float(post.iloc[0]) - float(pre.iloc[-1]), 3)
                d = d.copy()
                d[d.index < t] = d[d.index < t] + jump
                months = [q for q in m.index if q.end_time < t]
                m.loc[months] = m.loc[months] + jump
                ev.notes.append(
                    f"policy/{cc}: the {sw['new']} became the policy rate on "
                    f"{sw['date'].isoformat()} (the BIS series switches from the {sw['old']}, "
                    f"{float(pre.iloc[-1]):.2f}% → {float(post.iloc[0]):.2f}%). The switch is not a "
                    f"rate change ({sw['source']}): earlier history is spliced by {jump:+.2f}pp so "
                    "that policy changes are measured on the new instrument.")
        # month-ends inside the daily window must agree with the monthly rows
        bad = [str(q) for q in m.index if q.start_time >= pd.Timestamp(DAILY_START)
               and (v := _value_on(d, q.end_time.date())) is not None
               and abs(v - float(m.loc[q])) > LEVEL_EPS]
        if bad:
            ev.notes.append(f"policy/{cc}: BIS monthly differs from the daily month-end in "
                            f"{', '.join(bad)}; monthly rows retained.")
        def _ext_source(p: pd.Period) -> str:
            last_day = d[d.index <= p.end_time].index.max()
            return ("daily bridge month-end (BIS daily blank; announced level, see the data "
                    "notes)" if last_day in bridged else
                    "BIS daily month-end (monthly row absent)")

        last_m = m.index.max() if len(m) else None
        if last_m is not None:
            # interior months without a BIS monthly row (e.g. Japan from May 2013 once
            # the series resumes) take the daily month-end, as trailing months do
            inner = pd.period_range(max(m.index.min(), pd.Period(DAILY_START, freq="M")),
                                    last_m, freq="M").difference(m.index)
            for p in inner:
                v = _value_on(d, p.end_time.date())
                if v is not None:
                    m.loc[p] = v
                    ev.extensions.append({"cc": cc, "month": str(p), "value": v,
                                          "source": _ext_source(p)})
            m = m.sort_index()
        if last_m is None or last_m < ed.anchor:
            start = (last_m + 1) if last_m is not None else ed.anchor
            for p in pd.period_range(start, ed.anchor, freq="M"):
                v = _value_on(d, p.end_time.date())
                if v is not None:
                    m.loc[p] = v
                    ev.extensions.append({"cc": cc, "month": str(p), "value": v,
                                          "source": _ext_source(p)})
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
        # a bridged level starts from the last BIS level before the blank days (Japan:
        # 0.05%, below the decision threshold of the October 2010 move from 0.1%)
        for a in ev.announcements:
            if a["cc"] == cc and a.get("source") == "daily bridge" and a["from"] is not None:
                for x in ev.decisions:
                    if x["cc"] == cc and x["effective"] == a["effective"]:
                        x["from"] = a["from"]
        panels["policy"][cc] = m
        record("policy", cc, m)
        ev.policy[cc] = PolicySnap(
            cc=cc, monthly_last=str(m.index.max()), monthly_value=float(m.iloc[-1]),
            current=float(cur), effective_since=since, archive_daily_end=led.isoformat(),
            source=me.id)

    pc = policy_context(ed)
    if pc:
        ev.rt["policy_context"] = pc

    out = {}
    for k, dct in panels.items():
        dct = {cc: _ts(s) for cc, s in dct.items() if len(s)}
        out[k] = pd.DataFrame(dct).sort_index() if dct else pd.DataFrame()
    return out, ev
