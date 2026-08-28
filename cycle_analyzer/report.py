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


def _ctx_line(v) -> str:
    """One-sentence context-check narrative from a ContextVerdict."""
    if v is None or v.verdict == "NONE":
        return "no meaningful stretch — this leg is not a mean-reversion bet."
    state = ("already turning, {:.0%} retraced".format(v.retraced) if v.turning
             else "still pinned at the extreme")
    return (f"stretch {v.z:+.1f}σ, {state}; context score {v.context:+.2f} → "
            f"**{v.verdict}**: {v.note}.")


def _momentum_ctx(res: Results, cc: str) -> str:
    """Context line for divergence plays: these are momentum trades, so the
    check is the danger model, not a stretch."""
    st = res.stances.get(cc)
    d = res.infl_danger.get(cc)
    if d is None or st is None:
        return "this is a divergence trade, not a fade — no stretch required."
    if d.breached:
        where = "already inside the inflation-fight zone"
    elif d.months_to_cross is not None:
        where = f"the OU path crosses the fight line in ~{d.months_to_cross:.0f} months"
    else:
        where = "the fight line is not yet threatened"
    return (f"this is a divergence/momentum trade, not a fade: {where}, with "
            f"inflation momentum {st.infl_mom:+.1f}pp over 3m — the context is "
            f"moving *with* the position, which is what the filter requires when "
            f"there is no extreme to revert.")


def _top_plays(res: Results) -> list[dict]:
    """Assemble the elaborated trade theses from the model outputs."""
    C = COUNTRIES
    plays: list[dict] = []

    # 1. Best curve trade — chosen by the context filter, not by raw stretch:
    #    EARLY_TURN beats SETUP beats everything; TREND_INTACT is never picked.
    v_rank = {"EARLY_TURN": 0, "SETUP": 1, "NONE": 2, "WATCH": 2, "LATE": 3,
              "TREND_INTACT": 4}
    ranked = sorted((s for s in res.curves if s.direction != "neutral"),
                    key=lambda s: (v_rank.get(s.context_verdict, 2),
                                   -s.conviction, -abs(s.slope_z)))
    best_curve = ranked[0] if ranked else None
    if best_curve is not None and v_rank.get(best_curve.context_verdict, 2) <= 2:
        s = best_curve
        st = res.stances.get(s.cc)
        clk = res.clocks.get(s.cc)
        v = res.slope_ctx.get(s.cc) if res.slope_ctx else None
        move = "flatter" if s.direction == "flattener" else "steeper"
        moving = "flattening" if s.direction == "flattener" else "steepening"
        bits = [
            f"The {C[s.cc].name} 10y−policy slope sits at {s.slope:+.2f}pp "
            f"({s.slope_z:+.1f}σ vs its own history, half-life "
            f"{s.half_life:.0f}m). The economy is in **{s.phase}**, which pushes "
            f"the slope {move}"]
        if st is not None and st.direction != "on hold":
            bits.append(
                f", and {C[s.cc].cb} is {st.direction} ({st.d6:+.2f}pp over 6m at "
                f"{st.policy:.2f}%) — policy moves hit the front end first, which "
                f"is exactly the {moving} force")
        bits.append(". ")
        if v is not None and v.verdict == "EARLY_TURN":
            bits.append(
                f"Crucially, the move has *already started* but only "
                f"{v.retraced:.0%} of the extreme is retraced — you are not "
                f"calling the turn, the turn is in, and the context says the rest "
                f"is coming. ")
        elif v is not None and v.verdict == "SETUP":
            bits.append(
                "The slope itself has not moved yet, but the leading context is "
                "breaking against it — this is the position-before-it-prints "
                "entry. ")
        if clk and clk.months_to_next and clk.months_to_next <= 12:
            bits.append(f"The clock turns phase in ~{clk.months_to_next:.0f} "
                        f"months, so the window is now. ")
        # Contrast: the most stretched slope the filter REJECTED.
        rejected = [c for c in res.curves if c.context_verdict == "TREND_INTACT"]
        if rejected:
            r = max(rejected, key=lambda c: abs(c.slope_z))
            r_st = res.stances.get(r.cc)
            feed = (f"{C[r.cc].cb} is still {r_st.direction}, which keeps feeding "
                    f"the {'steepness' if r.slope_z > 0 else 'flatness'}"
                    if r_st else "the cycle still feeds the extreme")
            bits.append(
                f"Why not {C[r.cc].name}, whose slope is more stretched "
                f"({r.slope_z:+.1f}σ)? Because its stretch is TREND INTACT — "
                f"{feed} — and a confirmed trend is precisely the extreme this "
                f"framework refuses to fade on statistics alone.")
        plays.append({
            "title": f"{C[s.cc].name} curve {s.direction}",
            "thesis": "".join(bits),
            "expression": s.expression,
            "context": _ctx_line(v),
            "risk": (f"a growth shock flips the phase to Disinflation and the trade "
                     f"inverts; size for the {s.half_life:.0f}m half-life, not for a month."),
        })

    # 2. Best FX cross.
    if res.crosses:
        x = res.crosses[0]
        lo = next(s for s in res.fx if s.ccy == x["long"])
        sh = next(s for s in res.fx if s.ccy == x["short"])
        lo_clk, sh_clk = res.clocks.get(lo.cc), res.clocks.get(sh.cc)
        lo_v = res.reer_ctx.get(lo.cc) if res.reer_ctx else None
        sh_v = res.reer_ctx.get(sh.cc) if res.reer_ctx else None
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
                f"Why the cross and not two USD legs: pairing them nets out the "
                f"dollar, so the position is a pure relative-cycle bet with the carry "
                f"differential on your side."),
            "expression": x["expression"],
            "context": (f"long leg REER: {_ctx_line(lo_v)} Short leg REER: "
                        f"{_ctx_line(sh_v)}"),
            "risk": ("a global risk-off compresses EM carry crosses regardless of "
                     "local cycles; the short leg rallies on safe-haven flows."),
        })

    # 3. The freshest standout signal with a direct trade expression.
    tradeable = [s for s in res.standouts
                 if s.kind in ("early_hiker", "deliberating_hike", "cutting_into_inflation")]
    if tradeable:
        s = tradeable[0]
        ccy = C[s.cc].ccy
        expr = {
            "early_hiker": f"pay 1y–2y {ccy} swaps (short the front end) and buy "
                           f"{ccy} vs USD via 3m forwards — the first hiker in an "
                           f"easing world gets both the rate repricing and the flow",
            "deliberating_hike": f"pay 1y–2y {ccy} swaps — the hike is not priced "
                                 f"while the pack is neutral — and lean long {ccy} "
                                 f"vs USD via 3m forwards as the second leg",
            "cutting_into_inflation": f"sell {ccy} vs a credible regional peer via "
                                      f"forwards and put on a 2s10s steepener — "
                                      f"easing into rising inflation ends with a "
                                      f"weaker currency and a front-end repricing",
        }[s.kind]
        plays.append({
            "title": f"The fresh signal: {C[s.cc].name}",
            "thesis": (
                f"{s.headline}. This is the 'one fresh signal' class of trade: the "
                f"market prices the pack, not the outlier, so the repricing when the "
                f"outlier confirms is asymmetric — small loss if it stays parked, "
                f"large gain if it moves."),
            "expression": expr,
            "context": _momentum_ctx(res, s.cc),
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
            st = res.stances.get(best.cc)
            us = res.stances.get("US")
            pickup = (f"{st.policy - us.policy:+.1f}pp over USD"
                      if st and us else "the policy differential")
            plays.append({
                "title": f"The quiet carry: long {best.ccy}, because its cycle is not endangered",
                "thesis": (
                    f"{C[best.cc].name} is the model's cleanest 'nothing breaks here' "
                    f"story: the OU projection keeps both the inflation gap and the "
                    f"growth cycle clear of danger thresholds for the whole 36-month "
                    f"horizon{' (phase: ' + clk.phase + ')' if clk else ''}. When the "
                    f"cycle is far from endangered you are being paid carry without "
                    f"paying cycle risk — this is where 'we are ok with credit' "
                    f"applies: local-currency duration and credit both clip coupon "
                    f"while the clock stands still."),
                "expression": (
                    f"long {best.ccy} vs USD via rolled 3m forwards (carry ≈ {pickup}), "
                    f"and/or unhedged local-currency 2–5y government bonds — the belly, "
                    f"not the long end, so the position is carry, not a duration view"),
                "context": _ctx_line(res.reer_ctx.get(best.cc) if res.reer_ctx else None),
                "risk": "the safety is model-projected, not guaranteed; a supply-side "
                        "inflation shock (energy, food, FX pass-through) is exactly "
                        "what an OU model cannot see coming.",
            })

    # 5. Behind-the-curve: negative real rate with inflation above target.
    behind = [s for s in res.standouts if s.kind == "behind_curve"]
    if behind:
        s = behind[0]
        st = res.stances[s.cc]
        ccy = C[s.cc].ccy
        same_story = (
            f" Note this is the same macro story as the curve trade above: the "
            f"2s10s {best_curve.direction} is the DV01-neutral version, paying 2y "
            f"outright is the directional version — run one or the other, sized "
            f"once, not both at full size."
            if best_curve is not None and best_curve.cc == s.cc else "")
        plays.append({
            "title": f"The reckoning trade: {C[s.cc].name} front end is mispriced",
            "thesis": (
                f"A central bank holding a negative real rate "
                f"({st.real_rate:+.1f}%) with inflation {st.infl_gap:+.1f}pp above "
                f"target and momentum {st.infl_mom:+.1f}pp/3m eventually validates "
                f"the market's fear, not its hope. The trade is in the front end, "
                f"not the currency: {ccy} is a second-order long *if* the bank "
                f"moves, a short if it keeps refusing — so let rates carry the "
                f"view.{same_story}"),
            "expression": (f"pay 2y {ccy} swap (or short 2y govvies / front-end "
                           f"futures); keep duration elsewhere until the front end "
                           f"reprices the hikes"),
            "context": _momentum_ctx(res, s.cc),
            "risk": "the bank may be right — if growth cracks first, inflation dies "
                    "on its own and paying the front end loses.",
        })

    return plays


def _all_verdicts(res: Results) -> list:
    """Every non-NONE context verdict across the three families, ranked."""
    rank = {"EARLY_TURN": 0, "SETUP": 1, "TREND_INTACT": 2, "WATCH": 3, "LATE": 4}
    out = []
    for fam, d in (("inflation", res.infl_ctx), ("slope", res.slope_ctx),
                   ("reer", res.reer_ctx)):
        for v in (d or {}).values():
            if v.verdict != "NONE":
                out.append(v)
    out.sort(key=lambda v: (rank.get(v.verdict, 9), -abs(v.z)))
    return out


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
        add("**At a glance — the plays (elaborated in §7):**")
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

    # --------------------------------------------------------- context filter
    add("## 3. The context filter: which extremes to fade — and which to leave alone")
    add("")
    add("**Mean reversion alone is a bad idea.** A z-score says a variable is far "
        "from equilibrium; it says nothing about whether the forces that created "
        "the extreme are done. Every stretched variable is therefore cross-examined "
        "against the *prevailing context* — leading growth momentum, the policy "
        "direction, real-rate restrictiveness, the clock heading — and against its "
        "own turn evidence, and only then classified:")
    add("")
    add("- **EARLY TURN** — the correction has begun but has retraced only a "
        "fraction of the extreme, *and* the context says the cycle change is "
        "coming anyway. This is the best entry: you are not calling the top, "
        "the top is already in, and you are riding the rest of the reversion.")
    add("- **SETUP** — the series itself is still pinned at the extreme, but the "
        "leading indicators are deteriorating hard from the top. The "
        "counter-movement has not printed yet — position before it does.")
    add("- **TREND INTACT** — stretched, but the context still *feeds* the "
        "deviation (an early hiking cycle behind a rich currency, accelerating "
        "growth behind a hot inflation gap). **Do not fade.** The extreme can "
        "get more extreme; the statistical pull earns zero weight in the trade "
        "models until the context breaks.")
    add("- **LATE** — the reversion has mostly happened; the edge is gone.")
    add("")
    if "context" in rel:
        add(f"![Context filter map]({rel['context']})")
        add("")
    verdicts = _all_verdicts(res)
    if verdicts:
        add("| Economy | Variable | Stretch | Turning? | Retraced | Context | Verdict |")
        add("|---|---|---|---|---|---|---|")
        fam_label = {"inflation": "inflation gap", "slope": "curve slope", "reer": "REER"}
        for v in verdicts:
            add(f"| {C[v.cc].name} | {fam_label[v.family]} | {_fmt(v.z)}σ | "
                f"{'yes' if v.turning else 'no'} | {v.retraced:.0%} | "
                f"{v.context:+.2f} | **{v.verdict.replace('_', ' ')}** |")
        add("")
        add("*Context > 0 means the surrounding cycle pushes the variable back "
            "toward its mean; < 0 means the context still supports the extreme. "
            "Retraced = how much of the last 12 months' peak deviation is already "
            "unwound — early turns (< 40%) are entries, late ones are exits.*")
        add("")

    # -------------------------------------------------------------- standouts
    add("## 4. What stands out vs the global cycle")
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
    add("## 5. Yield curves")
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
    add("## 6. FX scorecard")
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
        add("Model crosses (strongest long vs weakest *credible* funder):")
        for x in res.crosses:
            add(f"- **Long {x['long']} / short {x['short']}** — edge "
                f"{x['edge']:+.2f}. {x['expression']}")
    add("")

    # ---------------------------------------------------- elaborated top plays
    add("## 7. What is most interesting to play right now")
    add("")
    for i, play in enumerate(plays, 1):
        add(f"### 7.{i} {play['title']}")
        add("")
        add(play["thesis"])
        add("")
        if play.get("expression"):
            add(f"**How to express it:** {play['expression']}.")
            add("")
        if play.get("context"):
            add(f"**Context check:** {play['context']}")
            add("")
        add(f"*Risk:* {play['risk']}")
        add("")

    # ------------------------------------------------------------- playbook
    add("## 8. Phase playbook (reference)")
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
    add("- **Context filter**: every |z| ≥ 0.75 stretch is cross-examined: turn "
        "evidence (3m drift back toward the mean, share of the 12m peak already "
        "retraced) and a context score built from leading-growth momentum, "
        "real-rate restrictiveness, policy direction and the clock heading. "
        "Verdicts gate the mean-reversion terms in the trade models: "
        "TREND INTACT zeroes them, EARLY TURN boosts them.")
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
