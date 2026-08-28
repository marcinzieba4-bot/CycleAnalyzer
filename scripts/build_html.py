#!/usr/bin/env python3
"""Render the cycle monitor as a self-contained HTML page (charts embedded)."""

import base64
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cycle_analyzer.data import load_panel               # noqa: E402
from cycle_analyzer.analysis import run, Results         # noqa: E402
from cycle_analyzer.report import _top_plays             # noqa: E402
from cycle_analyzer.universe import COUNTRIES            # noqa: E402

import numpy as np                                       # noqa: E402

CSS = """
:root {
  color-scheme: light;
  --bg: #f7f6f3; --surface: #fdfdfb; --ink: #20241f; --ink2: #5a6058;
  --muted: #8a9088; --line: #e3e2da; --accent: #0e6b5c; --accent-soft: #e3eeea;
  --hot: #b4552e; --hot-soft: #f4e5dc; --warn: #a8730a; --warn-soft: #f3ead6;
  --good: #2e7d32; --good-soft: #e2eee0; --cold: #4a6b8a; --cold-soft: #e2e9f0;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #131614; --surface: #1b1f1d; --ink: #e9e7df; --ink2: #b0b3aa;
    --muted: #7d827b; --line: #2c302d; --accent: #45a892; --accent-soft: #1d2e2a;
    --hot: #d07a52; --hot-soft: #33241c; --warn: #d3a04a; --warn-soft: #322a1a;
    --good: #66b16a; --good-soft: #1d2b1e; --cold: #7fa3c4; --cold-soft: #1d2630;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #131614; --surface: #1b1f1d; --ink: #e9e7df; --ink2: #b0b3aa;
  --muted: #7d827b; --line: #2c302d; --accent: #45a892; --accent-soft: #1d2e2a;
  --hot: #d07a52; --hot-soft: #33241c; --warn: #d3a04a; --warn-soft: #322a1a;
  --good: #66b16a; --good-soft: #1d2b1e; --cold: #7fa3c4; --cold-soft: #1d2630;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.6 "IBM Plex Sans", system-ui, sans-serif;
}
.wrap { max-width: 900px; margin: 0 auto; padding: 48px 24px 96px; }
header.masthead { border-bottom: 2px solid var(--ink); padding-bottom: 20px; margin-bottom: 8px; }
.eyebrow {
  font: 600 12px/1 "IBM Plex Mono", monospace; letter-spacing: .14em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 14px;
}
h1 {
  font: 600 clamp(30px, 5vw, 44px)/1.12 "IBM Plex Serif", Georgia, serif;
  margin: 0 0 10px; text-wrap: balance;
}
.dek { color: var(--ink2); max-width: 62ch; margin: 0; }
h2 {
  font: 600 24px/1.25 "IBM Plex Serif", Georgia, serif;
  margin: 56px 0 6px; text-wrap: balance;
}
h2 .no { color: var(--muted); font: 500 15px/1 "IBM Plex Mono", monospace; margin-right: 10px; }
.sub { color: var(--ink2); margin: 0 0 18px; max-width: 68ch; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 22px 0 6px; }
.chip {
  font: 500 13px/1 "IBM Plex Mono", monospace; padding: 7px 12px;
  border-radius: 999px; border: 1px solid var(--line); background: var(--surface);
}
.chip b { font-weight: 700; }
.chip.overheat { background: var(--hot-soft); color: var(--hot); border-color: transparent; }
.chip.goldi    { background: var(--good-soft); color: var(--good); border-color: transparent; }
.chip.stag     { background: var(--warn-soft); color: var(--warn); border-color: transparent; }
.chip.disinf   { background: var(--cold-soft); color: var(--cold); border-color: transparent; }
.chip.pack     { color: var(--ink2); }
figure { margin: 22px 0; }
figure .frame {
  background: #fcfcfb; border: 1px solid var(--line); border-radius: 6px;
  padding: 10px; overflow-x: auto;
}
figure img { display: block; max-width: 100%; height: auto; margin: 0 auto; }
figcaption { font: 400 13px/1.5 "IBM Plex Sans", sans-serif; color: var(--muted); margin-top: 8px; }
.tablewrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); margin: 18px 0; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th {
  font: 600 11.5px/1.3 "IBM Plex Mono", monospace; letter-spacing: .06em;
  text-transform: uppercase; color: var(--ink2); text-align: left;
  padding: 10px 12px; border-bottom: 1px solid var(--line);
  background: var(--surface); white-space: nowrap;
}
td {
  padding: 8px 12px; border-bottom: 1px solid var(--line); white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
tr:last-child td { border-bottom: none; }
td.num { font-family: "IBM Plex Mono", monospace; font-size: 12.5px; }
td.name { font-weight: 600; }
.tag {
  display: inline-block; font: 600 11px/1 "IBM Plex Mono", monospace;
  padding: 4px 8px; border-radius: 4px; letter-spacing: .03em;
}
.tag.overheat { background: var(--hot-soft); color: var(--hot); }
.tag.goldi    { background: var(--good-soft); color: var(--good); }
.tag.stag     { background: var(--warn-soft); color: var(--warn); }
.tag.disinf   { background: var(--cold-soft); color: var(--cold); }
.tag.zone     { background: var(--hot-soft); color: var(--hot); }
.tag.near     { background: var(--warn-soft); color: var(--warn); }
.tag.watch    { background: var(--surface); color: var(--ink2); border: 1px solid var(--line); }
.tag.safe     { background: var(--good-soft); color: var(--good); }
.tag.steep    { background: var(--cold-soft); color: var(--cold); }
.tag.flat     { background: var(--hot-soft); color: var(--hot); }
.tag.neutral  { background: var(--surface); color: var(--ink2); border: 1px solid var(--line); }
ul.standouts { padding-left: 0; list-style: none; margin: 18px 0; display: grid; gap: 10px; }
ul.standouts li {
  background: var(--surface); border: 1px solid var(--line); border-left: 3px solid var(--accent);
  border-radius: 6px; padding: 12px 16px;
}
ul.standouts li b { font-family: "IBM Plex Serif", serif; }
.plays { display: grid; gap: 18px; margin: 24px 0; }
.play {
  background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
  padding: 22px 24px;
}
.play .rank {
  font: 700 13px/1 "IBM Plex Mono", monospace; color: var(--accent);
  letter-spacing: .1em; margin-bottom: 8px;
}
.play h3 { font: 600 19px/1.3 "IBM Plex Serif", Georgia, serif; margin: 0 0 10px; text-wrap: balance; }
.play p { margin: 0 0 10px; color: var(--ink); }
.play .risk { color: var(--ink2); font-size: 14px; margin: 0; }
.play .risk b { color: var(--warn); font: 600 11.5px/1 "IBM Plex Mono", monospace; text-transform: uppercase; letter-spacing: .08em; }
.safebox {
  background: var(--good-soft); border-radius: 8px; padding: 18px 22px; margin: 20px 0;
  border: 1px solid transparent;
}
.safebox b { color: var(--good); }
.method { font-size: 14.5px; color: var(--ink2); }
.method dt { font-weight: 600; color: var(--ink); font-family: "IBM Plex Mono", monospace; font-size: 12.5px; text-transform: uppercase; letter-spacing: .06em; margin-top: 12px; }
.method dd { margin: 4px 0 0; }
footer { margin-top: 64px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }
a { color: var(--accent); }
"""

PHASE_CLS = {"Overheating": "overheat", "Goldilocks": "goldi",
             "Stagflation": "stag", "Disinflation": "disinf"}


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def img(path: Path, alt: str, caption: str) -> str:
    return (f'<figure><div class="frame"><img alt="{alt}" '
            f'src="data:image/png;base64,{b64(path)}"></div>'
            f'<figcaption>{caption}</figcaption></figure>')


def fmt(x, nd=1):
    return f"{x:+.{nd}f}" if isinstance(x, (int, float)) and np.isfinite(x) else "–"


def danger_tag(d):
    if d is None:
        return '<span class="tag neutral">–</span>'
    lbl = d.label()
    if lbl == "IN THE ZONE":
        return '<span class="tag zone">in the zone</span>'
    if lbl == "NOT IN DANGER":
        return '<span class="tag safe">not in danger</span>'
    if lbl == "watch":
        return '<span class="tag watch">watch</span>'
    return f'<span class="tag near">{lbl}</span>'


def build(res: Results, charts_dir: Path, out: Path) -> None:
    C = COUNTRIES
    plays = _top_plays(res)
    H: list[str] = []
    add = H.append

    add(f"<title>DM+EM Cycle Monitor</title>")
    add('<link rel="preconnect" href="https://fonts.googleapis.com">')
    add('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Sans:wght@400;600&'
        'family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">')
    add(f"<style>{CSS}</style>")
    add('<div class="wrap">')

    # masthead
    add('<header class="masthead">')
    add(f'<div class="eyebrow">CycleAnalyzer · data through {res.asof} · '
        f'generated {date.today().isoformat()}</div>')
    add("<h1>DM+EM Cycle Monitor</h1>")
    add('<p class="dek">Twenty-four economies read as mean-reverting cycles: where each one '
        "sits on the growth × inflation clock, what comes next and when, which cycles are "
        "not endangered, who stands apart from the global pack — and what all of it says "
        "to play in FX and yield curves.</p>")
    add("</header>")

    counts = {}
    for clk in res.clocks.values():
        counts[clk.phase] = counts.get(clk.phase, 0) + 1
    p = res.pack
    add('<div class="chips">')
    for ph in ("Overheating", "Stagflation", "Goldilocks", "Disinflation"):
        if counts.get(ph):
            add(f'<span class="chip {PHASE_CLS[ph]}"><b>{counts[ph]}</b> {ph.lower()}</span>')
    add(f'<span class="chip pack">{p["n_hiking"]} hiking · {p["n_hold"]} on hold · '
        f'{p["n_cutting"]} cutting</span>')
    add("</div>")

    # section 1: clock
    add('<h2><span class="no">01</span>Where the world is on the clock</h2>')
    add('<p class="sub">Growth (leading indicator) on the x-axis, inflation gap vs each '
        "central bank's target on the y-axis, both scaled by the economy's own history. "
        "Cycles rotate counter-clockwise: Goldilocks → Overheating → Stagflation → "
        "Disinflation. The rotation speed gives the ETA to the next phase.</p>")
    add(img(charts_dir / "clock.png", "Cycle clock scatter",
            "Trails show the last 6 months. The crowd in the upper-right — the heated, "
            "credit-friendly zone where the inflation fight comes next — is the story of this print."))
    add('<div class="tablewrap"><table><thead><tr>'
        "<th>Economy</th><th>Bloc</th><th>Growth z</th><th>Infl z</th>"
        "<th>Phase</th><th>Heading</th><th>ETA</th></tr></thead><tbody>")
    order = sorted(res.clocks, key=lambda cc: (C[cc].bloc, -res.clocks[cc].theta))
    for cc in order:
        clk = res.clocks[cc]
        eta = f"~{clk.months_to_next:.0f}m" if clk.months_to_next else "slow"
        arrow = "→" if clk.omega > 0.05 else ("←" if clk.omega < -0.05 else "·")
        add(f'<tr><td class="name">{C[cc].name}</td><td>{C[cc].bloc}</td>'
            f'<td class="num">{fmt(clk.g)}</td><td class="num">{fmt(clk.i)}</td>'
            f'<td><span class="tag {PHASE_CLS[clk.phase]}">{clk.phase}</span></td>'
            f'<td>{arrow} {clk.heading}</td><td class="num">{eta}</td></tr>')
    add("</tbody></table></div>")

    # section 2: mean reversion
    add('<h2><span class="no">02</span>Mean reversion &amp; distance to danger</h2>')
    add('<p class="sub">Each cycle variable is fit as an Ornstein–Uhlenbeck process. The '
        "projected path (OU decay plus fading momentum) is tested against two thresholds: "
        "the <b>inflation-fight line</b> (+1σ) and the <b>recession zone</b> (−1σ). "
        "An economy whose path never gets near either is flagged "
        "<b>not in danger</b> — the cycle has far to run before it is endangered.</p>")
    add(img(charts_dir / "danger.png", "Distance to inflation fight",
            "Dot = current inflation gap (z); arrow = model path 12 months out. "
            "Green cycles are not endangered; red are already in the fight."))
    add('<div class="tablewrap"><table><thead><tr>'
        "<th>Economy</th><th>Infl level</th><th>OU stretch</th><th>Half-life</th>"
        "<th>Inflation fight</th><th>Growth level</th><th>Recession risk</th></tr></thead><tbody>")
    for cc in order:
        fi, fg = res.infl_fits.get(cc), res.growth_fits.get(cc)
        di, dg = res.infl_danger.get(cc), res.growth_danger.get(cc)
        add(f'<tr><td class="name">{C[cc].name}</td>'
            f'<td class="num">{fmt(fi.last) if fi else "–"}</td>'
            f'<td class="num">{fmt(fi.z) if fi else "–"}</td>'
            f'<td class="num">{f"{fi.half_life:.0f}m" if fi else "–"}</td>'
            f"<td>{danger_tag(di)}</td>"
            f'<td class="num">{fmt(fg.last) if fg else "–"}</td>'
            f"<td>{danger_tag(dg)}</td></tr>")
    add("</tbody></table></div>")
    safe = res.safe_list()
    if safe:
        add('<div class="safebox"><b>Cycles not in danger:</b> '
            + ", ".join(C[cc].name for cc in safe)
            + ". The model path stays clear of both thresholds for the full 36-month "
              "horizon. These are the places to be paid for the benign part of the "
              "cycle — carry and credit — without fighting the clock.</div>")
    ou = charts_dir / "ou.png"
    if ou.exists():
        add(img(ou, "OU projections",
                "The four most actionable inflation gaps: stretched and fast-reverting. "
                "Blue = history, orange dash = OU projection, red dots = the fight line."))

    # section 3: standouts
    add('<h2><span class="no">03</span>What stands out vs the global cycle</h2>')
    add('<p class="sub">Divergence is the signal: the first hiker in an easing world, the '
        "bank deliberating a hike while the pack is neutral, the one cutting into rising "
        "inflation. Each stance is scored against the universe median.</p>")
    add(img(charts_dir / "stance.png", "Policy stance divergence",
            "Policy-rate change over 6 months. ▲ marks inflation re-accelerating "
            "(3-month momentum above +0.3pp)."))
    add('<ul class="standouts">')
    for s in res.standouts[:10]:
        add(f"<li><b>{C[s.cc].name}</b> — {s.headline}.</li>")
    add("</ul>")

    # section 4: curves
    add('<h2><span class="no">04</span>Yield curves</h2>')
    add('<p class="sub">Slope = 10y − policy. The call combines what the phase implies '
        "(overheating flattens, disinflation steepens) with the OU stretch of the slope "
        "against its own history; stars mark conviction, and phase + mean reversion "
        "agreeing is the double-confirmation worth acting on.</p>")
    add(img(charts_dir / "slope.png", "Curve slopes",
            "Slope z-scores vs own history, colored by the model's call."))
    add('<div class="tablewrap"><table><thead><tr>'
        "<th>Economy</th><th>Slope</th><th>z</th><th>HL</th><th>Phase</th>"
        "<th>Call</th><th>Why</th></tr></thead><tbody>")
    for s in res.curves:
        cls = {"steepener": "steep", "flattener": "flat", "neutral": "neutral"}[s.direction]
        add(f'<tr><td class="name">{C[s.cc].name}</td>'
            f'<td class="num">{s.slope:+.2f}pp</td><td class="num">{fmt(s.slope_z)}</td>'
            f'<td class="num">{s.half_life:.0f}m</td><td>{s.phase}</td>'
            f'<td><span class="tag {cls}">{s.direction} {"★" * s.conviction}</span></td>'
            f'<td style="white-space:normal;min-width:260px">{s.rationale}</td></tr>')
    add("</tbody></table></div>")

    # section 5: FX
    add('<h2><span class="no">05</span>FX scorecard</h2>')
    add('<p class="sub">Score vs USD = carry (haircut when inflation eats it) + cycle '
        "phase (weighted toward the heading when rotation is fast) + REER valuation "
        "(mean-reversion pull) + policy momentum − credibility penalty.</p>")
    add(img(charts_dir / "fx.png", "FX scorecard",
            "Stacked decomposition; the diamond is the total."))
    if res.crosses:
        add("<p><b>Model crosses</b> — strongest longs against the weakest "
            "<i>credible</i> funders (a broken-credibility high-carry currency is "
            "excluded from the short leg: shorting 30–40% carry is a bleed, not a hedge):</p><ul>")
        for x in res.crosses:
            add(f"<li><b>Long {x['long']} / short {x['short']}</b> — edge {x['edge']:+.2f}, "
                f"carry differential {x['carry']:+.2f}</li>")
        add("</ul>")

    # section 6: plays
    add('<h2><span class="no">06</span>What is most interesting to play</h2>')
    add('<p class="sub">Ranked by how many independent signals agree.</p>')
    add('<div class="plays">')
    for i, play in enumerate(plays, 1):
        add(f'<div class="play"><div class="rank">PLAY {i}</div>'
            f'<h3>{play["title"]}</h3><p>{play["thesis"]}</p>'
            f'<p class="risk"><b>Risk</b> — {play["risk"]}</p></div>')
    add("</div>")

    # methodology
    add('<h2><span class="no">07</span>Methodology</h2>')
    add('<dl class="method">')
    add("<dt>Clock</dt><dd>Growth z = OECD composite leading indicator's deviation from 100, "
        "scaled by 15y dispersion. Inflation z = CPI y/y minus the central-bank target, scaled "
        "likewise. Phase angle θ = atan2(infl, growth); rotation = median monthly Δθ over 9m.</dd>")
    add("<dt>Mean reversion</dt><dd>AR(1)/OU fit per series; expected path blends OU decay "
        "with fading 3-month momentum (the realistic rise-then-revert hump). Danger = the "
        "projected path crossing +1σ (inflation) or −1σ (growth); safe requires staying "
        "0.6σ clear for 36 months.</dd>")
    add("<dt>Standouts</dt><dd>6m policy change vs universe median (robust MAD z), real-rate "
        "gap vs own decade, 3m inflation momentum → early hiker, deliberating hike, cutting "
        "into inflation, behind the curve, room to cut.</dd>")
    add("<dt>Data</dt><dd>BIS (policy rates, CPI y/y, broad REER — all 24 economies, "
        f"through {res.asof}), OECD CLI via DBnomics (23), FRED 10y yields (17). Cached in "
        "the repository for reproducibility.</dd>")
    add("</dl>")

    add("<footer>Model output from the CycleAnalyzer framework — not investment advice. "
        "Sources: BIS, OECD, FRED. All z-scores are vs each economy's own history, which is "
        "what makes chronic-high-inflation regimes comparable to low-inflation ones.</footer>")
    add("</div>")

    out.write_text("\n".join(H))
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    res = run(load_panel(verbose=False))
    root = Path(__file__).resolve().parent.parent
    build(res, root / "reports" / "charts", root / "reports" / "cycle_monitor.html")
