"""HTML evidence sections for real-time-era retrospective editions (e.g. 2008).

Mirrors ``evidence_html`` but describes the real-time sources used when no
DBnomics archive exists: OECD revisions-database editions, ALFRED, BIS decision
histories and explicitly gated present-day histories.
"""

from __future__ import annotations

import html
import json
from datetime import date

import numpy as np

from ..universe import COUNTRIES
from .editions import Edition
from .panels import Evidence
from . import realtime as R
from .benchmarks import era_benchmarks, targets_for

ANN_SOURCES = json.loads((R.OUT_ROOT / "announcement_sources.json").read_text())

POLICY_INSTRUMENT_RT = {
    "US": "Federal funds target rate", "XM": "ECB main refinancing operations rate",
    "JP": "Uncollateralized overnight call-rate target", "GB": "Bank Rate",
    "CA": "Target for the overnight rate", "AU": "Cash rate target",
    "CH": "Midpoint of the SNB three-month CHF Libor target range",
    "SE": "Riksbank repo rate", "NO": "Norges Bank key policy rate (sight deposit rate)",
    "NZ": "Official Cash Rate", "CN": "PBoC one-year benchmark lending rate",
    "IN": "RBI repo rate", "BR": "Selic target",
    "MX": "Overnight interbank rate (BIS series)", "ZA": "SARB repurchase rate",
    "TR": "CBRT overnight borrowing rate", "PL": "NBP reference rate", "HU": "MNB base rate",
    "CZ": "CNB two-week repo rate", "ID": "BI Rate",
    "KR": "Bank of Korea policy rate (BIS series)", "CL": "Monetary policy rate",
    "CO": "BanRep intervention rate", "TH": "BOT one-day repurchase rate",
}


def instrument(cc: str, ed: Edition) -> str:
    """Instrument label as of the edition (no later regime is named)."""
    if cc == "US" and ed.last_eligible_day >= date(2019, 10, 31):
        # FOMC statement of 30 Oct 2019: "the Committee decided to lower the target
        # range for the federal funds rate to 1-1/2 to 1-3/4 percent"; effective 31 Oct
        return ("Federal funds target range midpoint (1.50–1.75% range from 31 Oct 2019, "
                "after 1.75–2.00% from 19 Sep 2019)")
    if cc == "US" and ed.last_eligible_day >= date(2019, 9, 19):
        # FOMC statement of 18 Sep 2019: "the Committee decided to lower the target
        # range for the federal funds rate to 1-3/4 to 2 percent"; effective 19 Sep
        return ("Federal funds target range midpoint (1.75–2.00% range from 19 Sep 2019, "
                "after 2.00–2.25% from 1 Aug 2019)")
    if cc == "US" and ed.last_eligible_day >= date(2019, 8, 1):
        # FOMC statement of 31 Jul 2019: "the Committee decided to lower the target
        # range for the federal funds rate to 2 to 2-1/4 percent"; effective 1 Aug
        return ("Federal funds target range midpoint (2.00–2.25% range from 1 Aug 2019, "
                "after 2.25–2.50% from 20 Dec 2018)")
    if cc == "CN" and ed.last_eligible_day >= date(2019, 8, 20):
        # PBoC Announcement [2019] No. 15, 17 Aug 2019: LPR reform; first new 1-year
        # LPR published 20 Aug 2019 (4.25%); the BIS series switches that day
        return ("One-year loan prime rate (LPR), the reference rate for new loans under the "
                "PBoC's reform announced 17 Aug 2019 (first fixing 20 Aug 2019); earlier "
                "history spliced from the PBoC one-year benchmark lending rate")
    if cc == "CH" and ed.last_eligible_day >= date(2019, 6, 13):
        # SNB monetary policy assessment of 13 Jun 2019: introduction of the SNB policy
        # rate (-0.75%), replacing the target range for three-month CHF Libor
        return ("SNB policy rate (introduced 13 Jun 2019 at −0.75%, replacing the "
                "three-month CHF Libor target range, whose midpoint the earlier months use)")
    if cc == "US" and ed.last_eligible_day >= date(2018, 12, 20):
        # FOMC statement of 19 Dec 2018: "the Committee decided to raise the target
        # range for the federal funds rate to 2-1/4 to 2-1/2 percent"; effective 20 Dec
        return ("Federal funds target range midpoint (2.25–2.50% range from 20 Dec 2018, "
                "after 2.00–2.25% from 27 Sep 2018)")
    if cc == "US" and ed.last_eligible_day >= date(2018, 9, 27):
        # FOMC statement of 26 Sep 2018: "the Committee decided to raise the target
        # range for the federal funds rate to 2 to 2-1/4 percent"; effective 27 Sep
        return ("Federal funds target range midpoint (2.00–2.25% range from 27 Sep 2018, "
                "after 1.75–2.00% from 14 Jun 2018)")
    if cc == "US" and ed.last_eligible_day >= date(2018, 6, 14):
        # FOMC statement of 13 Jun 2018: "the Committee decided to raise the target
        # range for the federal funds rate to 1-3/4 to 2 percent"; effective 14 Jun
        return ("Federal funds target range midpoint (1.75–2.00% range from 14 Jun 2018, "
                "after 1.50–1.75% from 22 Mar 2018)")
    if cc == "US" and ed.last_eligible_day >= date(2018, 3, 22):
        # FOMC statement of 21 Mar 2018: "the Committee decided to raise the target
        # range for the federal funds rate to 1-1/2 to 1-3/4 percent"; effective 22 Mar
        return ("Federal funds target range midpoint (1.50–1.75% range from 22 Mar 2018, "
                "after 1.25–1.50% from 14 Dec 2017)")
    if cc == "US" and ed.last_eligible_day >= date(2017, 12, 14):
        # FOMC statement of 13 Dec 2017: "the Committee decided to raise the target
        # range for the federal funds rate to 1-1/4 to 1-1/2 percent"; effective 14 Dec
        return ("Federal funds target range midpoint (1.25–1.50% range from 14 Dec 2017, "
                "after 1.00–1.25% from 15 Jun 2017)")
    if cc == "US" and ed.last_eligible_day >= date(2017, 6, 15):
        # FOMC statement of 14 Jun 2017: "the Committee decided to raise the target
        # range for the federal funds rate to 1 to 1-1/4 percent"; effective 15 Jun
        return ("Federal funds target range midpoint (1.00–1.25% range from 15 Jun 2017, "
                "after 0.75–1.00% from 16 Mar 2017)")
    if cc == "US" and ed.last_eligible_day >= date(2017, 3, 16):
        # FOMC statement of 15 Mar 2017: "the Committee decided to raise the target
        # range for the federal funds rate to 3/4 to 1 percent"; effective 16 Mar
        return ("Federal funds target range midpoint (0.75–1.00% range from 16 Mar 2017, "
                "after 0.50–0.75% from 15 Dec 2016)")
    if cc == "US" and ed.last_eligible_day >= date(2016, 12, 15):
        # FOMC statement of 14 Dec 2016: "the Committee decided to raise the target
        # range for the federal funds rate to 1/2 to 3/4 percent"; effective 15 Dec
        return ("Federal funds target range midpoint (0.50–0.75% range from 15 Dec 2016, "
                "after 0.25–0.50% from 17 Dec 2015)")
    if cc == "US" and ed.last_eligible_day >= date(2015, 12, 17):
        # FOMC statement of 16 Dec 2015: "the Committee decided to raise the target
        # range for the federal funds rate to 1/4 to 1/2 percent"; effective 17 Dec
        return ("Federal funds target range midpoint (0.25–0.50% range from 17 Dec 2015, "
                "after 0–0.25% from 16 Dec 2008)")
    if cc == "US" and ed.last_eligible_day >= date(2008, 12, 16):
        return "Federal funds target range midpoint (0–0.25% range from 16 Dec 2008)"
    if cc == "TR" and ed.last_eligible_day >= date(2018, 6, 1):
        # CBRT press release of 28 May 2018 on the simplification of the operational
        # framework: from 1 Jun 2018 the one-week repo rate is the policy (funding) rate
        return ("CBRT one-week repo rate (policy rate from 20 May 2010; earlier history "
                "spliced from the overnight borrowing rate; again the CBRT's funding rate from "
                "1 Jun 2018, see the operational context below the policy decisions)")
    if cc == "TR" and ed.last_eligible_day >= date(2010, 5, 20):
        return ("CBRT one-week repo rate (policy rate from 20 May 2010; earlier history "
                "spliced from the overnight borrowing rate)")
    if cc == "ID" and ed.last_eligible_day >= date(2016, 8, 19):
        return ("BI 7-Day (Reverse) Repo Rate (policy rate from 19 Aug 2016; earlier history "
                "spliced from the BI Rate)")
    if cc == "JP" and ed.last_eligible_day >= date(2016, 9, 21):
        # BoJ, 'New Framework for Strengthening Monetary Easing: "Quantitative and
        # Qualitative Monetary Easing with Yield Curve Control"', 21 Sep 2016
        return ("Short-term policy interest rate: −0.1% applied to Policy-Rate Balances in "
                "BoJ current accounts (QQE with Yield Curve Control, from 21 Sep 2016; the same "
                "rate applied from 16 Feb 2016). Earlier months at the former 0–0.1% "
                "call-rate guideline (0.05%), a proxy while the monetary base was the main "
                "operating target")
    if cc == "JP" and ed.last_eligible_day >= date(2016, 2, 16):
        # BoJ, 'Introduction of "Quantitative and Qualitative Monetary Easing with a
        # Negative Interest Rate"', 29 Jan 2016, effective 16 Feb 2016
        return ("Rate applied to Policy-Rate Balances in BoJ current accounts (−0.1% from "
                "16 Feb 2016, announced 29 Jan 2016); the main operating target remains the "
                "monetary base (QQE). Earlier months at the former 0–0.1% call-rate guideline "
                "(0.05%), a short-rate proxy")
    if cc == "JP" and ed.last_eligible_day >= date(2013, 4, 4):
        # BoJ, 'Introduction of the "Quantitative and Qualitative Monetary Easing"',
        # 4 Apr 2013: "the main operating target for money market operations is changed
        # from the uncollateralized overnight call rate to the monetary base"
        return ("BIS series at the former uncollateralized overnight call-rate guideline "
                "(0–0.1%); from 4 Apr 2013 the BoJ's main operating target is the monetary "
                "base (QQE), so the level is a short-rate proxy, not a target")
    return POLICY_INSTRUMENT_RT.get(cc, "")


def _e(x) -> str:
    return html.escape(str(x))


def _links(items: list[dict]) -> str:
    return "; ".join(f'<a href="{_e(x["url"])}">{_e(x["label"])}</a>' for x in items)


def render(ed: Edition, ev: Evidence, res, reconstructed: str) -> str:
    C = COUNTRIES
    H: list[str] = []
    add = H.append
    led = ev.ledger
    cli, cpi = ev.rt["cli"], ev.rt["cpi"]
    anc = ed.anchor
    lag1 = R.gate_lag1(ed)
    n_cli = len(ev.growth_def)

    add("<h2>Historical inputs and timing</h2>")
    add(f'<p class="sub">Information cutoff: before {ed.date:%-d %B %Y}, 00:00 '
        f"Europe/Warsaw ({ed.cutoff_iso}). Reconstructed on {reconstructed}. No archive of "
        f"the present-day sources reaches back to {ed.date.year}, so every input is either "
        "a real-time vintage, a decision history dated to the day, or a present-day history "
        "cut at an explicit, conservative publication gate; each one, with its availability "
        "bound, is in the ledger below. Projected paths are model scenarios, not realised "
        "outcomes.</p>")
    chk = cli.get("content_check")
    chk_txt = ""
    if chk:
        chk_txt = (" Content check: the edition’s " + _e(chk["area"]) + " aggregate for "
                   + _e(chk["month"]) + " gives " + ", ".join(
                       f"{x['what']} {x['edition']:+.2f}" if x["what"] != "level"
                       else f"level {x['edition']:.2f}" for x in chk["items"])
                   + ", matching the published " + ", ".join(
                       f"{x['what']} {x['reported']:+.1f}" if x["what"] != "level"
                       else f"level {x['reported']:.1f}" for x in chk["items"]) + ".")
    add(f'<p class="sub"><b>Growth.</b> {n_cli} growth inputs are OECD composite leading '
        f"indicators, amplitude adjusted, exactly as published in the {_e(cli['label'])} "
        "edition of the OECD real-time revisions database (Main Economic Indicators vintages, "
        f"never revised afterwards; latest reference month {_e(ev.rt['cli'].get('ref', ''))}"
        f"). That edition is used because its CLI was public by {_e(cli['public_by'])} "
        f"({_e(cli['basis'])}).{chk_txt} Evidence: {_links(cli.get('evidence', [])) or 'edition month end'}. "
        + (_e(cli["method_note"]["text"]) + " Source: "
           + _links([cli["method_note"]]) + ". " if cli.get("method_note") else "")
        + "Chile, Colombia and Thailand have no real-time leading indicator and no growth input; "
        f"an input whose latest observation is more than {R.STALE_MONTHS} months older than the "
        "anchor month is not used (data notes below)"
        + ".</p>")
    us = ev.cpi_choice.get("US", {})
    extra_bis = [c for c, v in ev.cpi_choice.items()
                 if v.get("kind") == "bis_gated" and c not in R.NO_RT
                 and v.get("reason") not in ("fixed-base", "definition")]
    def_bis = [c for c, v in ev.cpi_choice.items()
               if v.get("kind") == "bis_gated" and v.get("reason") == "definition"]
    fixed_bis = [c for c, v in ev.cpi_choice.items()
                 if v.get("kind") == "bis_gated" and v.get("reason") == "fixed-base"]
    cn_ed = (ev.cpi_choice.get("CN") or {}).get("chosen", "")
    if (R.stored_as_yoy("CN", cpi["edition"])
            or (ev.cpi_choice.get("CN") or {}).get("reason") != "fixed-base"):
        cn_txt = ("China’s series is stored as an index of the same month of the previous "
                  "year = 100, so its y/y is the value less 100. ")
    else:
        cn_txt = ("China’s series is stored in this edition as a fixed-base index, so its y/y "
                  "is the 12-month ratio inside the vintage; because that derived index can "
                  "deviate from the published y/y, the published y/y behind the one-full-month "
                  "gate competes and the fresher series is used"
                  + (" (here the published y/y)" if "BIS" in cn_ed else " (here the vintage)")
                  + ". ")
    add(f'<p class="sub"><b>Inflation.</b> Headline CPI y/y for 21 economies is computed '
        f"inside a single real-time vintage: the OECD consumer-price index of the "
        f"{_e(cpi['label'])} edition, the newest edition whose month had ended before the "
        "cutoff (a conservative bound; no earlier publication date is claimed). "
        + cn_txt + "Australia and New Zealand publish quarterly CPI, repeated "
        "across each quarter’s three months. The United States uses the BLS CPI-U all-items "
        f"NSA index from the ALFRED {ed.alfred_vintage.isoformat()} (Friday) vintage, latest "
        f"{_e(us.get('last', '?'))}. Chile, Colombia and Thailand"
        + ("".join(f", and {_e(C[c].name)} (absent from the eligible real-time edition)"
                   for c in extra_bis))
        + ("".join(f", and {_e(C[c].name)} (published y/y fresher than the vintage index)"
                   for c in fixed_bis))
        + ("".join(f", and {_e(C[c].name)} (its vintage series is the CPI for Industrial "
                   "Workers, not the Combined CPI the RBI targets)" for c in def_bis))
        + " use the present-day BIS CPI "
        f"history requested only through {lag1}: a reference month is admitted once the whole "
        "following month has passed, although these offices publish within about ten days. "
        + ("Headline CPI y/y is rarely revised, but those three histories are not vintages. "
           if not (extra_bis or fixed_bis or def_bis) else
           "Headline CPI y/y is rarely revised, but those histories are not vintages. ")
        + 
        "Newer national releases that were public before the cutoff but are absent from the "
        "eligible vintage are not inserted, so an older observation date does not mean no "
        "newer release existed.</p>")
    add(f'<p class="sub"><b>Exchange rates and yields.</b> No vintage of the BIS broad real '
        f"effective exchange rates for {ed.date.year} is retrievable. All 24 REER histories "
        f"are present-day BIS broad indices requested only through {lag1} (one full month "
        "after each reference month, against BIS publication around mid-month). Their later "
        "revisions — updated trade weights, revised consumer prices, a wider basket — are "
        "not removed; REER enters the model only through the valuation leg of the FX score. "
        f"The 17 ten-year government yields are monthly market averages through {anc}, the "
        "last completed month; market yields were observable as the month ended and are not "
        "revised.</p>")
    a3, a6, a12 = anc - 3, anc - 6, anc - 12
    add(f'<p class="sub"><b>Policy.</b> Monthly policy histories are BIS end-of-month '
        f"policy rates through {anc}, the last completed month. The current effective "
        f"snapshot is the rate in force on {ed.last_eligible_day.isoformat()} in the BIS "
        "daily decision history (downloaded only to that day): decisions announced but not "
        "yet effective at the cutoff are excluded. Policy rates are administrative facts, "
        "public when set, and are not revised. Changes are measured from the snapshot to "
        f"exact completed-month anchors (3m: {a3}, 6m: {a6}, 12m: {a12}). Policy "
        "instruments are those of the time (see the table); Mexico’s BIS series is the "
        "overnight interbank rate"
        + (", a daily market rate until Banxico targeted it" if ed.last_eligible_day >=
           R.MARKET_RATE_BEFORE["MX"] else ", a daily market rate in this period")
        + ". Indicative carry is a policy-rate differential, not an executable forward "
        "quote; the curve input is the 10y yield minus the matched-month policy rate, not a "
        "traded 2s10s spread. OU horizons start at each series’ last eligible observation, so "
        "ETAs are not countdowns from the edition date.</p>")
    if ev.gaps:
        parts = []
        for k in sorted(ev.gaps):
            g = ev.gaps[k]
            parts.append(f"{k}: {', '.join(g) if len(g) <= 12 else ', '.join(g[:6]) + f' … {len(g) - 6} more through ' + g[-1]}")
        add('<p class="sub">Source observations missing inside the histories (no values are '
            "filled): " + "; ".join(_e(p) for p in parts) + ".</p>")
    eb = era_benchmarks(ed)
    if eb:
        add('<p class="sub"><b>Inflation benchmarks</b> are those publicly in force at the '
            "cutoff and are held constant through each historical fit. " + _e(eb["note"])
            + "</p>")

    # ---- observation dates ----------------------------------------------------
    add("<h3>Historical observation dates</h3>")
    add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>policy</th><th>cpi</th>'
        "<th>reer</th><th>growth</th><th>y10</th><th>Matched clock month</th></tr></thead><tbody>")
    for cc, c in C.items():
        o = ev.obs.get(cc, {})
        clk = res.clocks.get(cc)
        mm = clk.history.index[-1].strftime("%Y-%m") if clk is not None else "Not available"
        g = o.get("cli") or ("No real-time input" if cc in R.NO_RT else "Stale; not used")
        add(f'<tr><td class="name">{_e(c.name)}</td><td class="num">{o.get("policy") or "–"}</td>'
            f'<td class="num">{o.get("cpi") or "–"}</td><td class="num">{o.get("reer") or "–"}</td>'
            f'<td class="num">{g}</td>'
            f'<td class="num">{o.get("y10") or ("Not configured" if not c.fred_10y else "–")}</td>'
            f'<td class="num">{mm}</td></tr>')
    add("</tbody></table></div>")

    # ---- effective policy and CPI -----------------------------------------------
    add("<h2>Effective policy and latest published CPI</h2>")
    add('<p class="sub">Assessed real rate = current effective policy rate minus the latest '
        "eligible CPI reading (distinct from historical real rates matched by month). "
        "“Effective since” is the first day of the current level in the BIS daily decision "
        "history.</p>")
    add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>Instrument</th>'
        "<th>Current policy</th><th>Effective since</th><th>Benchmark</th>"
        "<th>Latest CPI</th><th>Assessed real rate</th></tr></thead><tbody>")
    tgt = targets_for(ed)
    for cc, c in C.items():
        p = ev.policy.get(cc)
        st = res.stances.get(cc)
        ch = ev.cpi_choice.get(cc, {})
        if p is None:
            continue
        rr = st.real_rate if st is not None else np.nan
        add(f'<tr><td class="name">{_e(c.name)}</td><td style="white-space:normal">'
            f"{_e(instrument(cc, ed))}</td>"
            f'<td class="num">{p.current:.2f}%</td><td class="num">{_e(p.effective_since)}</td>'
            f'<td class="num">{tgt.get(cc, c.infl_target):.2f}%</td>'
            f'<td class="num">{ch.get("last", "–")}: {ch.get("last_value", float("nan")):.2f}%</td>'
            f'<td class="num">{rr:+.2f}%</td></tr>')
    add("</tbody></table></div>")

    # ---- recent decisions ----------------------------------------------------------
    add("<h3>Policy decisions effective in the six months before the cutoff</h3>")
    if ev.decisions:
        add('<p class="sub">From the BIS daily decision history (changes of at least '
            f"{R.DECISION_MIN_PP:.2f}pp). Every one took effect on or before "
            f"{ed.last_eligible_day.isoformat()}.</p>")
        add('<ul class="standouts">')
        for a in sorted(ev.decisions, key=lambda a: a["effective"], reverse=True):
            add(f"<li><b>{_e(a['effective'])} · {_e(C[a['cc']].name)}</b> — "
                f"{_e(instrument(a['cc'], ed) or 'policy rate')} {a['from']:g}% → "
                f"{a['to']:g}% ({a['to'] - a['from']:+.2f}pp)</li>")
        add("</ul>")
    else:
        add('<p class="sub">None.</p>')
    bridges = [a for a in ev.announcements if a.get("source") == "daily bridge"]
    if bridges:
        parts = []
        for a in bridges:
            src = ANN_SOURCES[f"{a['cc']}|{a['effective']}"]
            parts.append(f"{_e(C[a['cc']].name)} from {_e(a['effective'])} at {a['to']:g}% "
                         f"(announced {_e(src['announced'])}): "
                         f'<a href="{_e(src["url"])}">{_e(src["label"])}</a>')
        add('<p class="sub">Levels used where the BIS daily history is blank (see the data '
            "notes): " + "; ".join(parts) + ".</p>")
    pctx = ev.rt.get("policy_context", [])
    if pctx:
        add('<p class="sub">Operational context the BIS series does not show (disclosed for '
            "reading the policy rows; not a model input): " + " ".join(
                f"{_e(C[x['cc']].name)} — {_e(x['text'])} "
                f'(<a href="{_e(x["url"])}">{_e(x["label"])}</a>).' for x in pctx) + "</p>")

    # ---- inflation inputs -------------------------------------------------------------
    add("<h3>Inflation inputs</h3>")
    add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>Series used</th>'
        "<th>Latest reference</th><th>Value</th><th>Other candidates (latest)</th></tr></thead><tbody>")
    for cc, c in C.items():
        ch = ev.cpi_choice.get(cc)
        if not ch:
            continue
        others = "; ".join(f"{x['candidate'].split(',')[0]} {x['last']}"
                           for x in ch["considered"] if x["candidate"] != ch["chosen"])
        add(f'<tr><td class="name">{_e(c.name)}</td><td style="white-space:normal">'
            f'{_e(ch["chosen"])}</td><td class="num">{ch["last"]}</td>'
            f'<td class="num">{ch["last_value"]:.2f}%</td>'
            f'<td style="white-space:normal">{_e(others) or "–"}</td></tr>')
    add("</tbody></table></div>")

    # ---- benchmarks ----------------------------------------------------------------------
    if eb:
        add("<h3>Inflation benchmarks in force at the cutoff</h3>")
        add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>Benchmark</th>'
            "<th>Official objective (index)</th><th>Source</th></tr></thead><tbody>")
        for cc, c in C.items():
            b = eb["rows"].get(cc)
            if not b:
                continue
            add(f'<tr><td class="name">{_e(c.name)}</td><td class="num">{b["value"]:.2f}%</td>'
                f'<td style="white-space:normal">{_e(b["wording"])} ({_e(b["index"])})</td>'
                f'<td style="white-space:normal">{_links(b["urls"]) or "–"}</td></tr>')
        add("</tbody></table></div>")

    # ---- growth definitions --------------------------------------------------------------
    add("<h3>Growth input definitions</h3>")
    add('<p class="sub">' + "; ".join(
        f"{_e(C[cc].name)}: {_e(ev.growth_def[cc])}" for cc in C if cc in ev.growth_def)
        + "; Chile, Colombia, Thailand: no real-time growth input.</p>")
    if ev.notes:
        add('<p class="sub">Data notes: ' + " ".join(_e(n) for n in ev.notes) + "</p>")

    # ---- ledger -----------------------------------------------------------------------------
    add("<h2>Historical source ledger</h2>")
    add('<p class="sub">Each entry: identifier (link to the exact bytes used), availability '
        "bound or gate, SHA-256 of the retrieved bytes, and the eligibility rule.</p>")
    add('<ul style="font-size:13px;line-height:1.55">')
    for k in sorted(led, key=lambda k: (led[k].kind, k)):
        e = led[k]
        proof = (f' · <a href="{_e(e.proof_url)}">source page</a>' if e.proof_url else "")
        add(f'<li><a href="{_e(e.url)}">{_e(e.id)}</a> · {_e(e.kind)} · available by '
            f"{_e(e.available_by)} · sha256 {e.sha256[:16]}… · {_e(e.note)}{proof}</li>")
    add("</ul>")
    return "\n".join(H)
