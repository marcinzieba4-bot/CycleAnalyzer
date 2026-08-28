"""Markdown report generator: the human-readable output of the framework."""

from __future__ import annotations

import numpy as np
from datetime import date
from pathlib import Path

from .universe import COUNTRIES
from .analysis import Results
from .models.cycle_clock import ClockReading

_PHASE_PLAY = {
    "Goldilocks": "credit-friendly: carry works, curve gently steepens, currency supported",
    "Overheating": "pre-hike: pay the front end, long the currency, flatteners",
    "Stagflation": "late-cycle: steepeners begin, currency vulnerable, own the peak-rates trade",
    "Disinflation": "easing: receive rates, bull steepeners, currency funds carry trades",
}


def _fmt(x, nd=1, suffix=""):
    return f"{x:+.{nd}f}{suffix}" if isinstance(x, (int, float)) and np.isfinite(x) else "–"


def _clock_row(cc: str, clk: ClockReading, res: Results) -> str:
    c = COUNTRIES[cc]
    eta = f"~{clk.months_to_next:.0f}m" if clk.months_to_next else "slow"
    rot = "→" if clk.omega > 0.05 else ("←" if clk.omega < -0.05 else "·")
    return (f"| {c.name} | {c.bloc} | {_fmt(clk.g)} | {_fmt(clk.i)} | "
            f"**{clk.phase}** | {rot} {clk.heading} | {eta} |")


def _danger_cell(d) -> str:
    if d is None:
        return "–"
    return {"IN THE ZONE": "🔴 in the zone", "NOT IN DANGER": "🟢 not in danger",
            "watch": "🟡 watch"}.get(d.label(), f"🟠 {d.label()}")


def _top_plays(res: Results) -> list[dict]:
    """Assemble the elaborated trade theses from the model outputs."""
    C = COUNTRIES
    plays: list[dict] = []

    # 1. Best curve trade where phase and mean reversion agree.
    agree = [s for s in res.curves if "mean reversion agrees" in s.rationale]
    best_curve = agree[0] if agree else (res.curves[0] if res.curves else None)
    if best_curve is not None:
        s = best_curve
        st = res.stances.get(s.cc)
        clk = res.clocks.get(s.cc)
        eta = (f" The clock says the phase turns in ~{clk.months_to_next:.0f} months, "
               f"so the window is now." if clk and clk.months_to_next else "")
        plays.append({
            "title": f"{C[s.cc].name} curve {s.direction} "
                     f"({'pay' if s.direction=='flattener' else 'receive'} the belly vs the wings "
                     f"or outright 10y−policy)",
            "thesis": (
                f"The {C[s.cc].name} 10y−policy slope sits at {s.slope:+.2f}pp, "
                f"{s.slope_z:+.1f}σ vs its own history, and reverts with a "
                f"{s.half_life:.0f}-month half-life — fast enough to trade. The economy "
                f"is in **{s.phase}**, which historically pushes the slope "
                f"{'flatter' if s.direction=='flattener' else 'steeper'}, and here the "
                f"mean-reversion pull points the same way: cyclical signal and "
                f"statistical stretch agree, which is the rare double-confirmation "
                f"this framework looks for.{eta} Policy stance: {C[s.cc].cb} is "
                f"{st.direction if st else '?'} "
                f"({st.d6:+.2f}pp over 6m at {st.policy:.2f}%)." if st else ""),
            "risk": (f"a growth shock flips the phase to Disinflation and the trade "
                     f"inverts; size for the {s.half_life:.0f}m half-life, not for a month."),
        })

    # 2. Best FX cross.
    if res.crosses:
        x = res.crosses[0]
        lo = next(s for s in res.fx if s.ccy == x["long"])
        sh = next(s for s in res.fx if s.ccy == x["short"])
        lo_clk, sh_clk = res.clocks.get(lo.cc), res.clocks.get(sh.cc)
        plays.append({
            "title": f"Long {x['long']} / short {x['short']}",
            "thesis": (
                f"The widest credible gap in the FX scorecard ({x['edge']:+.2f}). "
                f"{x['long']}: carry {lo.carry:+.2f}, cycle {lo.cycle:+.2f} "
                f"({lo_clk.phase if lo_clk else '?'}"
                f"{', heading ' + lo_clk.heading if lo_clk and lo_clk.months_to_next else ''}), "
                f"REER valuation {lo.valuation:+.2f}. "
                f"{x['short']}: cycle {sh.cycle:+.2f} "
                f"({sh_clk.phase if sh_clk else '?'}), valuation {sh.valuation:+.2f}, "
                f"momentum {sh.momentum:+.2f} — a funding currency whose central bank "
                f"is easing or parked while the long leg's cycle still supports rates. "
                f"You are paid {x['carry']:+.2f} of score in pure carry to hold the view."),
            "risk": ("a global risk-off compresses EM carry crosses regardless of "
                     "local cycles; the short leg rallies on safe-haven flows."),
        })

    # 3. The freshest standout signal with a direct trade expression.
    tradeable = [s for s in res.standouts
                 if s.kind in ("early_hiker", "deliberating_hike", "cutting_into_inflation")]
    if tradeable:
        s = tradeable[0]
        expr = {
            "early_hiker": "pay the front end and be long the currency — the first "
                           "hiker in an easing world gets the flow",
            "deliberating_hike": "pay the front end (the hike is not priced while the "
                                 "pack eases) and lean long the currency",
            "cutting_into_inflation": "short the currency vs a credible neighbor and "
                                      "own steepeners — easing into rising inflation "
                                      "ends with a weaker currency and a repricing",
        }[s.kind]
        plays.append({
            "title": f"The fresh signal: {C[s.cc].name}",
            "thesis": f"{s.headline}. Expression: {expr}.",
            "risk": "single-meeting risk — one CPI print or one MPC vote can void "
                    "the divergence; keep it tactical.",
        })

    # 4. Safe-cycle carry: the not-endangered economy with the best carry.
    safe = res.safe_list()
    if safe:
        cands = [s for s in res.fx if s.cc in safe]
        if cands:
            best = max(cands, key=lambda s: s.carry + s.total / 10)
            clk = res.clocks.get(best.cc)
            di = res.infl_danger.get(best.cc)
            plays.append({
                "title": f"The quiet carry: long {best.ccy}, because its cycle is not endangered",
                "thesis": (
                    f"{C[best.cc].name} is the model's cleanest 'nothing breaks here' "
                    f"story: the OU projection keeps both the inflation gap and the "
                    f"growth cycle clear of danger thresholds for the whole 36-month "
                    f"horizon{' (phase: ' + clk.phase + ')' if clk else ''}. When the "
                    f"cycle is far from endangered you are being paid carry "
                    f"({best.carry:+.2f}) without paying cycle risk — this is where "
                    f"'we are ok with credit' applies: local-currency duration and "
                    f"credit both clip coupon while the clock stands still."),
                "risk": "the safety is model-projected, not guaranteed; a supply-side "
                        "inflation shock (energy, food, FX pass-through) is exactly "
                        "what an OU model cannot see coming.",
            })

    # 5. Behind-the-curve: negative real rate with inflation above target.
    behind = [s for s in res.standouts if s.kind == "behind_curve"]
    if behind:
        s = behind[0]
        st = res.stances[s.cc]
        plays.append({
            "title": f"The reckoning trade: {C[s.cc].name} front end is mispriced",
            "thesis": (
                f"A central bank holding a negative real rate "
                f"({st.real_rate:+.1f}%) with inflation {st.infl_gap:+.1f}pp above "
                f"target and momentum {st.infl_mom:+.1f}pp/3m eventually validates "
                f"the market's fear, not its hope. Pay the front end / short "
                f"short-dated bonds; the currency is a second-order long *if* the "
                f"bank moves, a short if it keeps refusing."),
            "risk": "the bank may be right — if growth cracks first, inflation dies "
                    "on its own and paying the front end loses.",
        })

    return plays


def build_report(res: Results, charts: dict[str, Path], outdir: Path) -> str:
    C = COUNTRIES
    rel = {k: p.relative_to(outdir) if p.is_absolute() else p for k, p in charts.items()}
    L: list[str] = []
    add = L.append

    add(f"# DM + EM Cycle Monitor — {res.asof}")
    add("")
    add(f"*Generated {date.today().isoformat()} by CycleAnalyzer. Data: BIS "
        "(policy rates, CPI, REER), OECD (composite leading indicators), FRED "
        "(10y yields). All signals are model output, not investment advice.*")
    add("")
    plays = _top_plays(res)
    if plays:
        add("**At a glance — the plays (elaborated in §6):**")
        for i, p in enumerate(plays, 1):
            add(f"{i}. {p['title']}")
        add("")

    # ---------------------------------------------------------------- summary
    add("## 1. Where the world is on the clock")
    add("")
    p = res.pack
    add(f"The global pack: **{p['n_cutting']} central banks easing, "
        f"{p['n_hold']} on hold, {p['n_hiking']} hiking** — median policy move "
        f"over 6 months {p['median_d6']:+.2f}pp.")
    add("")
    counts = {}
    for clk in res.clocks.values():
        counts[clk.phase] = counts.get(clk.phase, 0) + 1
    add(" · ".join(f"**{k}**: {v}" for k, v in
                   sorted(counts.items(), key=lambda kv: -kv[1])))
    add("")
    add(f"![Cycle clock]({rel['clock']})")
    add("")
    add("| Economy | Bloc | Growth z | Infl z | Phase | Heading | ETA next |")
    add("|---|---|---|---|---|---|---|")
    order = sorted(res.clocks, key=lambda cc: (C[cc].bloc, -res.clocks[cc].theta))
    for cc in order:
        add(_clock_row(cc, res.clocks[cc], res))
    add("")
    add("*Phases rotate Goldilocks → Overheating → Stagflation → Disinflation. "
        "ETA is the model's months-to-next-quadrant at the current rotation "
        "speed; '·' or 'slow' = effectively parked.*")
    add("")

    # ---------------------------------------------------------- mean reversion
    add("## 2. Mean reversion: how stretched, how fast it snaps back")
    add("")
    add("Every cycle variable is fit as an Ornstein–Uhlenbeck process; the "
        "half-life says how quickly deviations decay, the z-score how far we "
        "are from equilibrium, and the projected path when (if ever) the "
        "**inflation-fight threshold (+1σ)** or **recession zone (−1σ)** is hit.")
    add("")
    add(f"![Distance to danger]({rel['danger']})")
    add("")
    add("| Economy | Infl level (z) | OU stretch | HL (m) | Inflation fight | Growth level (z) | Recession risk |")
    add("|---|---|---|---|---|---|---|")
    for cc in order:
        fi, fg = res.infl_fits.get(cc), res.growth_fits.get(cc)
        di, dg = res.infl_danger.get(cc), res.growth_danger.get(cc)
        add(f"| {C[cc].name} | {_fmt(fi.last) if fi else '–'} | "
            f"{_fmt(fi.z) if fi else '–'} | "
            f"{f'{fi.half_life:.0f}' if fi else '–'} | {_danger_cell(di)} | "
            f"{_fmt(fg.last) if fg else '–'} | {_danger_cell(dg)} |")
    add("")
    safe = res.safe_list()
    if safe:
        add("**Cycles NOT in danger** (model path stays clear of both thresholds "
            "over 36 months): " + ", ".join(f"**{C[cc].name}**" for cc in safe) +
            ". These are the economies where you can still be paid for the "
            "benign part of the cycle — credit and carry — without fighting "
            "the clock.")
        add("")
    if "ou" in rel:
        add(f"![OU projections]({rel['ou']})")
        add("")

    # -------------------------------------------------------------- standouts
    add("## 3. What stands out vs the global cycle")
    add("")
    add(f"![Policy stance]({rel['stance']})")
    add("")
    if res.standouts:
        for s in res.standouts[:10]:
            add(f"- **{C[s.cc].name}** — {s.headline}.")
    else:
        add("- Nothing is meaningfully out of step with the global cycle this month.")
    add("")

    # ------------------------------------------------------------------ curve
    add("## 4. Yield curves")
    add("")
    add(f"![Curve slopes]({rel['slope']})")
    add("")
    add("| Economy | Slope (pp) | z | HL (m) | Phase | Call | Why |")
    add("|---|---|---|---|---|---|---|")
    for s in res.curves:
        add(f"| {C[s.cc].name} | {s.slope:+.2f} | {_fmt(s.slope_z)} | "
            f"{s.half_life:.0f} | {s.phase} | **{s.direction}** "
            f"({'★' * s.conviction}) | {s.rationale} |")
    add("")

    # --------------------------------------------------------------------- FX
    add("## 5. FX scorecard")
    add("")
    add(f"![FX scores]({rel['fx']})")
    add("")
    add("| Ccy | Carry | Cycle | Valuation | Momentum | Penalty | **Total** |")
    add("|---|---|---|---|---|---|---|")
    for s in res.fx:
        add(f"| {s.ccy} | {_fmt(s.carry,2)} | {_fmt(s.cycle,2)} | "
            f"{_fmt(s.valuation,2)} | {_fmt(s.momentum,2)} | {_fmt(s.penalty,2)} "
            f"| **{_fmt(s.total,2)}** |")
    add("")
    if res.crosses:
        add("Model crosses (strongest long vs weakest short):")
        for x in res.crosses:
            add(f"- **Long {x['long']} / short {x['short']}** — edge "
                f"{x['edge']:+.2f}, carry differential {x['carry']:+.2f}")
    add("")

    # ---------------------------------------------------- elaborated top plays
    add("## 6. What is most interesting to play right now")
    add("")
    for i, play in enumerate(plays, 1):
        add(f"### 6.{i} {play['title']}")
        add("")
        add(play["thesis"])
        add("")
        add(f"*Risk:* {play['risk']}")
        add("")

    # ------------------------------------------------------------- playbook
    add("## 7. Phase playbook (reference)")
    add("")
    for ph, play in _PHASE_PLAY.items():
        members = [C[cc].name for cc, clk in res.clocks.items() if clk.phase == ph]
        add(f"- **{ph}** ({', '.join(members) if members else 'none'}): {play}")
    add("")

    # ------------------------------------------------------------ methodology
    add("## Appendix: methodology in one page")
    add("")
    add("- **Clock**: growth z = OECD CLI deviation from 100 scaled by 15y "
        "dispersion; inflation z = CPI y/y minus CB target scaled likewise. "
        "Phase angle θ = atan2(infl, growth); rotation speed = median monthly "
        "Δθ over 9m.")
    add("- **Mean reversion**: AR(1)/OU fit per series; expected path blends "
        "OU decay with fading 3m momentum, producing the realistic "
        "rise-then-revert hump. Danger = projected path crossing ±1σ.")
    add("- **Standouts**: 6m policy change vs universe median (robust z via "
        "MAD), real-rate gap vs own decade, inflation momentum. Labels: early "
        "hiker, cutting-into-inflation, deliberating hike, behind the curve, "
        "room to cut.")
    add("- **FX score** = carry (haircut when inflation gap eats it) + clock "
        "phase (weighted toward the heading when rotation is fast) + REER "
        "mean-reversion pull + policy momentum − credibility penalty.")
    add("- **Curve call** = 0.6 × phase implication + 0.4 × OU stretch fade, "
        "weighted by reversion speed.")
    add("")

    text = "\n".join(L)
    (outdir / "cycle_monitor.md").write_text(text)
    return text
