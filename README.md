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
3. **Context filter** (`models/context.py`) — because *mean reversion alone is
   a bad idea*: every |z| ≥ 0.75 stretch is cross-examined against its own turn
   evidence (has the correction begun? how much of the 12-month peak is already
   retraced?) and a context score built from leading-growth momentum, real-rate
   restrictiveness, policy direction and the clock heading. Verdicts:
   **EARLY TURN** (correction begun, only slightly retraced, context confirms →
   the best entry), **SETUP** (still pinned at the extreme but leading
   indicators breaking hard from the top → position for the counter-movement),
   **TREND INTACT** (the context still feeds the extreme → *never* fade),
   **LATE** (edge gone). The verdicts gate the mean-reversion terms in the
   trade models — TREND INTACT zeroes them, EARLY TURN boosts them.
4. **Divergence / standouts** (`models/divergence.py`) — each central bank's
   6-month policy move is compared to the universe median (robust MAD z),
   plus real-rate gaps and inflation momentum → labeled signals: *early
   hiker*, *deliberating a hike while others are neutral/cutting*, *cutting
   into inflation*, *behind the curve*, *room to cut*.

Trade generation (`models/trades.py`) maps all of it to markets:

- **FX score** = carry (haircut when inflation eats it) + clock phase
  (weighted toward the *heading* when rotation is fast) + context-gated REER
  mean-reversion pull + policy momentum − credibility penalty. Crosses pair
  the strongest longs against the weakest *fundable* (credible) shorts, with
  the concrete expression (rolled 3m forwards, indicative carry in pp).
- **Curve call** = 0.6 × phase implication + 0.4 × context-gated OU
  slope-stretch fade → steepener / flattener with 1–3 star conviction and the
  exact legs (2s10s DV01-neutral: pay/receive 2y vs 10y).

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

`scripts/build_html.py` renders the self-contained HTML version, and
`scripts/site_publish.py --deploy` publishes it to the veerock site's
Research > Cycle Analyzer tab (white theme, weekly archive rotation to
`/research/cycle/archive/`, CloudFront invalidation). A scheduled Routine
runs the whole chain every Sunday 15:00 Europe/Warsaw (13:00 UTC).

## Retrospective (point-in-time) editions

`scripts/retro_build.py` rebuilds the monitor *as it could have been written*
on a past Sunday, using only information available before 00:00
Europe/Warsaw on that date (`cycle_analyzer/retro/`):

| Input | Point-in-time source |
|---|---|
| REER (24), 10y yields (17), US CPI | ALFRED vintage of the Friday before the cutoff |
| OECD CLI (13) | immutable DBnomics git commit of `DSD_KEI@DF_KEI` before the cutoff |
| Business confidence (10) | DBnomics `DSD_STES@DF_BTS` commit; percent balance centred on its own pre-cutoff mean |
| CPI y/y | freshest matching-definition pre-cutoff archive (BIS / OECD), plus verified original releases (`data/retro/original_releases.json`) |
| Policy rates | DBnomics BIS `WS_CBPOL` commit; later decisions only if announced *and* effective before the cutoff, each cited (`data/retro/announcement_sources.json`) |

The retrospective method also charges negative carry in full, measures policy
changes from the effective snapshot to exact calendar month-ends, and prints
an evidence appendix (observation dates, effective policy, CPI sources,
source ledger with SHA-256). The live weekly pipeline is unchanged.

```bash
python scripts/retro_build.py --range 2025-01-01 2025-02-28 --every 14
python scripts/retro_audit.py 2025-01-05 2025-01-19 2025-02-02 2025-02-16
python scripts/retro_build.py 2025-01-05 ... --deploy   # archive only; latest.html untouched
```

`retro_audit.py` re-checks every edition for look-ahead (source availability,
observation months, policy effective dates, dates mentioned in the page).
Exact model inputs and evidence are retained under `data/retro/<date>/`.

## Caveats

- Signals are monthly and slow; this is a strategic framework, not an
  execution model. Nothing here is investment advice.
- OU projections are conditional expectations — a supply shock (energy, FX
  pass-through) is exactly what a mean-reversion model cannot anticipate;
  the "not in danger" flag means *the endogenous cycle* is benign.
- CPI y/y scaled by own history deliberately normalizes chronic
  high-inflation regimes (Türkiye): within-regime dynamics drive the clock,
  while the FX credibility penalty carries the level effect.
