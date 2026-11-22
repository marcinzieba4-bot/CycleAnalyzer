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
fires every Sunday 15:00 Europe/Warsaw (13:00 UTC) but publishes only on
the **biweekly grid** (every 14 days from 2025-01-05) and skips off-weeks,
so the site carries one report every two weeks.

`scripts/archive_thin.py` enforces that grid on the published archive: it
lists off-grid pages (dry run by default) and with `--apply` copies them to
`veerock-site/backups/cycle-archive-thinned-<stamp>/` (outside the public
prefix) before removing them and rebuilding the index.

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
| Inflation benchmarks | the benchmark publicly known at the cutoff (`cycle_analyzer/retro/benchmarks.py`; e.g. China's 2025 CPI objective of ~2%, announced 5 Mar 2025, applies from the 2025-03-16 edition; South Africa's 3% point target from 12 Nov 2025) |

**Frozen archives.** DBnomics stopped converting BIS in July 2025 and OECD in
June 2026. When an archive's newest pre-cutoff commit is more than 30 days
old, the builder falls back to: the ALFRED Friday vintage of the OECD CLI
(`<ISO3>LOLITOAASTSAM`); BIS CPI and policy histories as cached in this
repository's newest pre-cutoff `data/raw` commit (the weekly pipeline's own
dated fetch); and, for policy decisions after that snapshot's last month,
the BIS daily decision history with every decision cited. Editions built
from fresh archives are unaffected (verified byte-for-byte on the model
output).

The retrospective method also charges negative carry in full, measures policy
changes from the effective snapshot to exact calendar month-ends, and prints
an evidence appendix (observation dates, effective policy, CPI sources,
source ledger with SHA-256). The live weekly pipeline is unchanged.

```bash
python scripts/retro_build.py --range 2025-01-01 2025-02-28 --every 14
python scripts/retro_audit.py 2025-01-05 2025-01-19 2025-02-02 2025-02-16
python scripts/retro_build.py 2025-01-05 ... --deploy   # archive only; latest.html untouched
```

Editions built so far (biweekly Sundays): 2025-01-05 … 2025-02-16,
2025-03-02, 03-16, 03-30, 04-13, 04-27, 05-11, 05-25, and 2025-06-08,
06-22, 07-06, 07-20, 08-03, 08-17, 08-31, 09-14, 09-28; plus 2026-09-13
(the gap between the 2026-08-30 and 2026-09-27 archive pages). Pass edition
dates explicitly (or a `--range` whose start *is* a grid Sunday): `--range`
steps from the first Sunday on/after its start.

DBnomics' BIS mirror has not updated since 2025-07-10, so from mid-July 2025
the archived BIS CPI and policy files are frozen. Policy stays current
through the cited decision history; CPI comes from the OECD archives, and for
the economies they do not cover (Japan, Canada, Mexico, South Africa, Chile,
Thailand, India) from verified original national releases. Editions after
mid-2026 need a citation for every decision since July 2025.

### Pre-archive editions (Q1 2008): real-time vintages

No DBnomics archive or ALFRED vintage of the REER, CLI or long-rate series
reaches back to 2008, so editions dated on or before 2016-12-31 are built by
`cycle_analyzer/retro/realtime.py` instead:

| Input | Point-in-time source |
|---|---|
| OECD CLI, amplitude adjusted (20–21) | OECD real-time revisions database (`DSD_STES_REVISIONS@DF_STES_REVISIONS`), the newest monthly edition whose CLI was demonstrably public before the cutoff (`data/retro/oecd_rt_editions.json`: dated press reports, with a content check against the published OECD-area figures) |
| CPI y/y (21) | CP index of the newest revisions-database edition whose edition month had ended; y/y computed inside that vintage (China is stored as previous-year = 100). US: ALFRED CPIAUCNS Friday vintage |
| CPI Chile, Colombia, Thailand | present-day BIS `WS_LONG_CPI`, requested only through the month whose *following* month had ended |
| REER (24) | present-day BIS broad REER, same one-full-month gate (no 2008 vintage exists; disclosed on every page) |
| 10y yields (17) | present-day monthly market averages, completed months only |
| Policy (24) | BIS daily decision history downloaded only to the last day before the cutoff; BIS end-of-month rates through the last completed month |
| Inflation benchmarks | `data/retro/benchmarks_2008.json`: the objective publicly in force (e.g. BoJ ~1%, Norway 2.5%, Brazil 4.5%, China 3% → 4.8% from the 5 Mar 2008 Government Work Report), each with sources shown only once published |

Inputs whose latest observation is more than 9 months older than the anchor
month are not used (Turkey's CLI in the Dec-2007 and Jan-2008 editions).
Editions built (biweekly grid): 2008-01-06, 01-20, 02-03, 02-17, 03-02,
03-16, 03-30, 04-13, 04-27, 05-11, 05-25, 06-08, 06-22, 07-06, 07-20,
08-03, 08-17, 08-31, 09-14, 09-28, 10-12, 10-26, 11-09, 11-23, 12-07, 12-21;
2009-01-04, 01-18, 02-01, 02-15, 03-01, 03-15, 03-29, 04-12, 04-26, 05-10,
05-24, 06-07, 06-21, 07-05, 07-19, 08-02, 08-16, 08-30, 09-13, 09-27,
10-11, 10-25, 11-08, 11-22, 12-06, 12-20
(`python scripts/retro_build.py --range 2008-01-01 2009-12-31 --every 14`).
India follows the RBI's end-of-fiscal-year figure: 5.0 from 28 Jul 2009,
6.5 from 27 Oct 2009. Next-year targets announced in 2009 (Colombia, Korea,
Türkiye, Poland, Japan's clarified "understanding") are recorded as wording.
China's CPI is absent from every 2009 real-time edition: when a series is
missing from the eligible edition, the present-day BIS history behind the
one-full-month gate competes with the newest earlier edition and the fresher
one is used (data notes say which). India's benchmark follows the RBI's stated
end-of-fiscal-year figure (4.0 from the 2009–10 Annual Policy, 21 Apr 2009).
2009 editions use `data/retro/benchmarks_2009.json`: the current-year (2009)
targets as publicly known — Türkiye 7.5, Colombia 5.0, Indonesia 4.5 (set
during 2008), India 3.0 from the RBI's 27 Jan 2009 review, China 4.0 from the
5 Mar 2009 Government Work Report. A CPI series missing from the eligible
real-time edition (China in the Jan/Feb 2009 editions) comes from the newest
earlier edition carrying it, disclosed in the data notes.
Q4: the December 2008 CLI edition is the first under the OECD's revised
method (double Hodrick–Prescott filter replacing PAT; the vintage's whole
history was re-estimated) and the pages using it say so; the US instrument
becomes the target-range midpoint only after 16 Dec 2008. Q4 benchmark
announcements (South Africa's CPIX → CPI switch, India, US, UK, Colombia,
New Zealand) changed wording only, not values.
Q3 benchmark change: India 5.5 → 7.0 (RBI First Quarter Review, 29 Jul 2008:
"close to 7.0 per cent" by end-March). The Q3 CLI editions are
content-checked against dated reports (OECD area, or Italy for September).
Q2 benchmark changes applied from their announcement dates: India 5.0 → 5.5
(RBI Annual Policy Statement, 29 Apr 2008); Türkiye keeps its end-2008 4%
target after the 3 Jun 2008 revision of later-year targets. CLI release dates
without a retrievable press report (Mar, May, Jun 2008 editions) rest on
Haver's dated archive entries, bracketed by ECB Monthly Bulletin cut-offs; each
evidence item appears on a page only once it was itself published.

### 2010 editions

Biweekly grid continued: 2010-01-03, 01-17, 01-31, 02-14, 02-28, 03-14,
03-28, 04-11, 04-25, 05-09, 05-23, 06-06, 06-20, 07-04, 07-18, 08-01, 08-15,
08-29, 09-12, 09-26, 10-10, 10-24, 11-07, 11-21, 12-05, 12-19
(`python scripts/retro_build.py --range 2010-01-01 2010-12-31 --every 14`).

- **CLI editions** January–December 2010 are registered from dated public
  reports, each content-checked against the vintage's OECD-area (January:
  euro-area) figures. The August 2010 release (June data) has no properly
  dated report with a point figure, so it is *not* registered: the
  2010-08-15 and 2010-08-29 editions keep the July edition, and 2010-09-12
  takes August's only through the edition-month-end rule.
- **Release reference-month cap.** An edition admitted by a dated press report
  is only shown public through that release's reference month. The February
  2010 database edition carries January 2010 rows for 16 economies (the
  release itself covered December 2009); those rows are dropped in the
  2010-02-14 and 2010-02-28 editions, disclosed in the data notes, and
  `retro_audit.py` now checks it.
- **Türkiye's instrument switch.** On 18 May 2010 the CBRT kept overnight
  rates unchanged and made the one-week repo rate (7%, 50bp above the
  overnight borrowing rate) its policy rate; the BIS series switches on
  20 May (6.50% → 7.00%). That is not a hike: from the switch on, earlier
  history is spliced onto the new instrument (`INSTRUMENT_SWITCH` in
  `realtime.py`), so 3/6/12-month changes, holds and the decision list are
  measured on one instrument; the current level and carry use the actual 7%.
- **Benchmarks** (`data/retro/benchmarks_2010.json`): Czechia 2% from January
  2010 (announced 8 Mar 2007), Türkiye 6.5, Colombia 3 (2–4% range), Korea
  3 ±1, Indonesia 5 ±1 (stated by Bank Indonesia on 3 Sep 2009; formalised
  by PMK 143/2010 on 24 Aug 2010), Brazil 4.5; China 4 → 3 from the 5 Mar 2010
  Government Work Report; India's end-of-fiscal-year WPI projection 6.5 →
  8.5 (29 Jan) → 5.5 (20 Apr) → 6.0 (27 Jul) → 5.5 on the new WPI series
  (2 Nov). FOMC projections, UK budgets/remit, the BoJ's April review, the
  RBA's new Statement and South Africa's budget change wording only.
  Forward-year targets are paraphrased ("the following year's") so that no
  page names a later date.
- **China CPI storage.** The revisions database stores China's CP as "same
  month of the previous year = 100" only in the 2007–2008 editions; from
  200911 it is a fixed-base index (2009-07: 111.08 vs 113.11 a year earlier
  = −1.8%, the NBS figure). Reading it as previous-year = 100 reported the
  index level less 100 (~11–15%) as inflation. Those editions now take the
  12-month ratio inside the vintage, and since that derived index deviates
  from the published y/y by up to ~0.9pp in some vintages, the published y/y
  behind the one-full-month gate competes (the fresher wins; in every 2010
  edition it is the published y/y). 2008 editions and the 2009 editions
  where China is absent rebuild byte-identically. The 2009-12-06 and
  2009-12-20 pages, built before this fix with China's CPI at 11.08% (true
  −1.8% for 2009-07), were rebuilt and republished on 2026-11-22 (China now
  −0.6%, the published October 2009 y/y), as were 2008-02-17 and 2008-03-02,
  where the reference-month cap drops Switzerland's January 2008 CLI row
  (the February 2008 release covered December 2007). Only those inputs
  changed. Caveat: with China's real rate correctly positive, long CNY tops
  the FX crosses in some editions; the model ignores the 2008–10 USD peg and
  treats the 5.31% benchmark lending rate as carry.

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
