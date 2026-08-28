"""Report charts (matplotlib, static PNG, light surface).

Palette follows the validated reference instance of the dataviz method:
categorical slots in fixed order (blue, orange, aqua, yellow, magenta),
diverging blue<->red with a neutral gray midpoint, reserved status colors,
recessive grid/axes, thin marks, selective direct labels, one axis.
"""

from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from .universe import COUNTRIES
from .analysis import Results, INFL_DANGER_Z
from .models.mean_reversion import expected_path

# ---- palette (reference instance, light mode) ------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASE = "#c3c2b7"
S1_BLUE = "#2a78d6"     # slot 1 — DM / first series
S2_ORANGE = "#eb6834"   # slot 2 — EM / second series
S3_AQUA = "#1baf7a"
S4_YELLOW = "#eda100"
S5_MAGENTA = "#e87ba4"
DIV_POS = "#d03b3b"     # diverging warm pole (tightening / hot)
DIV_NEG = "#2a78d6"     # diverging cool pole (easing / cold)
DIV_MID = "#f0efec"
ST_GOOD = "#0ca30c"
ST_WARN = "#fab219"
ST_SERIOUS = "#ec835a"
ST_CRIT = "#d03b3b"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "font.family": "DejaVu Sans",
    "text.color": INK, "axes.edgecolor": BASE, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.7, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10,
})


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ 1. clock

def clock_chart(res: Results, path: Path, trail: int = 6):
    fig, ax = plt.subplots(figsize=(8.6, 7.2))
    lim = 3.2
    # quadrant washes, barely-there
    ax.axhspan(0, lim, xmin=0.5, xmax=1, color="#fbeae4", alpha=0.55, zorder=0)
    ax.axhspan(0, -lim, xmin=0.5, xmax=1, color="#e7f0fb", alpha=0.55, zorder=0)
    ax.axhspan(0, lim, xmin=0, xmax=0.5, color="#f5efe2", alpha=0.55, zorder=0)
    ax.axhspan(0, -lim, xmin=0, xmax=0.5, color="#e9f4ee", alpha=0.45, zorder=0)
    ax.axhline(0, color=BASE, lw=1); ax.axvline(0, color=BASE, lw=1)

    kw = dict(fontsize=11, color=INK2, alpha=0.85, weight="bold", ha="center")
    ax.text(lim * 0.55, lim * 0.92, "OVERHEATING", **kw)
    ax.text(lim * 0.55, -lim * 0.97, "GOLDILOCKS / RECOVERY", **kw)
    ax.text(-lim * 0.55, lim * 0.92, "STAGFLATION / SLOWDOWN", **kw)
    ax.text(-lim * 0.55, -lim * 0.97, "DISINFLATION / EASING", **kw)

    for cc, clk in res.clocks.items():
        c = COUNTRIES[cc]
        col = S1_BLUE if c.bloc == "DM" else S2_ORANGE
        h = clk.history.tail(trail + 1)
        ax.plot(h["g"], h["i"], color=col, lw=1.2, alpha=0.45, zorder=2)
        ax.scatter([clk.g], [clk.i], s=52, color=col, zorder=3,
                   edgecolors=SURFACE, linewidths=1.4)
        ax.annotate(cc, (clk.g, clk.i), textcoords="offset points",
                    xytext=(6, 5), fontsize=8.5, color=INK, weight="bold")

    ax.scatter([], [], s=52, color=S1_BLUE, label="Developed markets")
    ax.scatter([], [], s=52, color=S2_ORANGE, label="Emerging markets")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_xlabel("Growth cycle (leading-indicator z-score)")
    ax.set_ylabel("Inflation gap vs target (z-score)")
    ax.set_title(f"The cycle clock — {res.asof} (trail = last {trail} months; "
                 "economies rotate counter-clockwise)", fontsize=11, color=INK)
    _save(fig, path)


# ------------------------------------------------- 2. policy stance divergence

def stance_chart(res: Results, path: Path):
    rows = [(cc, s.d6) for cc, s in res.stances.items() if np.isfinite(s.d6)]
    rows.sort(key=lambda r: r[1])
    ccs = [r[0] for r in rows]; vals = [r[1] for r in rows]
    med = float(np.median(vals))
    fig, ax = plt.subplots(figsize=(9.4, 5.6))
    cols = [DIV_POS if v > 0.01 else DIV_NEG if v < -0.01 else DIV_MID for v in vals]
    ax.bar(range(len(ccs)), vals, color=cols, width=0.72, zorder=2)
    ax.axhline(med, color=INK2, lw=1.2, ls="--", zorder=3)
    ax.text(len(ccs) - 0.4, med, f"  global median {med:+.2f}pp",
            fontsize=8.5, color=INK2, va="bottom", ha="right")
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(range(len(ccs)))
    ax.set_xticklabels(ccs, fontsize=8.5)
    for i, (cc, v) in enumerate(rows):
        st = res.stances[cc]
        if st.infl_mom > 0.3:  # inflation re-accelerating marker
            ax.annotate("▲", (i, v), textcoords="offset points",
                        xytext=(0, 6 if v >= 0 else -14), ha="center",
                        fontsize=7.5, color=ST_SERIOUS)
    ax.set_ylabel("Policy-rate change, last 6 months (pp)")
    ax.set_title("Who is hiking, who is cutting — red = tighter, blue = easier; "
                 "▲ = inflation re-accelerating (3m momentum > +0.3pp)",
                 fontsize=10.5, color=INK)
    _save(fig, path)


# --------------------------------------------- 3. inflation danger / distance

def danger_chart(res: Results, path: Path):
    rows = []
    for cc, f in res.infl_fits.items():
        d = res.infl_danger.get(cc)
        if d is None:
            continue
        proj = expected_path(f, 12)[-1]
        rows.append((cc, f.last, proj, d))
    rows.sort(key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(9.4, 6.2))
    for i, (cc, now, proj, d) in enumerate(rows):
        col = (ST_CRIT if d.breached else
               ST_SERIOUS if d.months_to_cross is not None else
               ST_GOOD if d.safe else ST_WARN)
        ax.plot([now, proj], [i, i], color=col, lw=2, alpha=0.8, zorder=2,
                solid_capstyle="round")
        ax.scatter([now], [i], s=42, color=col, zorder=3,
                   edgecolors=SURFACE, linewidths=1.2)
        ax.scatter([proj], [i], s=30, color=col, zorder=3, marker=">",
                   edgecolors=SURFACE, linewidths=0.8)
    ax.axvline(INFL_DANGER_Z, color=ST_CRIT, lw=1.2, ls="--", alpha=0.8)
    ax.text(INFL_DANGER_Z, len(rows) - 0.2, " inflation-fight threshold (+1σ)",
            color=ST_CRIT, fontsize=8.5, va="top")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=8.5)
    ax.set_xlabel("Inflation gap (z)  —  dot = now, arrow = model path in 12m")
    ax.set_title("Distance to the inflation fight — green = cycle not endangered, "
                 "amber = watch, orange = closing in, red = already in the zone",
                 fontsize=10.5, color=INK)
    _save(fig, path)


# ------------------------------------------------------------ 4. curve slopes

def slope_chart(res: Results, path: Path):
    rows = [(s.cc, s.slope_z, s.direction) for s in res.curves]
    rows.sort(key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    cols = {"steepener": S3_AQUA, "flattener": S5_MAGENTA, "neutral": DIV_MID}
    ax.bar(range(len(rows)), [r[1] for r in rows],
           color=[cols[r[2]] for r in rows], width=0.72, zorder=2)
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([r[0] for r in rows], fontsize=8.5)
    ax.set_ylabel("Curve slope 10y − policy, z vs own history")
    handles = [plt.Rectangle((0, 0), 1, 1, color=cols[k]) for k in
               ("steepener", "flattener", "neutral")]
    ax.legend(handles, ["model says steepener", "model says flattener", "neutral"],
              frameon=False, fontsize=9, loc="upper left")
    ax.set_title("Yield curves: stretch vs own history, colored by model call",
                 fontsize=10.5, color=INK)
    _save(fig, path)


# ------------------------------------------------------------------ 5. FX bars

def fx_chart(res: Results, path: Path):
    scores = res.fx
    fig, ax = plt.subplots(figsize=(9.8, 5.8))
    comps = [("carry", S1_BLUE), ("cycle", S2_ORANGE), ("valuation", S3_AQUA),
             ("momentum", S4_YELLOW), ("penalty", S5_MAGENTA)]
    x = np.arange(len(scores))
    pos = np.zeros(len(scores)); neg = np.zeros(len(scores))
    for name, col in comps:
        vals = np.array([getattr(s, name) for s in scores])
        base = np.where(vals >= 0, pos, neg)
        ax.bar(x, vals, bottom=base, color=col, width=0.7, zorder=2,
               label=name, edgecolor=SURFACE, linewidth=0.8)
        pos = np.where(vals >= 0, pos + vals, pos)
        neg = np.where(vals < 0, neg + vals, neg)
    ax.scatter(x, [s.total for s in scores], s=40, color=INK, zorder=4,
               marker="D", label="total score")
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels([s.ccy for s in scores], fontsize=8.5)
    ax.legend(frameon=False, fontsize=9, ncol=6, loc="lower left")
    ax.set_ylabel("FX score vs USD (decomposed)")
    ax.set_title("FX scorecard — carry + cycle + REER valuation + policy momentum "
                 "− credibility penalty", fontsize=10.5, color=INK)
    _save(fig, path)


# ------------------------------------------------- 6. context filter map

_VERDICT_COL = {"EARLY_TURN": ST_GOOD, "SETUP": ST_WARN,
                "TREND_INTACT": ST_CRIT, "WATCH": MUTED, "LATE": BASE}
_VERDICT_LBL = {"EARLY_TURN": "early turn — fade it", "SETUP": "setup — position early",
                "TREND_INTACT": "trend intact — don't fade", "WATCH": "watch", "LATE": "late"}


def context_chart(res, path: Path):
    fams = [("inflation", res.infl_ctx, "Inflation gap"),
            ("slope", res.slope_ctx, "Curve slope"),
            ("reer", res.reer_ctx, "REER")]
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.4), sharey=True)
    for ax, (fam, d, title) in zip(axes, fams):
        ax.axhline(0, color=BASE, lw=1)
        ax.axvspan(0.75, 3.2, ymin=0.5, ymax=1, color="#e2eee0", alpha=0.5, zorder=0)
        ax.axvspan(0.75, 3.2, ymin=0, ymax=0.5, color="#f4e5dc", alpha=0.5, zorder=0)
        for v in (d or {}).values():
            if v.verdict == "NONE":
                continue
            col = _VERDICT_COL[v.verdict]
            ax.scatter([abs(v.z)], [v.context], s=46, color=col, zorder=3,
                       marker="^" if v.turning else "o",
                       edgecolors=SURFACE, linewidths=1.1)
            ax.annotate(v.cc, (abs(v.z), v.context), textcoords="offset points",
                        xytext=(5, 4), fontsize=7.5, color=INK)
        ax.set_xlim(0.6, 3.2); ax.set_ylim(-1.05, 1.05)
        ax.set_title(title, fontsize=10, color=INK)
        ax.set_xlabel("stretch |z|")
        ax.tick_params(labelsize=8)
    axes[0].set_ylabel("context score\n(+ = pushes back to mean)")
    handles = [plt.Line2D([], [], ls="", marker="o", color=_VERDICT_COL[k],
                          label=_VERDICT_LBL[k])
               for k in ("EARLY_TURN", "SETUP", "TREND_INTACT", "WATCH", "LATE")]
    handles.append(plt.Line2D([], [], ls="", marker="^", color=INK2,
                              label="▲ = correction already started"))
    fig.legend(handles=handles, loc="lower center", frameon=False, fontsize=8.5,
               ncol=6, bbox_to_anchor=(0.5, -0.06))
    fig.suptitle("The context filter — fade only the extremes the cycle has "
                 "turned against (upper half); leave confirmed trends alone (lower half)",
                 fontsize=10.5, color=INK, y=1.03)
    _save(fig, path)


# ---------------------------------------------- 7. OU projections (multiples)

def ou_chart(res: Results, ccs: list[str], path: Path, years: int = 6):
    n = len(ccs)
    fig, axes = plt.subplots(1, n, figsize=(3.1 * n, 3.2), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, cc in zip(axes, ccs):
        z = res.ind["infl_z"][cc].dropna().tail(years * 12)
        f = res.infl_fits.get(cc)
        ax.plot(z.index, z.values, color=S1_BLUE, lw=1.6)
        if f is not None:
            h = 18
            import pandas as pd
            future = pd.date_range(z.index[-1], periods=h + 1, freq="MS")[1:]
            ax.plot(future, expected_path(f, h), color=S2_ORANGE, lw=1.6, ls="--")
        ax.axhline(INFL_DANGER_Z, color=ST_CRIT, lw=1, ls=":", alpha=0.85)
        ax.axhline(0, color=BASE, lw=0.8)
        ax.set_title(f"{cc} — HL {f.half_life:.0f}m" if f else cc,
                     fontsize=9.5, color=INK)
        ax.tick_params(labelsize=7)
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(30)
    axes[0].set_ylabel("inflation gap (z)")
    fig.suptitle("Inflation gap: history (blue), OU projection (orange dash), "
                 "danger line (red dots)", fontsize=10, color=INK, y=1.04)
    _save(fig, path)


def render_all(res: Results, outdir: Path) -> dict[str, Path]:
    paths = {
        "clock": outdir / "clock.png",
        "stance": outdir / "stance.png",
        "danger": outdir / "danger.png",
        "slope": outdir / "slope.png",
        "fx": outdir / "fx.png",
        "context": outdir / "context.png",
    }
    clock_chart(res, paths["clock"])
    stance_chart(res, paths["stance"])
    danger_chart(res, paths["danger"])
    slope_chart(res, paths["slope"])
    fx_chart(res, paths["fx"])
    context_chart(res, paths["context"])
    # OU multiples: the four most "interesting" = largest |z| with fast HL
    ranked = sorted(res.infl_fits.items(),
                    key=lambda kv: -abs(kv[1].z) / max(6.0, kv[1].half_life))
    ccs = [cc for cc, _ in ranked[:4]]
    if ccs:
        paths["ou"] = outdir / "ou.png"
        ou_chart(res, ccs, paths["ou"])
    return paths
