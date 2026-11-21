"""HTML evidence sections for a retrospective edition."""

from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np

from ..universe import COUNTRIES
from .panels import Evidence, BCI_QUARTERLY, CLI_13
from .editions import Edition
from .benchmarks import china_note, change_in_force, targets_for

SOURCES_FILE = Path(__file__).resolve().parents[2] / "data" / "retro" / "announcement_sources.json"

POLICY_INSTRUMENT = {
    "US": "Federal funds target range midpoint", "XM": "ECB deposit facility rate",
    "JP": "Uncollateralized overnight call-rate target", "GB": "Bank Rate",
    "CA": "Target for the overnight rate", "AU": "Cash rate target",
    "CH": "SNB policy rate", "SE": "Riksbank policy rate", "NO": "Norges Bank policy rate",
    "NZ": "Official Cash Rate", "CN": "One-year Loan Prime Rate (lending-benchmark proxy)",
    "IN": "Policy repo rate", "BR": "Selic target", "MX": "Target for the overnight interbank rate",
    "ZA": "Repurchase rate", "TR": "One-week repo auction rate", "PL": "NBP reference rate",
    "HU": "MNB base rate", "CZ": "Two-week repo rate", "ID": "BI-Rate",
    "KR": "Bank of Korea Base Rate", "CL": "Monetary policy rate",
    "CO": "Monetary policy intervention rate", "TH": "One-day bilateral repurchase rate",
}

BENCHMARK_NOTE = (
    "Inflation benchmarks are the analytical targets publicly known at the cutoff and are "
    "held constant through each edition’s historical fit rather than reconstructing past "
    "target regimes. The US formal 2% objective refers to PCE inflation and Sweden’s to "
    "CPIF, while this model uses headline CPI for both. Switzerland’s 1% is the midpoint of "
    "its 0–2% price-stability range; Australia’s 2.5% the midpoint of 2–3%; Thailand’s 2% "
    "the midpoint of 1–3%; South Africa’s 4.5% the midpoint of its 3–6% target range. "
    "{china} Türkiye’s 5% is the medium-term goal; "
    "Brazil’s 3% is the continuous "
    "target in force from January 2025.")


def _e(x) -> str:
    return html.escape(str(x))


def _load_sources() -> dict:
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text())
    return {}


def render(ed: Edition, ev: Evidence, res, reconstructed: str) -> str:
    C = COUNTRIES
    H: list[str] = []
    add = H.append
    srcs = _load_sources()
    anc = ed.anchor
    led = ev.ledger

    def lid(prefix: str):
        return next((v for k, v in led.items() if k.startswith(prefix)), None)

    kei, bts, bcpi, bpol = (lid("dbnomics-oecd-kei"), lid("dbnomics-oecd-bts"),
                            lid("dbnomics-bis-cpi"), lid("dbnomics-bis-cbpol"))

    add("<h2>Historical inputs and timing</h2>")
    add(f'<p class="sub">Information cutoff: before {ed.date:%-d %B %Y}, 00:00 '
        f"Europe/Warsaw ({ed.cutoff_iso}). Reconstructed on {reconstructed} from explicit "
        "historical vintages and immutable pre-cutoff archives retrieved from the internet; "
        "every input history and its availability bound is listed in the ledger below. "
        "Projected paths are model scenarios, not later realised outcomes.</p>")
    add(f'<p class="sub">All 24 REER (BIS broad real effective exchange rates) and 17 '
        f"ten-year yield histories use explicit ALFRED {ed.alfred_vintage.isoformat()} "
        "(Friday) vintages, including the historical revisions contained in that vintage. "
        "Later releases and the present-day statistical histories are not substituted.</p>")
    gdesc = (f"Thirteen growth inputs are OECD amplitude-adjusted composite leading indicators "
             f"from the immutable DBnomics OECD Key Economic Indicators archive "
             f"(commit {kei.proof_url.rsplit('/', 1)[-1][:12]}, committed {kei.available_by[:16]}Z)"
             if kei else "")
    if bts:
        gdesc += (f"; ten are OECD composite business-confidence percent balances from the "
                  f"business-tendency-survey archive (commit "
                  f"{bts.proof_url.rsplit('/', 1)[-1][:12]}, committed {bts.available_by[:16]}Z), "
                  "normalized to 100 plus the deviation from each series’ own pre-cutoff "
                  "average. The model scales growth by its own trailing dispersion, so this "
                  "proxy matches the amplitude-adjusted confidence index up to centring; it is "
                  "not a CLI. Norway and New Zealand confidence surveys are quarterly and are "
                  "repeated across their three reference months; the euro area uses the EA19 "
                  "aggregate as a proxy against EA20 inflation; Thailand has no growth input")
    add(f'<p class="sub">{gdesc}. Where no newer archived release is verified before the '
        "cutoff, the older observation is used and dated explicitly.</p>")
    us = ev.cpi_choice.get("US", {})
    add('<p class="sub">Inflation is headline CPI y/y from the freshest matching-definition '
        "archive per economy (BIS WS_LONG_CPI, the model-native source, wins ties; OECD "
        "consumer-price and Key-Economic-Indicator archives qualify when fresher). The UK uses "
        "CPI, not the OECD’s national CPIH series; India uses the BIS Combined CPI history, "
        "not the different OECD India index; Japan, Mexico, Chile and Thailand use BIS where "
        "the OECD archives are stale or absent. US CPI is the BLS CPI-U all-items NSA index "
        f"from the ALFRED {ed.alfred_vintage.isoformat()} vintage with a true calendar-month "
        f"year-on-year change and no filling (latest {us.get('last', '?')}). Australian and "
        "New Zealand quarterly CPI is repeated across each quarter’s three months; those "
        "points are not independent monthly releases. "
        + (("Verified original national releases published before the cutoff extend the "
            "archived history where it ends early: " + "; ".join(
                f"{_e(C[cc].name)} {x['ref']} {x['value']:g}% ({_e(x['label'])}, published "
                f"{x['released']})"
                for cc, ch in ev.cpi_choice.items() for x in ch.get("supplements", []))
            + ". They are appended only after the last archived month and never overwrite an "
              "archived value. ") if any(ch.get("supplements") for ch in ev.cpi_choice.values())
           else "")
        + "Other newer national releases that were public before the cutoff but are absent "
        "from every eligible archive are not inserted — coverage is conservative, so an older "
        "observation date does not mean no newer release existed.</p>")
    a3, a6, a12 = anc - 3, anc - 6, anc - 12
    ext_ann = [x for x in ev.extensions if x["source"].startswith("announced")]
    ext_months = sorted({x["month"] for x in ext_ann})
    add(f'<p class="sub">Completed policy training ends in {anc}. Monthly policy histories '
        f"come from the immutable DBnomics BIS WS_CBPOL archive (commit "
        f"{bpol.proof_url.rsplit('/', 1)[-1][:12] if bpol else '?'}, committed "
        f"{bpol.available_by[:16] if bpol else '?'}Z)"
        + (f"; month-end values for {', '.join(ext_months)} beyond the archived monthly rows "
           "are publicly announced targets corroborated by daily decision histories, not "
           "claimed archived BIS statistical vintages" if ext_months else "")
        + ". The current effective snapshot is the rate in force on "
        f"{ed.last_eligible_day.isoformat()}: decisions announced but not yet effective at the "
        "cutoff are excluded. Policy-change comparisons run from that snapshot to exact "
        f"completed-month anchors (3m: {a3}, 6m: {a6}, 12m: {a12}); the partial current "
        "month does not add a completed month on hold. Current-rate snapshots feed stance, "
        "context, standouts and FX; their assessed real rates (effective rate minus latest "
        "eligible CPI) are compared with unchanged monthly historical medians. Historical "
        "real rates and every curve slope keep matched observation months.</p>")
    add('<p class="sub">Policy instruments differ: US target-range midpoint, euro-area '
        "deposit facility, China one-year LPR proxy. Indicative carry is a policy-rate "
        "differential, not an executable forward quote. The curve input is the ten-year "
        "government yield minus the matched-month policy rate, not a traded 2s10s spread. OU "
        "projection horizons start at each fitted series’ last eligible observation and the "
        "cycle clock uses each economy’s latest matched growth/inflation month, so ETAs are "
        "not countdowns from the edition date. Inherited estimators operate on available "
        "observations; where documented gaps occur a step can exceed one calendar month.</p>")
    if ev.gaps:
        parts = []
        for k in sorted(ev.gaps):
            g = ev.gaps[k]
            parts.append(f"{k}: {', '.join(g) if len(g) <= 12 else ', '.join(g[:6]) + f' … {len(g) - 6} more through ' + g[-1]}")
        add('<p class="sub">Original source observations remain missing (no values are '
            "filled): " + "; ".join(_e(p) for p in parts) + ".</p>")
    add(f'<p class="sub">{BENCHMARK_NOTE.format(china=china_note(ed))}</p>')
    cn = change_in_force("CN", ed)
    if cn is not None:
        add(f'<p class="sub">Benchmark source: <a href="{_e(cn["url"])}">{_e(cn["label"])}</a>. '
            "It is public before this cutoff, so this edition uses it in place of the "
            "earlier 3% benchmark.</p>")

    # ---- observation dates table ----------------------------------------
    add("<h3>Historical observation dates</h3>")
    add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>policy</th><th>cpi</th>'
        "<th>reer</th><th>growth</th><th>y10</th><th>Matched clock month</th></tr></thead><tbody>")
    for cc, c in C.items():
        o = ev.obs.get(cc, {})
        clk = res.clocks.get(cc)
        mm = clk.history.index[-1].strftime("%Y-%m") if clk is not None else "Not available"
        add(f'<tr><td class="name">{_e(c.name)}</td><td class="num">{o.get("policy") or "–"}</td>'
            f'<td class="num">{o.get("cpi") or "–"}</td><td class="num">{o.get("reer") or "–"}</td>'
            f'<td class="num">{o.get("cli") or ("Not configured" if cc == "TH" else "–")}</td>'
            f'<td class="num">{o.get("y10") or ("Not configured" if not c.fred_10y else "–")}</td>'
            f'<td class="num">{mm}</td></tr>')
    add("</tbody></table></div>")

    # ---- effective policy and latest CPI --------------------------------
    add("<h2>Effective policy and latest published CPI</h2>")
    add('<p class="sub">Assessed real rate equals the current effective policy rate minus the '
        "latest eligible CPI reading; it is distinct from historical real-rate observations "
        "matched by reference month. “Effective since” is the first day of the current level "
        "in the daily decision history; “Evidence” states whether that level is inside the "
        "archived BIS daily series or comes from a decision announced and effective after the "
        "archive date.</p>")
    add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>Instrument</th>'
        "<th>Current policy</th><th>Effective since</th><th>Evidence</th><th>Target</th>"
        "<th>Latest CPI</th><th>Assessed real rate</th></tr></thead><tbody>")
    ann_keys = {(a["cc"], a["effective"]) for a in ev.announcements}
    tgt = targets_for(ed)
    for cc, c in C.items():
        p = ev.policy.get(cc)
        st = res.stances.get(cc)
        cpi = ev.cpi_choice.get(cc, {})
        if p is None:
            continue
        evid = ("announced decision (listed below)"
                if (cc, p.effective_since) in ann_keys
                else f"in archive (daily to {p.archive_daily_end})")
        rr = st.real_rate if st is not None else np.nan
        add(f'<tr><td class="name">{_e(c.name)}</td><td style="white-space:normal">'
            f"{_e(POLICY_INSTRUMENT.get(cc, ''))}</td>"
            f'<td class="num">{p.current:.3f}%</td><td class="num">{_e(p.effective_since)}</td>'
            f'<td>{_e(evid)}</td>'
            f'<td class="num">{tgt.get(cc, c.infl_target):.2f}%</td>'
            f'<td class="num">{cpi.get("last", "–")}: {cpi.get("last_value", float("nan")):.2f}%</td>'
            f'<td class="num">{rr:+.3f}%</td></tr>')
    add("</tbody></table></div>")

    # ---- announcements ----------------------------------------------------
    add("<h3>Policy announcements known before the cutoff</h3>")
    if ev.announcements:
        add('<ul class="standouts">')
        for a in sorted(ev.announcements, key=lambda a: a["effective"], reverse=True):
            key = f"{a['cc']}|{a['effective']}"
            s = srcs.get(key, {})
            link = (f' Original source: <a href="{_e(s["url"])}">{_e(s.get("label", s["url"]))}</a>'
                    if s.get("url") else "")
            if s.get("url2"):
                link += f'; <a href="{_e(s["url2"])}">{_e(s.get("label2", s["url2"]))}</a>'
            link += "." if link else ""
            ann = f" (announced {s['announced']})" if s.get("announced") else ""
            add(f"<li><b>{_e(a['effective'])} · {_e(C[a['cc']].name)}</b> — {_e(C[a['cc']].cb)} "
                f"decision{ann}: {_e(POLICY_INSTRUMENT.get(a['cc'], 'policy rate'))} "
                f"{a['from']:g}% → {a['to']:g}%, effective {a['effective']}, after the archived "
                f"daily series ends and before this cutoff. Used for the current effective "
                f"snapshot{' and completed month-ends' if any(x['cc'] == a['cc'] for x in ext_ann) else ''}, "
                f"separately from the archived monthly training rows.{link}</li>")
        add("</ul>")
    else:
        add('<p class="sub">None: every effective decision before the cutoff is already inside '
            "the archived daily policy series.</p>")

    # ---- inflation inputs table --------------------------------------------
    add("<h3>Inflation inputs</h3>")
    add('<div class="tablewrap"><table><thead><tr><th>Economy</th><th>Series used</th>'
        "<th>Latest reference</th><th>Value</th><th>Other candidates (latest)</th></tr></thead><tbody>")
    for cc, c in C.items():
        ch = ev.cpi_choice.get(cc)
        if not ch:
            continue
        others = "; ".join(f"{x['candidate'].split(' (')[0]} {x['last']}"
                           for x in ch["considered"] if x["candidate"] != ch["chosen"])
        add(f'<tr><td class="name">{_e(c.name)}</td><td style="white-space:normal">'
            f'{_e(ch["chosen"])}</td><td class="num">{ch["last"]}</td>'
            f'<td class="num">{ch["last_value"]:.2f}%</td>'
            f'<td style="white-space:normal">{_e(others) or "–"}</td></tr>')
    add("</tbody></table></div>")

    # ---- growth definitions --------------------------------------------------
    add("<h3>Growth input definitions</h3>")
    add('<p class="sub">' + "; ".join(
        f"{_e(C[cc].name)}: {_e(ev.growth_def[cc])}" for cc in C if cc in ev.growth_def)
        + "; Thailand: no growth input configured.</p>")

    # ---- ledger ---------------------------------------------------------------
    add("<h2>Historical source ledger</h2>")
    add('<p class="sub">Each entry: identifier (link to the exact bytes used), availability '
        "bound, SHA-256 of the retrieved bytes, and the eligibility rule. Archive commits link "
        "to their immutable commit pages.</p>")
    add('<ul style="font-size:13px;line-height:1.55">')
    for k in sorted(led, key=lambda k: (led[k].kind, k)):
        e = led[k]
        proof = (f' · <a href="{_e(e.proof_url)}">proof</a>' if e.proof_url else "")
        add(f'<li><a href="{_e(e.url)}">{_e(e.id)}</a> · available by {_e(e.available_by)} · '
            f"sha256 {e.sha256[:16]}… · {_e(e.note)}{proof}</li>")
    add("</ul>")
    return "\n".join(H)
