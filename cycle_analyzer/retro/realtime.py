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
# From the April 2023 edition (after Croatia joined on 1 January 2023) the CPI is carried
# only as EA20; the January-March 2023 editions still carry EA19.
EA20_FROM = "202304"


def rt_areas(edition: str) -> dict[str, str]:
    """Database area code per economy for one real-time edition."""
    if edition >= EA20_FROM:
        return {**RT_AREA, "XM": "EA20"}
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
# Definition mismatch: the revisions database's India CP series is the CPI for
# Industrial Workers, not the all-India Combined CPI that the RBI targets (4%
# since the MPC resolution of 6 Apr 2017). Over 2015-2019 the two y/y rates
# differ by 1.4pp on average and by up to 5.6pp (2019-08: 6.31% vs 3.38%), which
# would invert India's inflation gap. As in the archive-era builder ("India:
# Combined CPI only"), editions from the given date use the present-day BIS
# Combined CPI behind the one-full-month gate instead; the vintage index is shown
# as a considered candidate. Earlier real-time editions are left as published.
CPI_DEFINITION_BIS = {
    "IN": {"from": date(2019, 1, 1),
           "why": ("the real-time database's India series is the CPI for Industrial Workers, "
                   "while the RBI's 4% objective refers to the all-India Combined CPI")},
}


def bis_for_definition(cc: str, ed: Edition) -> bool:
    d = CPI_DEFINITION_BIS.get(cc)
    return d is not None and ed.date >= d["from"]


# Series the real-time database stops updating from a given edition. Japan's CP index
# (2015 = 100) runs to 2022-04 in the June 2022 edition but ends at 2021-06 in every
# edition from July 2022 on, which would freeze Japan's inflation at mid-2021 and drop it
# once stale. From that edition the present-day BIS history behind the one-full-month gate
# is used instead; the vintage index is shown as a considered candidate. Earlier editions
# are built exactly as published.
CPI_TRUNCATED_BIS = {
    "JP": {"from_edition": "202207", "ends": "2021-06",
           "earlier": "earlier 2022 editions ran to within two months of their edition month"},
    # Mexico's CP index runs to 2024-07 in the September 2024 edition and stops there in
    # every later 2024 edition (October: 2024-07 instead of 2024-08).
    "MX": {"from_edition": "202410", "ends": "2024-07",
           "earlier": "earlier editions ran to within two months of their edition month"},
}


def truncated_in_vintage(cc: str, edition: str) -> bool:
    t = CPI_TRUNCATED_BIS.get(cc)
    return t is not None and edition >= t["from_edition"]


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
    "CN": {"date": date(2019, 8, 20), "old": "one-year benchmark lending rate",
           "new": "one-year loan prime rate (LPR)",
           "not_change": ("The switch is an instrument change, not a decision on the benchmark rate, "
                          "which was retained at 4.35%; the first fixing of the new reference rate was "
                          "0.10pp lower, and that gap is not counted as a policy move"),
           "source": ("PBoC Announcement [2019] No. 15 (signed 16 Aug, posted 17 Aug 2019): from "
                      "20 Aug 2019 the National Interbank Funding Center publishes the loan prime rate "
                      "on the 20th of each month, and banks are to price new loans mainly off it "
                      "('各银行应在新发放的贷款中主要参考贷款市场报价利率定价'); the PBoC's Q&A of the "
                      "same day: 'the benchmark deposit and lending rates are retained'; first new "
                      "one-year LPR, 20 Aug 2019: 4.25%")},
    # The BIS euro-area series is the MRO fixed rate until 17 Sep 2024 and the deposit
    # facility rate (DFR) from 18 Sep 2024, the day the ECB's narrower 15bp MRO-DFR spread
    # took effect together with a 25bp DFR cut. The switch day therefore carries a decision:
    # the splice uses the DFR in force before it ("new_before"), not the switch-day jump.
    "XM": {"date": date(2024, 9, 18), "old": "main refinancing operations (MRO) fixed rate",
           "new": "deposit facility rate (DFR)", "new_before": 3.75,
           "decision": ("the switch day also carries the decision of 12 Sep 2024 to lower the "
                        "DFR by 25bp, from 3.75% to 3.50% (MRO 4.25% to 3.65%), effective "
                        "18 Sep 2024, which is kept as a policy move"),
           "source": ("ECB press release, 'ECB announces changes to the operational framework for "
                      "implementing monetary policy', 13 Mar 2024: the Governing Council 'will "
                      "continue to steer the monetary policy stance through the deposit facility "
                      "rate' and the spread between the MRO rate and the DFR is set at 15 basis "
                      "points from 18 Sep 2024; BIS series note: 'From 18 Sep 2024 onwards: "
                      "official central bank steering rate is the deposit facility rate'")},
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
# Single days on which the BIS daily history shows a level that reverts on the next
# business day without any announced decision (data errors, not policy moves). Such a
# day is read at the level of the days around it, once the reversal itself is before
# the cutoff; the page says so. Thailand: 0.50% on 6 May 2020 only, between 0.75% on
# 5 and 7 May; the MPC's next scheduled meeting after the special meeting of 20 Mar
# was 20 May 2020, when it cut the policy rate from 0.75% to 0.50%.
DAILY_ERRATA = {
    "TH": [{"day": date(2020, 5, 6), "bis": 0.5}],
}
# Days on which the BIS daily history already carries a new level although the decision
# was published only on a later day (a fixing due on a weekend is carried from the
# weekend). The days before publication are read at the previous level, so the change is
# dated when it was made public; the page says so. China: the one-year LPR of 3.65% is
# carried from Saturday 20 Aug 2022, but the National Interbank Funding Center published
# that fixing on Monday 22 Aug 2022 (Xinhua, 22 Aug 2022).
DAILY_DATE_FIX = {
    "CN": [{"bis_from": date(2022, 8, 20), "published": date(2022, 8, 22),
            "source": ("Xinhua via gov.cn, 'China cuts benchmark lending rate LPR', 22 Aug 2022: "
                       "'The one-year loan prime rate (LPR) came in at 3.65 percent on Aug 22, "
                       "down from 3.7 percent, according to the National Interbank Funding "
                       "Center'")},
           # the 20th of August 2023 was a Sunday; the BIS daily series carries 3.45% from it
           {"bis_from": date(2023, 8, 20), "published": date(2023, 8, 21),
            "source": ("Xinhua via People's Daily Online, 'China's one-year LPR drops Monday', "
                       "21 Aug 2023: the National Interbank Funding Center 'saw its one-year "
                       "rate come in at 3.45 percent on Monday', down from the previous reading "
                       "of 3.55 percent")}],
}
# Editions of the revisions database that carry no CLI (LI_AA) at all: the July
# and August 2016 editions hold CP and the other MEI measures but no leading
# indicator (the query returns no records). They are never eligible as growth
# input; the newest earlier edition with a CLI is used instead. (The OECD suspended
# CLI publication over the summer of 2016 and on 8 Sep 2016 "released three months'
# worth of data" - Simon Ward, Money Moves Markets, 8 Sep 2016. That source is
# dated after the affected editions, so it is cited here, not on their pages.)
# The March 2020 edition carries no CLI either: the OECD cancelled its March 2020
# release (CLI sub-components could not yet capture the spread of COVID-19) and the
# April 2020 release, on 8 Apr 2020, covered data through March 2020.
# The August 2024 edition carries no CLI either (the query returns no records for any
# area; the September 2024 edition runs through August 2024, and no ALFRED vintage of the
# OECD CLI series ever carried a July 2024 value as its newest observation).
NO_CLI_EDITIONS = {"201607", "201608", "202003", "202408"}
# Dated public notices of a cancelled release: shown, from their date, on pages that
# still rely on an older edition because of it.
NO_CLI_NOTICES = {
    "202003": {"date": date(2020, 3, 9), "month": "March 2020",
               "text": ("'The OECD has cancelled its scheduled monthly release of composite "
                        "leading indicators (CLI), because of the rapid spread of the coronavirus "
                        "outbreak. ... The OECD will release its next CLI survey in April' (Argus "
                        "Media, 'OECD cancels CLI release', 9 Mar 2020; OECD notice reposted by "
                        "Scoop, 10 Mar 2020: 'originally scheduled for 9 March 2020, has been "
                        "cancelled')")},
}
ERA_LAST_DAY = date(2024, 12, 31)          # editions on or before use this builder
# From the January 2023 edition the real-time database carries the CLI only for the 13
# economies the OECD still estimates (its release of 8 Dec 2022: "The CLIs will continue to
# be estimated for a reduced set of countries"); the euro area, Switzerland, Sweden, Norway,
# Poland, Hungary and Czechia drop out. In editions whose CLI edition is on or after this
# one, every economy without a CLI that has an OECD business confidence indicator takes it
# instead, exactly as the live pipeline and the archive-era builder do: BSCICP03 (amplitude
# adjusted, long-term average = 100, the CLI's own scale), as served in the newest DBnomics
# git commit of the OECD MEI_CLI dataset committed before the cutoff. Thailand has none.
# Earlier editions are built exactly as published.
BCI_FROM_CLI_EDITION = "202301"
BCI_AREAS = {"XM": "EA19", "CH": "CHE", "SE": "SWE", "NO": "NOR", "NZ": "NZL", "PL": "POL",
             "HU": "HUN", "CZ": "CZE", "CL": "CHL", "CO": "COL"}
MEI_CLI_PATH = "MEI_CLI/series.jsonl"
# DBnomics' OECD MEI_CLI dataset was last converted on 2024-01-13 (no commit until the
# archive's end), so in 2024 its business confidence histories stop at end-2023. For
# editions from BCI_GATED_FROM, a second candidate competes for each of the ten economies:
# the OECD business-tendency-survey composite confidence balance for manufacturing
# (DSD_STES@DF_BTS, percent balance), present-day history requested only through the
# one-full-month publication gate and normalized to 100 + its deviation from its own
# pre-cutoff average, exactly as the archive-era builder does (the model scales the
# deviation from 100 by its own trailing dispersion, so only the centring matters, and it
# uses nothing after the gate). The fresher candidate is used, the dated archive on a tie.
BCI_GATED_FROM = date(2024, 1, 1)
OECD_BTS = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_BTS,4.0"
BTS_AREAS = {"XM": "EA20", "CH": "CHE", "SE": "SWE", "NO": "NOR", "NZ": "NZL", "PL": "POL",
             "HU": "HUN", "CZ": "CZE", "CL": "CHL", "CO": "COL"}
BTS_QUARTERLY = {"NO", "NZ"}
# From the 2024 editions the 24 REER histories are ALFRED vintages of FRED's copies of the
# BIS broad real effective exchange rates (RB<cc>BIS), the Friday before the cutoff, as in
# the archive-era builder; the gated present-day BIS history remains the fallback.
REER_ALFRED_FROM = date(2024, 1, 1)
REDUCED_SET_SOURCE = {
    "url": "https://www.miragenews.com/composite-leading-indicators-oecd-december-2022-911632/",
    "label": ("Mirage News (OECD release reprinted), 'Composite Leading Indicators, OECD, "
              "December 2022', 8 Dec 2022: 'This is the final OECD Composite Leading Indicators "
              "news release in the current format'; 'The CLIs will continue to be estimated for "
              "a reduced set of countries (most G20 economies plus Spain)'"),
    "date": "2022-12-08"}
DBN_CHECK_TOL = 0.005    # the database prints two decimals; DBnomics serves five
# An area the chosen CLI edition does not carry at all (from the April 2020 release
# the OECD stopped computing some economies' CLIs, e.g. New Zealand, and left others
# out of single releases) takes the newest earlier eligible edition carrying it, at
# most CLI_ABSENT_DEPTH editions back, capped at that release's reference month;
# beyond that the economy has no growth input. Only for editions from the given date
# (earlier editions are built exactly as published).
CLI_ABSENT_FALLBACK_FROM = date(2020, 1, 1)
CLI_ABSENT_DEPTH = 3
# Operational policy facts that the BIS series does not show (e.g. Turkiye in 2017: the
# CBRT kept the one-week repo rate at 8% but funded the market at the late liquidity
# window rate). Disclosed on the page with their sources, never model inputs; an item is
# shown only in editions whose last eligible day is on or after its source date.
POLICY_CONTEXT_FILE = OUT_ROOT / "policy_context.json"


def policy_context(ed: Edition) -> list[dict]:
    if not POLICY_CONTEXT_FILE.exists():
        return []
    reg = json.loads(POLICY_CONTEXT_FILE.read_text())
    # "until": the last day the described arrangement applied (a later item records
    # what replaced it), or the last day a long-finished episode is shown (the 2019
    # auction suspensions); the item is not shown in editions after that day.
    led = ed.last_eligible_day
    return [{"cc": cc, **{k: v for k, v in x.items() if k != "until"}}
            for cc, xs in reg.items() if not cc.startswith("_")
            for x in xs if date.fromisoformat(x["date"]) <= led
            and ("until" not in x or led <= date.fromisoformat(x["until"]))]

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
        a = rt_areas(e)["XM"] if area in ("EA18", "EA19", "EA20") else area
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


def bts_gated(cc: str, gate: pd.Period) -> tuple[pd.Series, str, S.LedgerEntry]:
    """OECD composite business confidence (manufacturing, percent balance), present-day
    history requested only through the gate (quarterly surveys: the last quarter whose
    final month is within the gate). Returns the raw monthly series (quarters repeated
    across their months), the series key and the ledger entry."""
    q = cc in BTS_QUARTERLY
    area = BTS_AREAS[cc]
    key = f"{area}.{'Q' if q else 'M'}.BCICP.PB.C.Y._Z._Z.N"
    end = (f"{(gate + 1).asfreq('Q') - 1}".replace("Q", "-Q") if q else str(gate))
    url = f"{OECD_BTS}/{key}?endPeriod={end}&format=csvfile"
    b, sha, got = S.cached_get(url)
    rows = []
    for r in csv.DictReader(io.StringIO(b.decode("utf-8"))):
        v = r.get("OBS_VALUE")
        if v not in (None, "", "NaN"):
            rows.append((r["TIME_PERIOD"], float(v)))
    rows.sort()
    s = _quarterly_to_monthly(rows) if q else _monthly(rows)
    e = S.LedgerEntry(
        id=f"oecd-bts-{area.lower()}-to-{end.lower()}", url=url, sha256=sha, nbytes=len(b),
        retrieved_at=got,
        available_by=f"reference {'quarters' if q else 'months'} through {end} (one-full-month "
                     "publication-lag gate)", kind="present-day-gated",
        note=(f"OECD business tendency surveys, composite business confidence, manufacturing "
              f"({key}, percent balance): present-day OECD history requested with "
              f"endPeriod={end}, so the retained bytes stop there. No pre-cutoff vintage of "
              "this series is retrievable; survey balances are revised only through seasonal "
              "adjustment, which is not removed."),
        proof_url=("https://data-explorer.oecd.org/vis?df[ds]=dsDisseminateFinalDMZ&"
                   "df[id]=DSD_STES%40DF_BTS&df[ag]=OECD.SDD.STES"))
    return s, key, e


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
        item = {"what": k, "reported": rep, "edition": round(got[k], 2), "ok": ok}
        if k == "level" and chk.get("level_dp"):
            item["dp"] = chk["level_dp"]
        res["items"].append(item)
        res["ok"] &= ok
    # percent changes as a report states them (e.g. "+1.54%"), compared at the
    # report's own precision with one unit of tolerance: needed once levels are far
    # from 100 (Turkiye's April 2020 CLI at 79), where points and percent diverge
    pct = {"mom_pct": 100.0 * (float(s.loc[m]) / float(s.loc[m - 1]) - 1.0),
           "yoy_pct": 100.0 * (float(s.loc[m]) / float(s.loc[m - 12]) - 1.0)}
    for k, g in pct.items():
        rep = chk.get(f"reported_{k}")
        if rep is None:
            continue
        dp = len(repr(float(rep)).split(".")[1])
        ok = abs(round(g, dp) - rep) <= 10 ** -dp + 1e-9
        res["items"].append({"what": k, "reported": rep, "edition": round(g, 2), "ok": ok,
                             "dp": dp})
        res["ok"] &= ok
    if not res["ok"]:
        raise RuntimeError(f"edition {ed} CLI does not match the dated public report: {res}")
    return res


def _dbnomics_check(ed: str, rt_bytes: bytes) -> dict | None:
    """For a CLI edition admitted by a dated DBnomics git commit (register
    ``dbnomics_check``): the commit must carry, for every listed area, the same latest
    reference month as the edition and every overlapping value within rounding (the
    database prints two decimals, DBnomics serves five). Raises otherwise."""
    chk = register().get(ed, {}).get("dbnomics_check")
    if not chk:
        return None
    url = (f"{S.GITLAB}/{S.OECD_PROJECT}/repository/files/{S._q(chk['path'])}/raw"
           f"?ref={chk['commit']}")
    b, sha, _ = S.cached_get(url)
    ser = S.read_jsonl_series(b, {f"LOLITOAA.{a}.M" for a in chk["areas"]})
    rt = parse_rt(rt_bytes)
    n, mx, bad = 0, 0.0, []
    for a in chk["areas"]:
        rows = dict(rt.get((a, "M"), []))
        cs = dict(ser.get(f"LOLITOAA.{a}.M", []))
        if not rows or not cs or max(rows) != max(cs):
            bad.append(f"{a}: latest month {max(rows) if rows else None} in the edition, "
                       f"{max(cs) if cs else None} in the commit")
            continue
        for p, v in rows.items():
            if p in cs:
                n += 1
                d = abs(cs[p] - v)
                mx = max(mx, d)
                if d > DBN_CHECK_TOL + 1e-6:
                    bad.append(f"{a} {p}: {v} in the edition, {cs[p]} in the commit")
    if bad:
        raise RuntimeError(f"edition {ed} CLI does not match DBnomics commit {chk['commit'][:12]}: "
                           + "; ".join(bad[:5]))
    return {"edition": ed, "commit": chk["commit"], "committed": chk["committed"],
            "areas": len(chk["areas"]), "values": n, "max_abs_diff": round(mx, 4),
            "sha256": sha, "url": url, "ok": True}


ALFRED_CLI = "{area}LOLITOAASTSAM"        # FRED copies of the OECD amplitude-adjusted CLI


def alfred_served_vintage(b: bytes) -> date | None:
    """The vintage ALFRED actually served (its CSV header names it, e.g.
    ``USALOLITOAASTSAM_20240410``), which can be earlier than the requested date."""
    import re
    m = re.search(r"_(\d{8})", b.decode("utf-8").splitlines()[0])
    return date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:])) if m else None


def _alfred_check(ed: str, rt_bytes: bytes) -> dict | None:
    """For a CLI edition admitted by a dated ALFRED vintage (register ``alfred_check``):
    the vintage of every listed area's FRED copy of the OECD amplitude-adjusted CLI must
    carry the same latest reference month as the edition, every overlapping value within
    rounding (the database prints two decimals), and must have been served as the
    vintage of that very day. The day before, no listed area may yet carry that month
    (the vintage is the first to carry the edition). Raises otherwise."""
    chk = register().get(ed, {}).get("alfred_check")
    if not chk:
        return None
    v = date.fromisoformat(chk["vintage"])
    rt = parse_rt(rt_bytes)
    n, mx, bad, shas = 0, 0.0, [], []
    for a in chk["areas"]:
        sid = ALFRED_CLI.format(area=a)
        b, e = S.alfred(sid, v.isoformat())
        if alfred_served_vintage(b) != v:
            bad.append(f"{a}: ALFRED served vintage {alfred_served_vintage(b)}, not {v}")
        al = {p[:7]: x for p, x in S.parse_alfred_csv(b)}
        rows = dict(rt.get((a, "M"), []))
        if not rows or not al or max(rows) != max(al):
            bad.append(f"{a}: latest month {max(rows) if rows else None} in the edition, "
                       f"{max(al) if al else None} in the vintage")
            continue
        pb, _ = S.alfred(sid, (v - pd.Timedelta(days=1)).isoformat())
        prev = S.parse_alfred_csv(pb)
        if prev and prev[-1][0][:7] >= max(rows):
            bad.append(f"{a}: the vintage of the previous day already carries {prev[-1][0][:7]}")
        for p, x in rows.items():
            if p in al:
                n += 1
                d = abs(al[p] - x)
                mx = max(mx, d)
                if d > DBN_CHECK_TOL + 1e-6:
                    bad.append(f"{a} {p}: {x} in the edition, {al[p]} in the vintage")
        shas.append({"series": sid, "sha256": e.sha256, "url": e.url})
    if bad:
        raise RuntimeError(f"edition {ed} CLI does not match the ALFRED {v} vintage: "
                           + "; ".join(bad[:5]))
    return {"edition": ed, "vintage": v.isoformat(), "areas": len(chk["areas"]), "values": n,
            "max_abs_diff": round(mx, 4), "series": shas, "ok": True}


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
    for e_no, nt in sorted(NO_CLI_NOTICES.items()):
        if cli_ed < e_no and nt["date"] <= led and e_no not in skipped:
            ev.notes.append(
                f"cli: the OECD cancelled its {nt['month']} CLI release, {nt['text']}; the "
                f"{edition_label(cli_ed)} edition remains the newest public one.")
    b, e = oecd_rt("LI_AA", cli_ed, cli_pub, cli_basis)
    ev.add(e)
    cli = parse_rt(b)
    chk_area = (register().get(cli_ed, {}).get("content_check") or {}).get("area", "OECD")
    chk = _content_check(cli_ed, cli.get((chk_area, "M"), []))
    ev.rt["cli"] = {"edition": cli_ed, "label": edition_label(cli_ed), "public_by": cli_pub,
                      "basis": cli_basis, "content_check": chk,
                      "evidence": [x for x in register().get(cli_ed, {}).get("evidence", [])
                                   if date.fromisoformat(x["date"]) <= led]}
    if cli_basis != "edition month end (conservative rule)":
        dchk = _dbnomics_check(cli_ed, b)
        if dchk:
            ev.rt["cli"]["dbnomics_check"] = dchk
        achk = _alfred_check(cli_ed, b)
        if achk:
            ev.rt["cli"]["alfred_check"] = achk
    bci_era = cli_ed >= BCI_FROM_CLI_EDITION
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
    if cli_ed >= EA19_FROM and not bci_era:
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
        if not len(s) and bci_era and cc in BCI_AREAS:
            continue            # no CLI estimated any more: business confidence below
        if not len(s) and ed.date >= CLI_ABSENT_FALLBACK_FROM:
            src_ed, rows, e_prev = _withheld_fallback(ed, cli_ed, area, CLI_ABSENT_DEPTH)
            s = _cap(_monthly(rows), ed)
            ev.rt["cli"].setdefault("absent", {})[area] = src_ed if e_prev is not None else None
            if e_prev is None:
                ev.notes.append(
                    f"cli/{cc}: the {edition_label(cli_ed)} edition carries no {area} leading "
                    f"indicator, nor does any eligible edition among the {CLI_ABSENT_DEPTH} "
                    "before it; no growth input.")
                continue
            ev.add(e_prev)
            ev.notes.append(
                f"cli/{cc}: the {edition_label(cli_ed)} edition carries no {area} leading "
                f"indicator; the newest earlier eligible edition carrying it "
                f"({edition_label(src_ed)}, through {s.index.max() if len(s) else 'n/a'}) is used.")
            if not len(s) or not fresh("cli", cc, s, f"the {edition_label(src_ed)} CLI edition"):
                continue
            panels["cli"][cc] = s
            ev.growth_def[cc] = (f"OECD composite leading indicator, amplitude adjusted, as "
                                 f"published in the {edition_label(src_ed)} edition (real-time "
                                 f"database, LI_AA {area}; not carried by the "
                                 f"{edition_label(cli_ed)} edition)")
            record("cli", cc, s)
            continue
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
        # A single area whose history this edition re-estimates (e.g. Mexico in April
        # 2021, returning after a gap): the page says so; the series is used as published.
        an = register().get(cli_ed, {}).get("area_notes", {}).get(area)
        if an:
            ev.notes.append(f"cli/{cc}: {an}")

    ev.rt["cli"]["ref"] =max(ev.obs[cc]["cli"] for cc in panels["cli"]) if panels["cli"] else ""

    # ---- growth: business confidence where the CLI is no longer estimated ---------
    if bci_era:
        bb, be = S.dbnomics_file(
            S.OECD_PROJECT, MEI_CLI_PATH, ed.cutoff_iso, "dbnomics-oecd-meicli",
            "OECD Main Economic Indicators, composite leading indicators dataset (MEI_CLI), "
            "read only for the business confidence indicator BSCICP03 (amplitude adjusted, "
            "long-term average = 100).")
        ser = S.read_jsonl_series(bb, {f"BSCICP03.{i3}.M" for i3 in BCI_AREAS.values()})
        sha12 = be.proof_url.rsplit("/", 1)[-1][:12]
        n_li = len(panels["cli"])
        used, gated = [], []
        bts_gate = gate_lag1(ed)
        for cc, i3 in BCI_AREAS.items():
            if cc in panels["cli"]:
                continue
            code = f"BSCICP03.{i3}.M"
            s = _cap(_monthly(ser.get(code, [])), ed)
            if ed.date >= BCI_GATED_FROM:
                # the present-day survey balance behind the gate competes with the dated
                # archive; the fresher one is used, the archive on a tie
                gs, gkey, ge = bts_gated(cc, bts_gate)
                gs = _cap(gs.dropna(), ed)
                if len(gs) and (not len(s) or gs.index.max() > s.index.max()):
                    if not fresh("cli", cc, gs, f"the business confidence balance {gkey}"):
                        continue
                    gs = 100.0 + (gs - gs.mean())
                    panels["cli"][cc] = gs
                    ev.add(ge)
                    ev.growth_def[cc] = (
                        f"OECD composite business confidence, manufacturing ({gkey}, percent "
                        f"balance), present-day history requested only through "
                        f"{ge.available_by.split(' through ')[1].split(' ')[0]}, normalized to "
                        "100 + its deviation from its own pre-cutoff average: a survey-based "
                        "proxy, not a CLI"
                        + ("; quarterly survey repeated across its three reference months"
                           if cc in BTS_QUARTERLY else "")
                        + ("; EA20 aggregate as the euro-area proxy" if cc == "XM" else "")
                        + (f"; fresher than BSCICP03 in DBnomics MEI_CLI commit {sha12} "
                           f"(through {s.index.max()})" if len(s) else ""))
                    record("cli", cc, gs)
                    gated.append(cc)
                    continue
            if not len(s) or not fresh("cli", cc, s, f"the business confidence indicator {code}"):
                continue
            panels["cli"][cc] = s
            ev.growth_def[cc] = (
                f"OECD business confidence indicator, amplitude adjusted (long-term average = "
                f"100; {code}), DBnomics MEI_CLI commit {sha12}: a survey-based proxy on the "
                "CLI's scale, not a CLI" + ("; EA19 aggregate as the euro-area proxy"
                                           if cc == "XM" else ""))
            record("cli", cc, s)
            used.append(cc)
        if used:
            ev.add(be)
        ev.rt["cli"]["bci"] = {"commit": sha12, "committed": be.available_by, "ledger": be.id,
                               "url": be.proof_url, "areas": used, "n_cli": n_li}
        if gated:
            ev.rt["cli"]["bci"]["gated"] = gated
            ev.rt["cli"]["bci"]["gate"] = str(bts_gate)
        if ed.date < BCI_GATED_FROM:
            ev.notes.append(
                f"cli: from the {edition_label(BCI_FROM_CLI_EDITION)} edition the real-time "
                f"database carries the leading indicator only for the {n_li} economies the OECD "
                "still estimates (its release of 2022-12-08 announced that the CLIs would continue "
                "to be estimated for a reduced set of countries); the economies without one ("
                + ", ".join(COUNTRIES[c].name for c in used) + ") take the OECD "
                "business confidence indicator BSCICP03 (amplitude adjusted, long-term average 100) "
                f"as served in DBnomics git commit {sha12} of the OECD MEI_CLI dataset, committed "
                f"{be.available_by[:16].replace('T', ' ')} UTC, before the cutoff. It is the live "
                "pipeline's fallback: a survey-based proxy on the CLI's scale, not a leading "
                "indicator.")
        else:
            parts = []
            if used:
                parts.append(
                    "the OECD business confidence indicator BSCICP03 (amplitude adjusted, long-term "
                    f"average 100) as served in DBnomics git commit {sha12} of the OECD MEI_CLI "
                    f"dataset, committed {be.available_by[:16].replace('T', ' ')} UTC, before the "
                    "cutoff, for " + ", ".join(COUNTRIES[c].name for c in used))
            if gated:
                parts.append(
                    "the OECD business-tendency-survey composite confidence balance for "
                    "manufacturing, present-day history requested only through "
                    f"{bts_gate} (one full month after each reference month) and normalized to "
                    "100 + its deviation from its own pre-cutoff average, for "
                    + ", ".join(COUNTRIES[c].name for c in gated)
                    + f" (fresher than that archive, whose newest pre-cutoff commit is of "
                    f"{be.available_by[:10]})")
            ev.notes.append(
                f"cli: the real-time database carries the leading indicator only for the {n_li} "
                "economies the OECD still estimates (its release of 2022-12-08 announced that the "
                "CLIs would continue to be estimated for a reduced set of countries); the economies "
                "without one take " + "; and ".join(parts) + ". Both are survey-based proxies, not "
                "leading indicators.")

    # ---- inflation --------------------------------------------------------
    cpi_ed, cpi_pub, cpi_basis = cpi_edition(ed)
    log(f"inflation: OECD real-time CPI, {edition_label(cpi_ed)} edition; US ALFRED "
        f"{ed.alfred_vintage}")
    b, cpi_e = oecd_rt("CP", cpi_ed, cpi_pub, cpi_basis)
    cp = parse_rt(b)
    ev.rt["cpi"] = {"edition": cpi_ed, "label": edition_label(cpi_ed), "public_by": cpi_pub,
                      "basis": cpi_basis}
    if bci_era:
        ev.notes.append(
            "cpi/XM: " + (f"from the {edition_label(EA20_FROM)} edition the real-time database "
                          "carries the euro-area aggregate as EA20 (Croatia joined the euro area "
                          "on 1 January 2023) instead of EA19; the aggregate is used as published."
                          if cpi_ed >= EA20_FROM else
                          "this edition of the real-time database carries the euro-area "
                          "aggregate as EA19; the aggregate is used as published."))
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
        shown_only = []
        if cc in RT_AREA and bis_for_definition(cc, ed):
            s, lbl = _rt_cpi(cc, cp, cpi_ed)
            shown_only.append((s, lbl.replace(
                f"OECD real-time CPI index {rt_areas(cpi_ed)[cc]}",
                f"OECD real-time CPI index {rt_areas(cpi_ed)[cc]} (CPI for Industrial Workers; "
                "not used: not the targeted index)", 1)))
            bb, be = bis_gated("WS_LONG_CPI", f"M.{cc}.771", lag1, "1985-01",
                               f"BIS WS_LONG_CPI M.{cc}.771 (CPI y/y)",
                               "one-full-month publication-lag gate")
            cands.append(("bis_gated", _monthly(S.parse_bis_csv(bb)), be,
                          f"BIS WS_LONG_CPI M.{cc}.771 (all-India Combined CPI), present-day "
                          f"history gated at {lag1}"))
            missing_note = ("definition", None)
        elif cc in RT_AREA and truncated_in_vintage(cc, cpi_ed):
            s, lbl = _rt_cpi(cc, cp, cpi_ed)
            shown_only.append((s, lbl.replace(
                f"OECD real-time CPI index {rt_areas(cpi_ed)[cc]}",
                f"OECD real-time CPI index {rt_areas(cpi_ed)[cc]} (stops at "
                f"{CPI_TRUNCATED_BIS[cc]['ends']}; not used: no longer updated in this edition)", 1)))
            bb, be = bis_gated("WS_LONG_CPI", f"M.{cc}.771", lag1, "1985-01",
                               f"BIS WS_LONG_CPI M.{cc}.771 (CPI y/y)",
                               "one-full-month publication-lag gate")
            cands.append(("bis_gated", _monthly(S.parse_bis_csv(bb)), be,
                          f"BIS WS_LONG_CPI M.{cc}.771, present-day history gated at {lag1}"))
            missing_note = ("truncated", None)
        elif cc in RT_AREA:
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
        for s0, lbl0 in shown_only:
            s0 = _cap(s0.dropna(), ed)
            if not s0.empty:
                considered.append({"candidate": lbl0, "last": str(s0.index.max()),
                                   "last_value": round(float(s0.iloc[-1]), 3)})
        if best is None:
            continue
        k, s, e, lbl = best
        if missing_note and missing_note[0] == "definition":
            ev.notes.append(
                f"cpi/{cc}: {CPI_DEFINITION_BIS[cc]['why']}; the present-day BIS Combined CPI "
                f"history behind the one-full-month publication gate (latest {s.index.max()}) "
                f"is used, not the {edition_label(cpi_ed)} vintage index.")
        elif missing_note and missing_note[0] == "truncated":
            ev.notes.append(
                f"cpi/{cc}: the {edition_label(cpi_ed)} CPI edition carries the "
                f"{rt_areas(cpi_ed)[cc]} index only through {CPI_TRUNCATED_BIS[cc]['ends']} "
                f"({CPI_TRUNCATED_BIS[cc]['earlier']}); the "
                "present-day BIS history behind the one-full-month publication gate (latest "
                f"{s.index.max()}) is used instead.")
        elif missing_note and missing_note[0] == "fixed-base":
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
                                        "definition" if missing_note and
                                        missing_note[0] == "definition" else
                                        "truncated" if missing_note and
                                        missing_note[0] == "truncated" else
                                        "absent" if missing_note else "")}
        record("cpi", cc, s)
    if used_cpi_rt:
        ev.add(cpi_e)

    # ---- REER + 10y ---------------------------------------------------------
    log(f"REER: BIS broad, gated at {lag1}; 10y yields: completed months to {ed.anchor}")
    reer_alfred = []
    for cc, c in COUNTRIES.items():
        s = pd.Series(dtype=float)
        if ed.date >= REER_ALFRED_FROM:
            ab, ae = S.alfred(f"RB{cc}BIS", ed.alfred_vintage.isoformat())
            s = _cap(_monthly([(p[:7], v) for p, v in S.parse_alfred_csv(ab)]), ed)
            if len(s):
                ev.add(ae)
                reer_alfred.append(cc)
        if not len(s):
            bb, be = bis_gated("WS_EER", f"M.R.B.{cc}", lag1, "1994-01",
                               f"BIS broad real effective exchange rate M.R.B.{cc}",
                               "one-full-month publication-lag gate")
            s = _cap(_monthly(S.parse_bis_csv(bb)), ed)
            if len(s):
                ev.add(be)
        if len(s):
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
        for er in DAILY_ERRATA.get(cc, []):
            t = pd.Timestamp(er["day"])
            nb = d[d.index > t]
            pv = d[d.index < t]
            if (t in d.index and len(nb) and len(pv) and abs(float(d.loc[t]) - er["bis"]) < LEVEL_EPS
                    and abs(float(nb.iloc[0]) - float(pv.iloc[-1])) < LEVEL_EPS):
                d = d.copy()
                d.loc[t] = float(pv.iloc[-1])
                ev.notes.append(
                    f"policy/{cc}: the BIS daily series shows {er['bis']:.2f}% on "
                    f"{er['day'].isoformat()} only, between {float(pv.iloc[-1]):.2f}% on "
                    f"{pv.index[-1].date().isoformat()} and {nb.index[0].date().isoformat()}; no "
                    "decision was announced, so that day is read at "
                    f"{float(pv.iloc[-1]):.2f}% (a one-day data error, not a policy move).")
        for fx in DAILY_DATE_FIX.get(cc, []):
            t0, t1 = pd.Timestamp(fx["bis_from"]), pd.Timestamp(fx["published"])
            pv = d[d.index < t0]
            early = d[(d.index >= t0) & (d.index < t1)]
            if not len(early) or not len(pv):
                continue
            d = d.copy()
            d.loc[early.index] = float(pv.iloc[-1])
            if led < fx["published"]:       # not yet published: nothing to say on the page
                continue
            ev.notes.append(
                f"policy/{cc}: the BIS daily series carries {float(early.iloc[0]):.2f}% from "
                f"{fx['bis_from'].isoformat()} ({fx['bis_from']:%A}), but the new level was "
                f"published on {fx['published'].isoformat()} ({fx['source']}); the days before "
                f"are read at {float(pv.iloc[-1]):.2f}%, so the change is dated when it was "
                "made public.")
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
                # the splice: the new instrument's level before the switch when the switch
                # day also carries a decision, else the switch-day jump itself
                base = sw.get("new_before", float(post.iloc[0]))
                jump = round(base - float(pre.iloc[-1]), 3)
                d = d.copy()
                d[d.index < t] = d[d.index < t] + jump
                months = [q for q in m.index if q.end_time < t]
                m.loc[months] = m.loc[months] + jump
                if "new_before" in sw:
                    ev.notes.append(
                        f"policy/{cc}: the BIS series switches from the {sw['old']} to the "
                        f"{sw['new']} on {sw['date'].isoformat()} ({float(pre.iloc[-1]):.2f}% → "
                        f"{float(post.iloc[0]):.2f}%; {sw['source']}). The {sw['new']} stood at "
                        f"{base:.2f}% before that day, so earlier history is spliced by "
                        f"{jump:+.2f}pp, the spread between the two rates then in force (exact "
                        "for the five years before the switch; earlier spreads differed), and "
                        f"{sw['decision']}.")
                else:
                    ev.notes.append(
                        f"policy/{cc}: the {sw['new']} became the policy rate on "
                        f"{sw['date'].isoformat()} (the BIS series switches from the {sw['old']}, "
                        f"{float(pre.iloc[-1]):.2f}% → {float(post.iloc[0]):.2f}%). "
                        + (f"{sw['not_change']} ({sw['source']})" if sw.get("not_change") else
                           f"The switch is not a rate change ({sw['source']})")
                        + f": earlier history is spliced by {jump:+.2f}pp so "
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

    if reer_alfred:
        ev.rt["reer_alfred"] = reer_alfred
    pc = policy_context(ed)
    if pc:
        ev.rt["policy_context"] = pc

    out = {}
    for k, dct in panels.items():
        dct = {cc: _ts(s) for cc, s in dct.items() if len(s)}
        out[k] = pd.DataFrame(dct).sort_index() if dct else pd.DataFrame()
    return out, ev
