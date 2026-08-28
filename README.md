# CycleAnalyzer

A framework for reading **DM + EM business cycles** as mean-reverting
oscillations, predicting *what comes next* in each economy's cycle, and turning
the reading into **FX and yield-curve trade ideas**.

The latest generated report lives in
[`reports/cycle_monitor.md`](reports/cycle_monitor.md).

## The idea

A business cycle is treated as a rotation in a two-dimensional phase space:

```
                 inflation gap (z)
                        ▲
      STAGFLATION       │       OVERHEATING
      (steepeners,      │       (pay front end,
       ccy vulnerable)  │        long the ccy)
   ─────────────────────┼─────────────────────▶ growth cycle (z)
      DISINFLATION      │       GOLDILOCKS
      (receive rates,   │       (credit & carry
       ccy funds carry) │        work)
```

Economies rotate counter-clockwise: Goldilocks → Overheating → Stagflation →
Disinflation. "The economy is heating up, so credit is fine for now — but the
inflation fight comes next" is literally a position and a rotation speed on
this clock.

Three model layers sit on top:

1. **Cycle clock** (`models/cycle_clock.py`) — phase angle from
   `atan2(inflation z, growth z)`, rotation speed from the median monthly
   change of the unwrapped angle → current phase, the phase we are *heading*
   into, and the ETA in months.
2. **Mean reversion** (`models/mean_reversion.py`) — every cycle variable is
   fit as an Ornstein–Uhlenbeck (AR(1)) process: half-life, stationary
   z-score, and a projected path that blends OU decay with fading momentum.
   Projecting the path against danger thresholds (+1σ = inflation fight,
   −1σ = recession zone) yields either a **months-to-danger** estimate or an
   explicit **"cycle not endangered"** flag — the economies where carry and
   credit can still be clipped without fighting the clock.
3. **Divergence / standouts** (`models/divergence.py`) — each central bank's
   6-month policy move is compared to the universe median (robust MAD z),
   plus real-rate gaps and inflation momentum → labeled signals: *early
   hiker*, *deliberating a hike while others are neutral/cutting*, *cutting
   into inflation*, *behind the curve*, *room to cut*.

Trade generation (`models/trades.py`) maps all of it to markets:

- **FX score** = carry (haircut when inflation eats it) + clock phase
  (weighted toward the *heading* when rotation is fast) + REER mean-reversion
  pull + policy momentum − credibility penalty. Crosses pair the strongest
  longs against the weakest *fundable* (credible) shorts.
- **Curve call** = 0.6 × phase implication + 0.4 × OU slope-stretch fade →
  steepener / flattener with 1–3 star conviction; double-confirmation
  (phase and mean reversion agreeing) is flagged explicitly.

## Universe & data

24 economies (10 DM, 14 EM), all series monthly, no API keys required:

| Indicator | Source | Coverage |
|---|---|---|
| Policy rates | BIS `WS_CBPOL` | all 24 |
| CPI y/y | BIS `WS_LONG_CPI` | all 24 |
| Real effective FX (broad REER) | BIS `WS_EER` | all 24 |
| Composite leading indicator | OECD via DBnomics (`DF_CLI`, business confidence fallback) | 23 |
| 10y government yield | FRED (`IRLTLT01*`) | 17 |

Fetched series are cached under `data/raw/` (committed), so the pipeline is
fully reproducible offline.

## Usage

```bash
pip install -r requirements.txt
python scripts/run_analysis.py             # cached data
python scripts/run_analysis.py --refresh   # re-download everything
```

Output: `reports/cycle_monitor.md` + charts in `reports/charts/`.

## Caveats

- Signals are monthly and slow; this is a strategic framework, not an
  execution model. Nothing here is investment advice.
- OU projections are conditional expectations — a supply shock (energy, FX
  pass-through) is exactly what a mean-reversion model cannot anticipate;
  the "not in danger" flag means *the endogenous cycle* is benign.
- CPI y/y scaled by own history deliberately normalizes chronic
  high-inflation regimes (Türkiye): within-regime dynamics drive the clock,
  while the FX credibility penalty carries the level effect.
