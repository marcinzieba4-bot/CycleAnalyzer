# CycleAnalyzer

A framework for reading **DM + EM business cycles** as mean-reverting
oscillations, predicting *what comes next* in each economy's cycle, and turning
the reading into **FX and yield-curve trade ideas**.

The latest generated report lives in
[`reports/cycle_monitor.md`](reports/cycle_monitor.md).

**Trading rulebook:** [`reports/strategy/STRATEGY.md`](reports/strategy/STRATEGY.md) covers how to
trade the editions' ideas, how long to hold, and which stops to use. It was backtested on all
465 point-in-time editions 2008–2026 (`scripts/strategy_*.py`; designed on 2008–18, checked on
2019–26). Daily signals: `python scripts/strategy_backtest.py --live`.

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
06-22, 07-06, 07-20, 08-03, 08-17, 08-31, 09-14, 09-28; 2025-10-12 …
2026-08-30 (24 editions, below); and 2026-09-13. The repository now holds every
grid edition from 2008-01-06 to 2026-09-13; the live weekly pipeline publishes
from 2026-09-27. Pass edition dates explicitly (or a `--range` whose start *is* a
grid Sunday): `--range` steps from the first Sunday on/after its start.

DBnomics' BIS mirror has not updated since 2025-07-10, so from mid-July 2025
the archived BIS CPI and policy files are frozen. Policy stays current
through the cited decision history; CPI comes from the OECD archives, and for
the economies they do not cover (Japan, Canada, Mexico, South Africa, Chile,
Thailand, India) from verified original national releases. Editions after
mid-2026 need a citation for every decision since July 2025.

### 2025-10-12 … 2026-08-30 editions

Biweekly grid: 2025-10-12, 10-26, 11-09, 11-23, 12-07, 12-21, 2026-01-04, 01-18,
02-01, 02-15, 03-01, 03-15, 03-29, 04-12, 04-26, 05-10, 05-24, 06-07, 06-21,
07-05, 07-19, 08-02, 08-16, 08-30 (`python scripts/retro_build.py 2025-10-12 …`),
built 2026-11-27 with the archive-era method and audited (look-ahead audit
0 failed). The site archive already carried pages for these dates built outside
this repository (different templates, no retained inputs); they were not replaced.

- **Policy.** Every decision effective after the frozen BIS archive is cited from
  the central bank's own announcement (46 new entries in
  `data/retro/announcement_sources.json`, Sep 2025 – Jul 2026); where a bank's site
  blocks automated fetching (RBNZ, NBP, BCCh) the label says so and a second
  official source (rate table, BIS daily) corroborates it. The global turn shows in
  the decisions: cuts through early 2026 (Fed, BoC, BoE, NBP, Banxico, SARB, RBI, BoT,
  BCB), then hikes from February 2026 (RBA ×3, BanRep ×3, BI ×3 incl. an off-cycle
  hike on 9 Jun, BoJ, ECB, Norges Bank, CNB, SARB, RBNZ, BoK).
- **BIS daily errata** (`DAILY_ERRATA` in `panels.py`, new for the archive era). The
  MNB cut its base rate to 6.00% from 24 Jun 2026 (Decree 17/2026 (VI. 23.)); the BIS
  daily series shows 6.25% again on 25–30 Jun and 6.00% from 1 Jul with no decision
  in between. Those days, and a repository snapshot's June month-end carrying the same
  error, are read at 6.00%, and the page says so. The 2026-08-30 and 2026-09-13
  editions (repository snapshot of 2026-08-28) carry the corrected June value.
- **CPI first releases** (`data/retro/original_releases.json`, 154 new entries). The
  DBnomics OECD prices archive stops at 2025-12 for the euro area, CH, SE, NO, TR, PL,
  HU and CZ and at 2026-04/05 for most others (frozen from June 2026), so headline CPI
  is appended as first printed: JP, TH, IN, CA, MX, CL, ZA 2025-09 … 2026-07; XM
  (Eurostat flash), CH, SE (SCB's Snabb-KPI flash, then the regular release), NO, TR,
  PL (flash; first full release for Jan–Feb 2026, when GUS published no flash), HU, CZ
  (preliminary) 2026-01 … 07; GB, BR, CO, CN, ID, KR for the last two or three months.
  Each entry records the fetched document's sha256 and fetch time. Where a statistics
  office blocks automated access the label names the official mirror or release-day
  report used (TurkStat via the Treasury's bulletins or Anadolu Agency; KSH via the
  MNB's same-day flash analysis; BPS via ANTARA). Base changes named in the labels:
  JP 2025=100 (from July 2026 data), IN 2024=100 (from January 2026), CN 2025, TR
  2025=100, CH December 2025=100, COICOP 2018 across Europe. Every value agrees with
  today's BIS history within 0.3pp except Thailand March 2026 (−0.08% as published by
  the TPSO; BIS now shows −0.68%).
- **Partial archive commits** (`_backfill_truncated` in `panels.py`). Several 2026
  DBnomics commits of the OECD datasets carry a partial conversion of a model series:
  only its newest observation (UK CPI with December 2025 alone in the 2026-02-01
  edition's archive), no recent observations (the confidence balances of Norway, New
  Zealand, Chile and others ending in 2023 in the 2026-04-12 archive), or no series at
  all (Canada's CPI in March 2026). Each model series of the newest pre-cutoff commit
  is compared with the predecessors committed within the previous 62 days (all before
  the cutoff); missing or later observations are filled from them, the newer commit's
  values kept wherever it has them, and one data note per archive lists every filled
  series with the commit it came from. A candidate series with too short a history (fewer
  than half of the 120 months to its last observation) is never preferred to a complete
  one — Canada's new one-observation CPI code of April 2026, Australia's new monthly
  CPI — and the euro-area confidence proxy switches to EA20 only once that aggregate has
  a full history. Without these rules four editions would have lost a clock and three
  would have used inputs 10–30 months stale.
- **Neighbours.** A rebuilt 2025-09-28 has byte-identical model inputs. The rebuilt
  2026-09-13 differs in two inputs only: South Africa's July 2026 CPI (4.3%, Stats SA
  19 Aug 2026, before the cutoff; missing before) and Hungary's June 2026 rate (6.00%);
  its crosses, curve calls and plays are unchanged.

### Pre-archive editions (Q1 2008): real-time vintages

No DBnomics archive or ALFRED vintage of the REER, CLI or long-rate series
reaches back to 2008, so editions dated on or before 2024-12-31 are built by
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

### 2011 editions

Biweekly grid continued: 2011-01-02, 01-16, 01-30, 02-13, 02-27, 03-13,
03-27, 04-10, 04-24, 05-08, 05-22, 06-05, 06-19, 07-03, 07-17, 07-31, 08-14,
08-28, 09-11, 09-25, 10-09, 10-23, 11-06, 11-20, 12-04, 12-18
(`python scripts/retro_build.py --range 2011-01-01 2011-12-31 --every 14`).

- **CLI editions** January–August, October and November 2011 are registered
  from dated public reports (Diario Financiero, City A.M., IBTimes, Reuters
  via Fox Business, MercoPress, Le Moci, Korea Times), each content-checked
  against the vintage (OECD area, euro area, Germany or the UK, whichever the
  report quotes). The September and December 2011 releases (July and October
  data) have no retrievable dated report with figures, so they are *not*
  registered: the 2011-09-25 edition keeps the August release and 2011-12-18
  keeps November's; both become eligible only through the edition-month-end
  rule. (A blog's monthly "total leading index" percentages were rejected as
  evidence: they match the OECD-area vintage in one month only.)
- **Withheld areas.** The April 2011 release gave no figures for Japan after
  the earthquake ("No figures were given for Japan", Reuters, 11 Apr 2011),
  although the database edition carries them. A register entry's `withheld`
  areas are taken, until that edition's month has ended, from the newest
  earlier eligible edition (Japan in 2011-04-24 comes from the March release,
  through January 2011); `retro_audit.py` checks the fallback's eligibility.
  The October 2011 database edition carries September rows; the reference-
  month cap drops them in 2011-10-23 and 2011-11-06.
- **Benchmarks** (`data/retro/benchmarks_2011.json`): current-year targets
  Türkiye 5.5, Brazil 4.5 (CMN Res. 3,748, 30 Jun 2009), Colombia 3 (2–4%,
  Board of 19 Nov 2010), Indonesia 5 ±1 (PMK 143/2010); China 3 → 4 from the
  5 Mar 2011 Government Work Report ("keep the CPI increase around 4
  percent"); India's end-of-fiscal-year WPI projection 5.5 → 7.0 (25 Jan) →
  6.0 for the following fiscal year (3 May) → 7.0 (26 Jul; kept 25 Oct).
  Value-unchanged wording updates are not recorded.

### 2012 editions

Biweekly grid continued: 2012-01-01, 01-15, 01-29, 02-12, 02-26, 03-11,
03-25, 04-08, 04-22, 05-06, 05-20, 06-03, 06-17, 07-01, 07-15, 07-29, 08-12,
08-26, 09-09, 09-23, 10-07, 10-21, 11-04, 11-18, 12-02, 12-16, 12-30
(`python scripts/retro_build.py --range 2012-01-01 2012-12-31 --every 14`).

- **CLI editions** January–December 2012 are all registered from dated
  public reports (Domain-B, Reuters via The Reformed Broker / Business
  Standard / Irish Times / Globe and Mail / Fox Business, City A.M., 24/7
  Wall St, PTI, RTTNews), each page fetched and content-checked against the
  vintage (OECD area, euro area, France, India or the US, whichever the
  report quotes with a matching level *and* monthly change). The 2012-01-01
  edition keeps the December 2011 edition through the edition-month-end rule.
  The June 2012 database edition carries May rows for the OECD/euro-area
  aggregates and Indonesia; the reference-month cap drops them.
- **Method change.** The April 2012 edition is the first in which the CLI
  targets GDP instead of industrial production as its reference series (OECD
  methodology guideline, April 2012: "From April 2012 therefore the OECD has
  switched to using GDP as the reference"); the vintage's whole history was
  re-estimated, so levels shift (euro area January 2012: 98.7 in the March
  edition, 99.6 in April's). Pages using it carry the method note, as the
  December 2008 PAT → double-HP pages do.
- **Benchmarks** (`data/retro/benchmarks_2012.json`): current-year targets
  Türkiye 5 (set 10 Dec 2009), Brazil 4.5 (CMN Res. 3,880), Colombia 3 ±1
  (Board of 25 Nov 2011), Indonesia 4.5 ±1 (PMK 143/2010); Canada cites its
  8 Nov 2011 renewal; China ~4% re-set by the 5 Mar 2012 Government Work
  Report; India's end-of-fiscal-year WPI projection 7.0 (kept 24 Jan) → 6.5
  for the following fiscal year (17 Apr) → 7.0 (31 Jul) → 7.5 (30 Oct). Three
  framework changes are recorded although the value is unchanged, because
  they replace the row's wording: the FOMC's first explicit 2% (PCE) goal
  (25 Jan), the BoJ's 1% "price stability goal" (14 Feb) and New Zealand's
  Policy Targets Agreement of 20 Sep 2012.

### 2013 editions

Biweekly grid continued: 2013-01-13, 01-27, 02-10, 02-24, 03-10, 03-24,
04-07, 04-21, 05-05, 05-19, 06-02, 06-16, 06-30, 07-14, 07-28, 08-11, 08-25,
09-08, 09-22, 10-06, 10-20, 11-03, 11-17, 12-01, 12-15, 12-29
(`python scripts/retro_build.py --range 2013-01-13 2013-12-31 --every 14`),
published to the site archive on 2026-11-25 (all 26 pages verified
byte-identical live; 33,513 audit checks, 0 failed).

- **CLI editions** January–December 2013 are all registered from dated
  public reports (City A.M., Reuters via Fox Business / Business Standard /
  Yahoo, RTTNews, RTÉ, IANS, The Irish Times, a dated blog, and the OECD's
  own releases of 11 Feb and 8 Aug 2013), each page fetched and
  content-checked against the vintage (OECD area, UK or Japan). The October
  check uses The Irish Times' two-decimal figures (OECD area 100.59; all six
  quoted values equal the vintage exactly), because the rounded "100.6 from
  100.5" reports differ from the vintage's +0.04 monthly change. Release
  days: 14 Jan, 11 Feb, 11 Mar, 10 Apr, 14 May, 10 Jun, 8 Jul (public by the
  9 Jul report), 8 Aug, 9 Sep, 9 Oct, 12 Nov, 9 Dec. No 2013 edition
  re-estimates the CLI history, so no method note applies.
- **Japan's instrument.** The BoJ's QQE statement of 4 Apr 2013 made the
  monetary base its main operating target; the BIS series stays at the
  former 0–0.1% call-rate guideline (0.05%). From the 2013-04-07 edition the
  evidence page labels it a short-rate proxy, not a target (no level or
  decision changes).
- **Benchmarks** (`data/retro/benchmarks_2013.json`): current-year targets
  Türkiye 5 (set 21 Dec 2010, kept 25 Dec 2012), Brazil 4.5 (CMN Res. 3,991),
  Colombia 3 ±1 (Board of 23 Nov 2012), Indonesia 4.5 ±1 (PMK
  66/PMK.011/2012), Korea 2.5–3.5% (midpoint 3, MPC of 11 Oct 2012); Japan
  1 → 2 from the BoJ's "price stability target" (22 Jan); China ~4% → ~3.5%
  from the 5 Mar 2013 Government Work Report; India's end-of-fiscal-year WPI
  figure 7.5 → 6.8 (29 Jan) → 5.0 (3 May: "a level of 5.0 per cent by March"
  of the following year; later 2013 reviews give no numeric end-March
  figure). The RBA's new Statement on the Conduct of Monetary Policy (24 Oct)
  is recorded for its wording; the UK remit of 20 Mar and Thailand's
  unchanged 2013 core target are not.

### 2014 editions

Biweekly grid continued: 2014-01-12, 01-26, 02-09, 02-23, 03-09, 03-23,
04-06, 04-20, 05-04, 05-18, 06-01, 06-15, 06-29, 07-13, 07-27, 08-10, 08-24,
09-07, 09-21, 10-05, 10-19, 11-02, 11-16, 11-30, 12-14, 12-28
(`python scripts/retro_build.py --range 2014-01-12 2014-12-31 --every 14`),
published to the site archive on 2026-11-25 (all 26 pages verified
byte-identical live; 33,369 audit checks, 0 failed).

- **CLI editions** January, February and April–December 2014 are registered
  from dated public reports (Reuters via Business Standard / Yahoo / Lincoln
  Daily News, The Irish Times, RTÉ, PTI, Capital Market), each page fetched
  and content-checked against the vintage (OECD area, euro area or India).
  The January check uses the euro-area figures (101.0 from 100.8), because the
  OECD-area value (100.85) sits on a rounding boundary; the September check
  uses Reuters' two-decimal figures (OECD area 100.49; every two-decimal value
  quoted equals the vintage). The March 2014 release (January data) has no
  retrievable dated report with figures, so it is *not* registered: the
  2014-03-09 and 2014-03-23 editions keep the February release, and the March
  edition enters on 2014-04-06 through the edition-month-end rule (its
  database rows run one month past the release for the OECD and euro-area
  aggregates, which is irrelevant once the month has ended). Earliest dated
  reports: 13 Jan, 10 Feb, 9 Apr (release 8 Apr), 13 May, 10 Jun, 8 Jul,
  11 Aug, 8 Sep, 8 Oct, 12 Nov, 8 Dec. No 2014 edition re-estimates the CLI
  history (revisions to 2000–2011 values stay below 0.15 outside China's
  routine component revisions), so no method note applies.
- **Benchmarks** (`data/retro/benchmarks_2014.json`): current-year targets
  Türkiye 5 (CBRT policy document of 25 Dec 2012: "as was the case for the
  2013-2014 period"), Brazil 4.5 (CMN Res. 4,095), Colombia 3 ±1 (Board of
  29 Nov 2013), Indonesia 4.5 ±1 (PMK 66/PMK.011/2012), Korea 2.5–3.5%
  (midpoint 3); India 5.0 (the WPI end-of-fiscal-year figure of 3 May 2013)
  → 8.0 from the RBI's Third Quarter Review of 28 Jan 2014, which adopted the
  Patel Committee's CPI glide path ("an objective of below 8 per cent CPI
  inflation" by January of the following year): the first CPI-based Indian
  benchmark in the register; China ~3.5% re-set by the 5 Mar 2014 Government
  Work Report (recorded for its wording). Value-unchanged reaffirmations and
  targets set during 2014 for later years are not recorded.

### 2015 editions

Biweekly grid continued: 2015-01-11, 01-25, 02-08, 02-22, 03-08, 03-22,
04-05, 04-19, 05-03, 05-17, 05-31, 06-14, 06-28, 07-12, 07-26, 08-09, 08-23,
09-06, 09-20, 10-04, 10-18, 11-01, 11-15, 11-29, 12-13, 12-27
(`python scripts/retro_build.py --range 2015-01-11 2015-12-31 --every 14`),
published to the site archive on 2026-11-26 (all 26 pages verified
byte-identical live; 33,317 audit checks, 0 failed).

- **CLI editions** January–October 2015 are registered from dated public
  reports (Reuters via Lincoln Daily News / Investing.com / Daily FT / Voice
  of America, RTÉ, The Irish Times, RTTNews, IBTimes, Governance Now), each
  page fetched and content-checked against the vintage (OECD area, euro area,
  US, UK, China or India). Where the OECD-area monthly change sits on a
  rounding boundary (January: 100.44 → 100.49 reported as "100.5 from 100.4")
  another quoted area is checked. The May report prints the U.S. reading as
  "98.8 to 98.6" (vintage 99.8 to 99.6, apparently a misprint); its China,
  euro-area, German, French, Italian and Japanese figures all match, and the
  check uses China. The November and December 2015 releases (September and
  October data) have no retrievable dated report with figures, so they are
  *not* registered: 2015-11-15 and 2015-11-29 keep the October release, and
  the November edition enters on 2015-12-13 through the edition-month-end rule.
  Earliest dated reports: 12 Jan, 9 Feb, 9 Mar, 9 Apr, 12 May, 9 Jun, 8 Jul,
  10 Aug, 8 Sep, 8 Oct. No 2015 edition re-estimates the CLI history
  (revisions to 2000–2012 values stay at or below 0.34, the UK in October),
  so no method note applies.
- **Euro-area code.** The real-time database files the euro area as EA18 in
  every edition through January 2015 and only as EA19 from the February 2015
  edition (Lithuania joined on 1 January 2015). `realtime.rt_areas()` now
  picks the code per edition (CLI and CPI); earlier editions request the same
  URLs as before (a rebuilt 2014-12-28 page is byte-identical), and pages
  using an EA19 edition say so in the data notes.
- **US instrument.** From the 2015-12-27 edition the label names the
  0.25–0.50% target range effective 17 Dec 2015 (FOMC statement of 16 Dec:
  "decided to raise the target range for the federal funds rate to 1/4 to 1/2
  percent"); the BIS daily history moves 0.125 → 0.375 on that day.
- **Benchmarks** (`data/retro/benchmarks_2015.json`): current-year targets
  Türkiye 5 (CBRT policy document of 25 Dec 2012, para 19: "the inflation
  target for 2015 was set as 5 percent"), Brazil 4.5 ±2 (CMN Res. 4,237 of
  28 Jun 2013), Colombia 3 ±1 (Board of 28 Nov 2014), Indonesia 4.5 → 4 ±1
  (PMK 66/PMK.011/2012), Korea 2.5–3.5% (midpoint 3, the MPC's target for
  the three years from 2013); India 8 → 6, the second objective of the RBI's
  28 Jan 2014 glide path ("below 6 per cent CPI inflation" by January of the
  following year), with the Monetary Policy Framework Agreement recorded for
  its wording from the Governor's statement of 4 Mar 2015 (value unchanged);
  Thailand 1.75 (core 0.5–3.0%) → 2.5, the headline target of 2.5% ±1.5
  approved by the Cabinet on 6 Jan 2015; China ~3.5% → ~3% from the 5 Mar 2015
  Government Work Report ("keep the increase in the CPI at around 3%").
  Value-unchanged reaffirmations and targets set during 2015 for later years
  are not recorded; no wording names a later year.

### 2016 editions

Biweekly grid continued: 2016-01-10, 01-24, 02-07, 02-21, 03-06, 03-20,
04-03, 04-17, 05-01, 05-15, 05-29, 06-12, 06-26, 07-10, 07-24, 08-07, 08-21,
09-04, 09-18, 10-02, 10-16, 10-30, 11-13, 11-27, 12-11, 12-25
(`python scripts/retro_build.py --range 2016-01-10 2016-12-31 --every 14`),
published to the site archive on 2026-11-26 (all 26 pages verified
byte-identical live; 33,290 audit checks, 0 failed).

- **CLI editions** January–June and October–December 2016 are registered
  from dated public reports (PTI and Reuters via Business Standard, RTTNews,
  Gazeta do Povo, Republika, Investing.com, Lincoln Daily News, Uzmanpara /
  Milliyet, and the OECD's own release of 8 Mar 2016), each page fetched and
  content-checked against the vintage (OECD area, US, Germany or China). The
  June check uses Reuters' two-decimal figures (China 98.41 from 98.38; every
  two-decimal value quoted equals the vintage). The November report (Turkish)
  labels the month August, but its four two-decimal percentages (OECD area
  −0.01% m/m and −0.26% y/y, Türkiye +0.06% and +1.22%) equal the November
  edition's September values and not the October edition's August values.
  Release days: 11 Jan, 8 Feb, 8 Mar, 11 Apr, 11 May, 8 Jun, 10 Oct, 9 Nov,
  8 Dec.
- **No CLI in July and August.** The OECD suspended CLI publication over the
  summer of 2016 and released three months' worth of data on 8 Sep 2016; the
  July and August 2016 editions of the revisions database carry no LI_AA
  records at all (`NO_CLI_EDITIONS` in `realtime.py`), so 2016-07-10 …
  2016-09-18 keep the June release and the pages say so. The September release
  has no retrievable dated report with figures (the one Reuters copy found is
  not fetchable), so it is *not* registered and enters on 2016-10-02 through
  the edition-month-end rule. No 2016 edition re-estimates the CLI history, so
  no method note applies.
- **Japan's policy rate.** The BIS series is blank from 4 Apr 2013 (QQE) until
  21 Sep 2016. From 16 Feb 2016 the BoJ applied −0.1% to Policy-Rate Balances
  (announced 29 Jan 2016, BoJ statement cited on the page); that level fills
  the blank days (`DAILY_BRIDGE`), so the easing is dated when it took effect
  (0.05% proxy → −0.10%), and from 21 Sep 2016 the BIS series resumes at the
  same level as the short-term policy interest rate under yield-curve control.
  Interior months without a BIS monthly row take the daily month-end, as
  trailing months already did (earlier editions rebuild identically).
- **Indonesia's instrument switch.** On 19 Aug 2016 the BI 7-Day (Reverse)
  Repo Rate (5.25%) replaced the BI Rate (6.50%) as the policy rate (Bank
  Indonesia release No. 18/67/DKom, as announced on 15 Apr 2016). The BIS
  series switches that day; it is not a cut: from the switch on, earlier
  history is spliced onto the new instrument (−1.25pp), as for Türkiye in 2010.
- **US instrument.** From the 2016-12-25 edition
  the label names the 0.50–0.75% target range effective 15 Dec 2016 (FOMC
  statement and implementation note of 14 Dec 2016).
- **Benchmarks** (`data/retro/benchmarks_2016.json`): current-year targets
  Türkiye 5 (CBRT policy document of 24 Dec 2013, para 1: "the inflation
  target for 2016 is set as 5 percent"), Brazil 4.5 ±2 (CMN Res. 4,345 of
  25 Jun 2014), Colombia 3 ±1 (Board of 27 Nov 2015), Indonesia 4 ±1 (PMK
  93/PMK.011/2014), Korea 2 (MPC of 16 Dec 2015, replacing 2.5–3.5%), Thailand
  2.5 ±1.5 (Cabinet, 29 Dec 2015); India 6 → 5: the glide-path objective of
  below 6 per cent by January has reached its horizon, so the RBI's objective
  of "around 5 per cent by the end of fiscal" year (29 Sep 2015) is the
  current-year benchmark, with the statutory 4% ±2 target notified on
  5 Aug 2016 recorded for its wording (value unchanged; the MPC reaffirmed the
  5 per cent objective on 4 Oct 2016); China ~3% re-set by the 5 Mar 2016
  Government Work Report and the RBA's Statement of 19 Sep 2016, both recorded
  for their wording. Value-unchanged reaffirmations and targets set during 2016
  for later years (Canada's renewal of 24 Oct 2016) are not recorded; no
  wording names a later year.

### 2017 editions

Biweekly grid continued: 2017-01-08, 01-22, 02-05, 02-19, 03-05, 03-19,
04-02, 04-16, 04-30, 05-14, 05-28, 06-11, 06-25, 07-09, 07-23, 08-06, 08-20,
09-03, 09-17, 10-01, 10-15, 10-29, 11-12, 11-26, 12-10, 12-24
(`python scripts/retro_build.py --range 2017-01-08 2017-12-31 --every 14`),
published to the site archive on 2026-11-26 (all 26 pages verified
byte-identical live; 33,382 audit checks, 0 failed).

- **Real-time era extended.** `ERA_LAST_DAY` is now 2017-12-31: all twelve
  2017 editions of the revisions database carry CLI (LI_AA) and CP records
  for every economy used, so 2017 is built exactly as 2008–2016 are.
- **CLI editions** January, February and April–November 2017 are registered
  from dated public reports (Dow Jones Newswires in German via
  finanznachrichten.de, dpa-AFX via finanzen.net, City A.M., RTTNews, Fox
  Business, askanews, Bigpara, Uzmanpara, and the OECD's own releases of
  10 Jul and 7 Sep 2017 as hosted by Hellenic Shipping News and
  astrid-online.it), each page fetched and content-checked against the vintage
  (OECD area, euro area, US, UK or Türkiye). The February check uses the UK
  level only (City A.M.: "rose to 99.5"; vintage 99.46): the Reuters copy with
  more figures is not fetchable here. The August check uses Türkiye's figures
  (100.8 from 100.5, +0.30% m/m, +1.72% y/y; vintage 100.82, +0.30, +1.71),
  because the OECD-area and US values sit on rounding boundaries (100.05,
  99.65). The March and December 2017 releases (January and October data)
  have no retrievable dated report with figures, so they are *not*
  registered: 2017-03-19 keeps the February release and the March edition
  enters on 2017-04-02 through the edition-month-end rule; 2017-12-24 keeps
  November's. Release days: 11 Jan, 8 Feb,
  10 Apr, 10 May, 12 Jun, 10 Jul, 8 Aug, 7 Sep, 9 Oct, 9 Nov. No 2017 edition
  re-estimates the CLI history: OECD-area revisions to 2000–2013 values stay
  at or below 0.07; country-level component revisions reach 1.25 (Czechia,
  February) and 1.0 (UK, January), so no method note applies.
- **Policy.** The BIS daily histories show only real decisions in 2017 (no
  instrument switch). US instrument labels follow the target-range moves
  effective 16 Mar (0.75–1.00%), 15 Jun (1.00–1.25%) and 14 Dec 2017
  (1.25–1.50%; FOMC statements of 15 Mar, 14 Jun and 13 Dec).
- **Türkiye's funding rate** (`data/retro/policy_context.json`, new). The BIS
  series is the CBRT one-week repo rate, 8% all year, while the CBRT
  restricted funding at that rate from mid-January 2017 and supplied the
  market at the late liquidity window (LLW) lending rate (press release of
  13 Jan; MPC decisions raising the LLW lending rate to 11% on 24 Jan, 11.75%
  on 16 Mar, 12.25% on 26 Apr and 12.75% on 14 Dec 2017). Each fact is shown
  on the evidence page, with its source, only from its own date; it is a
  disclosure, not a model input (the policy level, carry and real rate stay
  on the BIS series). The CBRT's statement that one-week repo auctions were
  suspended from 12 Jan 2017 is in Inflation Report 2017-I, whose retrievable
  PDF was created on 1 Mar 2017; it is not cited.
- **Benchmarks** (`data/retro/benchmarks_2017.json`): current-year targets
  Türkiye 5 (CBRT policy document of 10 Dec 2014, para 1, restated with the
  ±2pp band on 6 Dec 2016), Brazil 4.5 ±1.5 (CMN Res. 4,419 of 25 Jun 2015),
  Colombia 3 ±1 (Board of 25 Nov 2016, cited from the bank's English release:
  the Spanish page sits behind a bot check), Indonesia 4 ±1 (PMK
  93/PMK.011/2014), Thailand 2.5 ±1.5 (Cabinet, 20 Dec 2016; Bank of Thailand
  and Fiscal Policy Office announcements of 21 Dec 2016), Canada 2% under the
  renewal of 24 Oct 2016 (now the agreement in force), India 5 (MPC of
  4 Oct 2016: 5 per cent by Q4 of the fiscal year ending in March). Changes
  announced during 2017: China ~3% re-set by the 5 Mar 2017 Government Work
  Report (recorded for its wording); India 5 → 4 from the MPC resolution of
  6 Apr 2017 (the medium-term 4% target, once the Q4 objective reached its
  horizon); Sweden's target variable CPI → CPIF (7 Sep 2017; value unchanged,
  recorded because it replaces the row's index and wording). The benchmark
  note no longer says that only one economy targets an index other than
  headline CPI. Value-unchanged reaffirmations are not recorded (the UK remit
  of 8 Mar 2017; New Zealand's unchanged Policy Targets Agreements of 6 Jun
  and 7 Nov 2017; Korea's 2%); no wording names a later year.

### 2018 editions

Biweekly grid continued: 2018-01-07, 01-21, 02-04, 02-18, 03-04, 03-18,
04-01, 04-15, 04-29, 05-13, 05-27, 06-10, 06-24, 07-08, 07-22, 08-05, 08-19,
09-02, 09-16, 09-30, 10-14, 10-28, 11-11, 11-25, 12-09, 12-23
(`python scripts/retro_build.py --range 2018-01-07 2018-12-31 --every 14`),
published to the site archive on 2026-11-26 (all 26 pages verified
byte-identical live; 33,480 audit checks, 0 failed).

- **Real-time era extended.** `ERA_LAST_DAY` is now 2018-12-31: all twelve
  2018 editions of the revisions database carry CLI (LI_AA) and CP records
  for every economy used. Before extending, the published 2017-12-24 page was
  rebuilt here and came out byte-identical.
- **CLI editions** January–December 2018 are all registered from dated
  public reports (dpa-AFX and Dow Jones Newswires in German via
  finanznachrichten.de and finanzen.net, Foreks via Uzmanpara, Bigpara, ECO /
  Lusa, and the International Economic and Financial Cooperation Center of
  China's Ministry of Finance), each page fetched and content-checked against
  the vintage. Release days: 15 Jan, 8 Feb, 8 Mar, 10 Apr, 14 May, 13 Jun,
  9 Jul, 8 Aug, 10 Sep, 8 Oct, 12 Nov, 10 Dec. Where the OECD-area value sits
  on a rounding boundary another quoted area is checked: January uses
  Türkiye's two-decimal figures (101.4, −0.29% m/m, +1.94% y/y; OECD area
  100.15), June uses Germany (100.3 from 100.5; the euro-area, French,
  Italian and UK values are on boundaries), September uses China (99.9,
  +0.32% m/m, from the Chinese Ministry of Finance note of 12 Sep; OECD-area
  level 99.65). The March check rests on Foreks flash headlines only (OECD
  area 100.1, previous 100.1; euro area, US and Türkiye also quoted). No 2018
  edition re-estimates the CLI history: OECD-area revisions to 2000–2014
  values stay at or below 0.08; country-level component revisions reach 1.26
  (Türkiye, April), so no method note applies.
- **Policy.** The BIS daily histories show only real decisions in 2018 except
  Türkiye's 1 Jun 2018 step (below). US instrument labels follow the
  target-range moves effective 22 Mar (1.50–1.75%), 14 Jun (1.75–2.00%),
  27 Sep (2.00–2.25%) and 20 Dec 2018 (2.25–2.50%; FOMC statements of 21 Mar,
  13 Jun, 26 Sep and 19 Dec). The Riksbank's December hike took effect on
  9 Jan of the following year and is in no 2018 edition.
- **Türkiye's funding regime** (`data/retro/policy_context.json`). The late
  liquidity window lending rate rose to 13.5% (MPC of 25 Apr) and 16.5%
  (23 May) while the one-week repo rate (the BIS series) stayed at 8%; on
  28 May the CBRT announced that from 1 Jun 2018 the one-week repo rate is its
  policy rate again, "equal to the current funding rate (16.50%)". The BIS
  series' 8% → 16.5% move on 1 Jun is therefore the end of the LLW regime, not
  a tightening on that day; the pages say so beside the policy decisions and
  in the instrument label. As in 2017 it is a disclosure, not a model input:
  the policy level, carry and real rate stay on the BIS series (17.75% from
  8 Jun and 24% from 14 Sep are ordinary decisions).
- **Benchmarks** (`data/retro/benchmarks_2018.json`): current-year targets
  Türkiye 5 (CBRT Monetary and Exchange Rate Policy for 2016, 9 Dec 2015,
  restated 6 Dec 2016), Brazil 4.5 ±1.5 (CMN Res. 4,499 of 30 Jun 2016),
  Colombia 3 (2–4%, Board of 24 Nov 2017), Indonesia 4 → 3.5 ±1 (PMK
  93/PMK.011/2014), Thailand 2.5 ±1.5 (agreed 29 Nov 2017, Cabinet approval of
  19 Dec 2017; the December 2017 Monetary Policy Report is shown only from its
  retrievable PDF's creation date, 21 Feb 2018). Changes announced during
  2018: Norway 2.5 → 2 under the Regulation on Monetary Policy of 2 Mar 2018,
  applied from Norges Bank's Monetary Policy Report 1/18 (15 Mar 2018), the
  earliest fetched source stating the figure (the Ministry of Finance release
  returns HTTP 403 and Norges Bank's release of 2 Mar does not state it), so
  2018-03-04 still uses 2.5; China's ~3% re-set by the 5 Mar 2018 Government
  Work Report and New Zealand's Policy Targets Agreement of 26 Mar 2018 (same
  1–3% with the 2% focus, adds supporting maximum sustainable employment),
  both recorded for their wording. Value-unchanged reaffirmations and targets
  set during 2018 for later years are not recorded; no wording names a later
  year.
- **Merged branch.** The 2018 editions were built on a parallel branch and
  merged here afterwards. Since then the 2018 late-liquidity-window items in
  `policy_context.json` carry `until` 2018-05-31, and the 28 May 2018 item
  uses the 2019 builder's wording, so a rebuilt June–December 2018 page
  differs from the published one in the Türkiye context lines only.

### 2019 editions

Biweekly grid continued: 2019-01-06, 01-20, 02-03, 02-17, 03-03, 03-17,
03-31, 04-14, 04-28, 05-12, 05-26, 06-09, 06-23, 07-07, 07-21, 08-04, 08-18,
09-01, 09-15, 09-29, 10-13, 10-27, 11-10, 11-24, 12-08, 12-22
(`python scripts/retro_build.py --range 2019-01-06 2019-12-31 --every 14`),
published to the site archive on 2026-11-26 (26 pages; 33,804 audit checks,
0 failed). 2018 was built on a parallel branch; its builder extension (US
target ranges of 2018, Türkiye's label from 1 Jun 2018) is included unchanged.

- **Real-time era extended.** `ERA_LAST_DAY` is now 2019-12-31: every
  edition of the revisions database from December 2018 to December 2019
  carries CLI (LI_AA) and CP records for all 21 economies used, so 2019 is
  built exactly as 2008–2017 are. A rebuilt 2017-12-24 page is
  byte-identical to the published one.
- **CLI editions** January–December 2019 are all registered from dated public
  reports, each page fetched and content-checked against the vintage:
  January–June from Dow Jones Newswires in German via finanznachrichten.de
  (OECD-area level and monthly change; January also CBC News, May also
  RTTNews), July–December from the Foreks wire on Uzmanpara/Milliyet
  (Türkiye's level, monthly and annual change, or the US level in December,
  because the OECD-area or other values sit on rounding boundaries). Every
  report is dated the release day: 14 Jan, 11 Feb, 11 Mar, 8 Apr, 13 May,
  11 Jun (10 Jun was Whit Monday), 8 Jul, 8 Aug, 9 Sep, 8 Oct, 12 Nov and
  9 Dec. Only 2019-01-06 uses the December 2018 edition through the
  edition-month-end rule. No 2019 edition re-estimates the CLI history
  (OECD-area revisions to 2000–2014 values at or below 0.05; country-level
  component revisions up to 0.81, New Zealand in December), so no method
  note applies.
- **India's CPI definition** (`CPI_DEFINITION_BIS` in `realtime.py`, new).
  The revisions database's India CP series is the CPI for Industrial Workers,
  not the all-India Combined CPI the RBI targets. Against the BIS Combined CPI,
  the two y/y rates differ by 1.4pp on average over 2015–2019 and by up to
  5.6pp (2019-08: 6.31% vs 3.38%), enough to invert India's inflation gap.
  The other 20 vintage series track the published CPI closely (mean gap at or
  below 0.22pp, the UK's CPIH-like series). From the 2019 editions India uses the
  present-day BIS Combined CPI behind the one-full-month gate, as the
  archive-era builder already does ("India: Combined CPI only"); the vintage
  index is listed as a considered candidate and the data notes say why.
  Earlier real-time editions are left as published. The same mismatch affects
  the 2014–2017 pages, where India's benchmark was already CPI-based.
- **China's instrument switch.** From 20 Aug 2019 the BIS series is the
  one-year loan prime rate (4.25%), replacing the one-year benchmark lending
  rate (4.35%; PBoC Announcement [2019] No. 15, posted 17 Aug 2019, cited in
  Chinese; the benchmark was retained). As for Türkiye in 2010 and Indonesia
  in 2016, earlier history is spliced (−0.10pp), so the switch is not counted
  as a cut. The LPR fixings of 20 Sep (4.20%) and 20 Nov (4.15%) are policy
  moves. The data note says that the first fixing was 0.10pp below the
  benchmark.
- **Instrument labels.** US target ranges follow the FOMC cuts effective
  1 Aug (2.00–2.25%), 19 Sep (1.75–2.00%) and 31 Oct 2019 (1.50–1.75%;
  statements and implementation notes of 31 Jul, 18 Sep and 30 Oct).
  Switzerland's label names the SNB policy rate (−0.75%) from 13 Jun 2019,
  which replaced the three-month Libor target range at the same level.
- **Türkiye's funding rate** (`data/retro/policy_context.json`). Items may now
  carry `until`, the last day the arrangement they describe applied. The 2017
  late-liquidity-window items end on 2018-05-31 and no longer appear. Four
  items are new, each shown from its source's own date:
  - The CBRT's simplification of 28 May 2018: from 1 Jun 2018 the one-week
    repo rate is again the funding rate, set equal to the 16.5% funding rate
    then in force. This is why the BIS series moves from 8% to 16.5%.
  - The one-week repo auction suspensions of 22 Mar and 9 May 2019 (CBRT
    press releases: "for a period of time"). While they lasted, marginal
    funding was at the 25.5% overnight lending rate, against the 24% policy
    rate.
  - The 8 Apr resumption, first documented by ING on 18 Apr. The 2019-04-14
    page therefore shows only the suspension.
  - The 21 May resumption (Reuters via Arab News).
  These are disclosures, not model inputs.
- **Benchmarks** (`data/retro/benchmarks_2019.json`): current-year targets
  Türkiye 5 (CBRT Monetary and Exchange Rate Policy for 2019, 5 Dec 2018),
  Brazil 4.25 ±1.5 (CMN Res. 4,582 of 29 Jun 2017), Indonesia 3.5 ±1 (PMK
  124/PMK.010/2017), Colombia 3 (2–4%, Board of 30 Nov 2018), Thailand 2.5 ±1.5
  (Cabinet and MPC, 25 Dec 2018), Korea 2 (Monetary Policy Board, 26 Dec 2018:
  the target from 2019 with no fixed period), India 4 (MPC, 6 Apr 2017,
  restated through 2019). Changes announced during 2018 carried in: Norway
  2.5 → 2 (Regulation of 2 Mar 2018), New Zealand's Policy Targets Agreement of
  26 Mar 2018 (value unchanged), China ~3% (Government Work Report, 5 Mar 2018).
  Changes announced during 2019 (both value-unchanged, recorded for their
  wording): New Zealand's Remit for the Monetary Policy Committee (14 Feb
  2019), China ~3% (5 Mar 2019). The FOMC's amended statement of 29 Jan 2019
  and the UK remit of 29 Oct 2018 are value-unchanged reaffirmations and are
  not recorded; no wording names a later year.

### 2020 editions

Biweekly grid continued: 2020-01-05, 01-19, 02-02, 02-16, 03-01, 03-15,
03-29, 04-12, 04-26, 05-10, 05-24, 06-07, 06-21, 07-05, 07-19, 08-02, 08-16,
08-30, 09-13, 09-27, 10-11, 10-25, 11-08, 11-22, 12-06, 12-20
(`python scripts/retro_build.py --range 2020-01-05 2020-12-31 --every 14`),
published to the site archive on 2026-11-27 (all 26 pages verified
byte-identical live; 35,201 audit checks, 0 failed). The parallel 2018 and
2019 branches were merged first; a rebuilt 2019-12-22 page is byte-identical
to the published one.

- **Real-time era extended.** `ERA_LAST_DAY` is now 2020-12-31. Every 2020
  edition of the revisions database carries CP for all 21 economies; the
  March 2020 edition carries no CLI at all, and from April some economies'
  CLIs are left out of single releases (below).
- **CLI editions** January, February and April–December 2020 are registered
  from dated public reports, each page fetched and content-checked against the
  vintage. The earliest dated report is always the Foreks wire on
  Uzmanpara/Milliyet (flash headlines or tables stamped the release minute);
  Dow Jones Newswires or dpa-AFX in German via finanznachrichten.de follow
  within the hour (from July with two-decimal levels equal to the vintage).
  Release days: 13 Jan, 10 Feb, 8 Apr, 12 May, 10 Jun (with the Economic
  Outlook, 11:01 Istanbul time), 9 Jul, 10 Aug, 8 Sep, 8 Oct, 9 Nov, 8 Dec.
  Checks use China (January), the OECD area (February, April, July, October,
  December), Türkiye (May: 79.3, −20.75% m/m, −18.94% y/y), the euro area
  (June), the US (August) and Germany (September, November), avoiding values
  on rounding boundaries. The Foreks flashes' "previous" values in August,
  September and November are the earlier edition's unrevised figures; no check
  uses them. Only 2020-01-05 uses the December 2019 edition.
- **Percent content checks.** A register `content_check` may now give
  `reported_mom_pct` / `reported_yoy_pct` (compared at the report's own
  precision, one unit of tolerance) and `level_dp` (how the reported level is
  printed): with Türkiye's CLI at 79, index-point and percent changes diverge.
  Earlier entries are checked and printed exactly as before.
- **Cancelled March release.** `NO_CLI_EDITIONS` gains 202003: the OECD
  "cancelled its scheduled monthly release of composite leading indicators
  (CLI), because of the rapid spread of the coronavirus outbreak" (Argus Media,
  9 Mar 2020; OECD notice reposted by Scoop). 2020-03-15 and 2020-03-29 keep the
  February release (through December 2019) and cite the notice
  (`NO_CLI_NOTICES`, new). The April release (8 Apr) already covered March:
  from then on the latest reference month is one month before the release, not
  two.
- **Economies left out of a release** (`CLI_ABSENT_FALLBACK_FROM`, new; 2020
  editions only, so earlier pages rebuild unchanged). The April edition carries
  no CLI for Switzerland, Mexico, Norway or New Zealand, the May edition none
  for South Africa, and no edition from April on one for New Zealand. Such an
  area takes the newest earlier eligible edition carrying it, at most three
  editions back (`CLI_ABSENT_DEPTH`), capped at that release's reference month,
  and the data notes say so; beyond that it has no growth input (New Zealand
  from 2020-06-21: 20 growth inputs). `retro_audit.py` accepts the older
  edition only for an area absent from the eligible edition's own bytes.
  Mexico's CLI stops at May 2020 and Australia's at March 2020 in several
  editions; both are used as published.
- **Caution note.** April–July pages cite the OECD's warning that the CLI's
  predictive power was for the moment limited and that the size of its fall
  did not measure the depth of the contraction (dpa-AFX, 8 Apr 2020);
  August–December pages its repeated caution (Dow Jones, 10 Aug 2020). No 2020
  edition re-estimates the CLI history (OECD-area revisions to 2000–2016
  values at or below 0.37, August; country components up to 1.88, India,
  October), so no method note applies.
- **Policy.** US labels follow the emergency cuts effective 4 Mar (1.00–1.25%)
  and 16 Mar 2020 (0–0.25%; FOMC statements of 3 and 15 Mar; the second came
  after the 2020-03-15 cutoff). `DAILY_ERRATA` (new): Thailand's BIS daily
  series shows 0.50% on 6 May 2020 only, between 0.75% on 5 and 7 May (the MPC
  cut to 0.50% on 20 May); the day is read at 0.75% and the page says so. No
  other 2020 move needed a correction or an instrument splice.
- **Türkiye's funding rate** (`data/retro/policy_context.json`). The four 2019
  auction items now carry `until` 2019-12-31 (shown in 2019 editions only). From
  7 Aug 2020 the CBRT suspended one-week repo auctions (first documented by
  Anadolu Agency via Hürriyet Daily News on 7 Aug; confirmed by the CBRT's MPC
  summary of 27 Aug), cut primary-dealer limits to zero (11 Aug), halved
  (18 Aug) and later zeroed (2 Nov) banks' overnight borrowing limits and
  raised the corridor (24 Sep, ING; late liquidity window 13.25% → 14.75% on
  22 Oct, Reuters via Arab News, average funding cost 12.52% against a 10.25%
  policy rate). These items carry `until` 2020-11-19; the 19 Nov decision
  (15%, all funding via one-week repo auctions from 20 Nov) is shown from its
  date, and the instrument label follows. Disclosures, not model inputs.
- **Benchmarks** (`data/retro/benchmarks_2020.json`): current-year targets
  Brazil 4.00 ±1.5 (CMN Res. 4,582, art. 1 II), Indonesia 3 ±1 (PMK
  124/PMK.010/2017), Thailand 2.0, the midpoint of the 1–3% headline range
  (Cabinet, 24 Dec 2019; BoT MPC announcement No. 3/2562), Türkiye 5 (CBRT
  Monetary and Exchange Rate Policy for 2020, 5 Dec 2019; its "interim targets"
  sentence is recorded in the wording, the agreed 5% is used), Colombia 3
  (2–4%, Board of 25 Nov 2019); Korea 2 and India 4 carried. Changes announced
  during 2020: Chile's updated framework document (11 Feb, reported 12 Feb;
  value unchanged, wording replaced), China ~3 → ~3.5% from the Report on the
  Work of the Government of 22 May (applies from 2020-05-24), the FOMC's
  amended statement of 27 Aug ("inflation that averages 2 percent over time";
  value unchanged, cited from the dated press release). Value-unchanged
  reaffirmations (UK remit of 11 Mar 2020) are not recorded; no wording names a
  later year.

### 2021 editions

Biweekly grid continued: 2021-01-03, 01-17, 01-31, 02-14, 02-28, 03-14,
03-28, 04-11, 04-25, 05-09, 05-23, 06-06, 06-20, 07-04, 07-18, 08-01, 08-15,
08-29, 09-12, 09-26, 10-10, 10-24, 11-07, 11-21, 12-05, 12-19
(`python scripts/retro_build.py --range 2021-01-03 2021-12-31 --every 14`),
published to the site archive on 2026-11-27 (all 26 pages verified
byte-identical live; 33,604 audit checks, 0 failed). A rebuilt 2020-12-20 page is byte-identical to the published one,
and rebuilt 2021 pages are byte-identical to the first build.

- **Real-time era extended.** `ERA_LAST_DAY` is now 2021-12-31. Every 2021
  edition of the revisions database carries CP for all 21 economies and the
  CLI for all of them except New Zealand (absent since April 2020: no growth
  input, 20 growth inputs).
- **CLI editions** January–December 2021 are registered from dated public
  reports, each page fetched and content-checked against the vintage: the
  Foreks flashes on Uzmanpara/Milliyet (stamped the release minute, 12:00
  Paris time) and Dow Jones Newswires in German via finanznachrichten.de
  within the hour. Release days: 14 Jan, 9 Feb, 9 Mar, 13 Apr, 11 May, 9 Jun,
  12 Jul, 10 Aug, 14 Sep (not the 8th), 12 Oct, 10 Nov, 9 Dec. Checks use
  China (January, September), the OECD area (February, March, July, August,
  October), the euro area (April, June), Germany (May, December) and the US
  (November), each with the reported percent change and away from rounding
  boundaries (the OECD area's December 2020 level is 99.45). No check uses a
  figure the reports misprint: the Foreks month labels in January (October)
  and August (June), and Dow Jones' Japan 99.0 (February), China 103.30 (May),
  euro area 100.4 (October) and OECD area 110.7 (December). Only 2021-01-03
  uses the December 2020 edition.
- **Caution notes.** January–August pages cite the OECD's own release text
  as reprinted by Scoop (dated the next day, New Zealand time): the CLIs
  "should be interpreted with care" and their magnitude read as the strength
  of the signal. No later statement was retrieved, so September–December
  pages say that the January–August releases advised caution.
- **Per-area CLI notes** (`area_notes` in the register, new; only the April
  2021 entry carries one, so earlier pages rebuild unchanged). Mexico's CLI
  stops at 2020-05 in the August 2020 to March 2021 editions: it is used
  until it is more than 9 months older than the anchor month, so the
  2021-04-11 page has 19 clocks. The April 2021 edition carries it through
  2021-03 again with its whole history re-estimated (2007 values revised by
  4.3 points on average, April 2020 from 98.4 to 86.4); pages using that
  edition say so. Otherwise no 2021 edition re-estimates the CLI history
  (OECD-area revisions to 2000–2017 values at or below 0.19, April).
- **Policy.** No BIS daily errata, bridges or instrument splices were needed:
  every 2021 move in the daily histories is an announced decision (Brazil's
  seven hikes from 17 Mar; Türkiye's hike to 19% on 18 Mar and cuts from
  23 Sep; Hungary, Czechia, Poland, Chile, Colombia, Mexico, Korea, Norway,
  New Zealand, South Africa and the UK hiking from mid-year; the cuts of
  Mexico, effective 12 Feb, and Indonesia, 18 Feb). US labels stay at the 0–0.25% range. China's 5bp LPR cut of
  20 Dec 2021 falls after the last edition.
- **Hungary's one-week deposit rate** (`data/retro/policy_context.json`;
  disclosures, not model inputs). The BIS series is the MNB base rate; from
  the tender of 18 Nov 2021 the MNB set its one-week deposit rate above it
  (2.5%, then 2.9%, 3.1%, 3.3% and 3.6%, 40–120bp over the base rate). Shown
  from each source's own date: the Monetary Council press releases of 16 Nov,
  30 Nov and 14 Dec ("Changes to the one-week central bank deposit rate will
  feed into the MNB's tightening cycle for a sustained period") and the dated
  Budapest Business Journal (MTI) tender reports. The instrument label names
  it from the 2021-11-21 page. The smaller spread of September 2020–June 2021
  (0.75% against 0.60%) is not disclosed: no dated public source for that level
  was retrieved. Türkiye's 19 Nov 2020 item still applies (one-week repo
  funding throughout 2021).
- **Benchmarks** (`data/retro/benchmarks_2021.json`): current-year targets
  Brazil 3.75 ±1.5 (CMN Res. 4,671 of 26 Jun 2018), Indonesia 3 ±1 (PMK
  124/PMK.010/2017, Art. 2(3)(c)), Thailand 2.0, the midpoint of the 1–3%
  range (Cabinet, 22 Dec 2020; the BoT's PDF is cited only from its 1 Feb 2021
  modification), Türkiye 5, now the "medium-term" target (CBRT Monetary and
  Exchange Rate Policy for 2021, 16 Dec 2020, Turkish PDF; the English PDF from
  its 14 Jan 2021 creation), Colombia 3 (2–4%, Board of 27 Nov 2020, cited from
  same-day reports: banrep.gov.co sits behind a bot check). Changes announced
  during 2021: New Zealand's replacement remit (Gazette, 25 Feb; value
  unchanged, wording replaced), China ~3.5 → ~3% (Report on the Work of the
  Government, 5 Mar; applies from 2021-03-14), India's re-notified 4% ±2
  target (31 Mar; value unchanged), the euro area 1.9 → 2.0 from the ECB's
  symmetric target of 8 Jul (applies from 2021-07-11; the register's general
  note may now be restated from a date, `note_changes`, so the 1.9%
  convention is described only on earlier pages). Value-unchanged
  reaffirmations (FOMC 26 Jan, UK remits of 3 Mar and 27 Oct) and targets set
  for later years (Canada's renewal of 13 Dec, Colombia's Board of 26 Nov) are
  not recorded; no wording names a later year.

### 2022 editions

Biweekly grid continued: 2022-01-02, 01-16, 01-30, 02-13, 02-27, 03-13,
03-27, 04-10, 04-24, 05-08, 05-22, 06-05, 06-19, 07-03, 07-17, 07-31, 08-14,
08-28, 09-11, 09-25, 10-09, 10-23, 11-06, 11-20, 12-04, 12-18
(`python scripts/retro_build.py --range 2022-01-02 2022-12-31 --every 14`),
published to the site archive on 2026-11-27 (all 26 pages verified
byte-identical live; index 440 archived reports; 36,412 audit checks, 0 failed,
and no abbreviated date such as "17 Mar 2022" after any cutoff). A rebuilt
2021-12-19 page is byte-identical to the published one, and rebuilt 2022 pages
are byte-identical to the first build. Every edition has 20 clocks.

- **Real-time era extended.** `ERA_LAST_DAY` is now 2022-12-31. Every 2022
  edition of the revisions database carries the CLI for all economies except
  New Zealand (absent since April 2020; the February 2022 release says its CLI
  "is currently under revision and could not be updated this month": no growth
  input, 20 growth inputs) and CP for all 21 economies, but see Japan below.
- **Japan's CPI** (`CPI_TRUNCATED_BIS`, new; only from the July 2022 CPI
  edition, so earlier pages rebuild unchanged). Japan's CP index runs to
  2022-04 in the June 2022 edition but ends at 2021-06 in every edition from
  July 2022 on, which would freeze Japan's inflation at mid-2021 and drop its
  clock once stale. From the 2022-08-14 page the present-day BIS CPI behind the
  one-full-month gate is used instead (as for India), the vintage index is shown
  as a considered candidate, and the data notes say so.
- **CLI editions** January–December 2022 are registered from dated public
  reports, each page fetched and content-checked against the vintage: Foreks
  flashes on Uzmanpara/Milliyet (14:00 +03:00 in winter, 13:00 in summer, i.e.
  12:00 Paris) and Dow Jones Newswires in German via finanznachrichten.de.
  March has Foreks flashes only (no Dow Jones story); July has no surviving
  Foreks flash (Dow Jones and Börsen-Zeitung); April adds Lusa's two-decimal
  levels (Observador). Release days: 17 Jan (not the 12th, so the 2022-01-16
  page still uses the December 2021 edition), 9 Feb, 9 Mar (the February
  release had announced 8 Mar), 11 Apr, 10 May, 13 Jun, 11 Jul, 9 Aug, 12 Sep,
  11 Oct, 9 Nov, 8 Dec. Checks use China (January), the OECD area (February,
  March and September at the level only, July), the euro area (April at two
  decimals, August, October), Germany (May, November) and the US (June,
  December); every reported value matches the vintage exactly at the report's
  precision. No check uses a figure the reports misprint (Dow Jones' US level
  99.0 in January; Germany's July comparator 98.8 in September). Uzmanpara
  rewrites years inside some 2022 headlines; the OECD flashes carry no year and
  are dated by their timestamps.
- **Caution notes.** Each page cites its own release's caution that the CLIs be
  interpreted with care (Omicron in January–March; the war in Ukraine, COVID-19
  and high inflation from April): January from Lusa's report, February and
  March from the OECD's February release PDF (no same-day March text was
  retrieved), April from Hellenic Shipping News' reprint (13 Apr), May–December
  from Mirage News reprints. The December release was "the final OECD Composite
  Leading Indicators news release in the current format" (the CLIs continue for
  a reduced set of countries); the 2022-12-18 page says so without naming the
  later date. No 2022 edition re-estimates the CLI history (OECD-area revisions
  to pre-2019 values at most 0.13, May; country components up to 1.29, India,
  April), so no method note applies.
- **Policy.** No BIS daily errata, bridges or instrument splices were needed:
  every 2022 move in the daily histories is an announced decision (the global
  hiking cycle: US seven hikes from 17 Mar, euro area from 27 Jul, Switzerland
  out of negative rates on 23 Sep; Türkiye's cuts from 19 Aug; China's LPR cuts).
  `DAILY_DATE_FIX` (new): the BIS daily series carries China's one-year LPR cut
  to 3.65% from Saturday 20 Aug 2022, but the fixing was published on Monday
  22 Aug (Xinhua via gov.cn); the two days are read at 3.70%, the change is dated
  22 Aug, and the page says so. US labels follow the seven 2022 target ranges
  (0.25–0.50% from 17 Mar to 4.25–4.50% from 15 Dec). The ECB's hike effective
  21 Dec and Indonesia's of 22 Dec fall after the last edition.
- **Hungary's operational rates** (`data/retro/policy_context.json`;
  disclosures, not model inputs). The one-week deposit rate stayed above the
  base rate (40–245bp) until the MNB raised it to the base rate at the tender of
  30 Jun 2022 (Monetary Council, 28 Jun); from 14 Oct 2022 the effective
  marginal rate was the 18% overnight deposit quick tender against the 13% base
  rate, and one-week deposit tenders stopped from 17 Oct (MNB press releases,
  Budapest Business Journal/MTI tender reports, Portfolio, ING Think, Reuters).
  Items now carry `until` so each page shows the current tender level and the
  latest Council statement (2021 pages unchanged); the instrument label follows
  the alignment and the October regime.
- **Benchmarks** (`data/retro/benchmarks_2022.json`): current-year targets
  Brazil 3.75 → 3.50 ±1.5 (CMN Res. 4,724 of 27 Jun 2019, DOU 1 Jul 2019),
  Indonesia 3 ±1 (PMK 101/PMK.010/2021, Art. 2(3)(a)), Thailand 2.0, the midpoint
  of the 1–3% range (Cabinet, 14 Dec 2021; the BoT's scanned announcement cited
  from its file's creation on 23 Dec 2021), Türkiye 5 (CBRT Monetary and
  Exchange Rate Policy for 2022, 29 Dec 2021), Colombia 3 (2–4%, Board of
  26 Nov 2021, cited from same-day reports), Canada's renewed framework of
  13 Dec 2021 (value unchanged, wording replaced). One change announced during
  2022: China's ~3% objective from the Report on the Work of the Government of
  5 Mar (value unchanged; applies from 2022-03-13). Value-unchanged
  reaffirmations (FOMC 25 Jan, UK remit of 17 Nov, the SNB's strategy review),
  targets for later years (Brazil's of 23 Jun 2022) and announcements after the
  last cutoff (Korea 20 Dec, Thailand 27 Dec, Türkiye 30 Dec) are not recorded;
  no wording names a later year.

### 2023 editions

Biweekly grid continued: 2023-01-01, 01-15, 01-29, 02-12, 02-26, 03-12,
03-26, 04-09, 04-23, 05-07, 05-21, 06-04, 06-18, 07-02, 07-16, 07-30, 08-13,
08-27, 09-10, 09-24, 10-08, 10-22, 11-05, 11-19, 12-03, 12-17, 12-31
(`python scripts/retro_build.py --range 2023-01-01 2023-12-31 --every 14`),
published to the site archive on 2026-11-27 (all 27 pages verified
byte-identical live; index 467 archived reports; 37,985 audit checks,
0 failed, and no abbreviated date such as "27 Sep 2023" after any cutoff).
Rebuilt 2022-12-04 and 2022-12-18 pages are byte-identical to the published ones.
2023-01-01 still uses the December 2022 CLI edition (20 clocks); every later
edition has 23 clocks.

- **Real-time era extended.** `ERA_LAST_DAY` is now 2023-12-31.
- **Reduced CLI set.** The OECD's release of 8 Dec 2022 was its last CLI news
  release in that format ("The CLIs will continue to be estimated for a reduced
  set of countries"). From the January 2023 edition the revisions database
  carries the CLI only for the 13 economies the archive-era builder also uses
  (US, Japan, UK, Canada, Australia, China, India, Brazil, Mexico, South Africa,
  Türkiye, Indonesia, Korea); the euro area, Switzerland, Sweden, Norway, Poland,
  Hungary and Czechia drop out, and no OECD-area aggregate is carried.
- **Business confidence for the other ten** (`BCI_FROM_CLI_EDITION`,
  `BCI_AREAS`; only editions whose CLI edition is 202301 or later, so earlier
  pages rebuild unchanged). The euro area (EA19), Switzerland, Sweden, Norway,
  New Zealand, Poland, Hungary, Czechia, Chile and Colombia take the OECD
  business confidence indicator BSCICP03 (amplitude adjusted, long-term
  average 100: the CLI's own scale, used as published), from the newest
  DBnomics git commit of the OECD `MEI_CLI` dataset committed before the
  cutoff: the live pipeline's own fallback, labelled on every page as a
  survey-based proxy, not a CLI. New Zealand (no CLI since 2020), Chile and
  Colombia (not in the revisions database) thus regain a growth input; Thailand
  has none. Norway's and New Zealand's surveys are quarterly and lag by up to
  three months, within the 9-month staleness rule.
- **CLI editions dated by DBnomics commits.** With no news releases there are
  no wire reports to date the 2023 editions. Each one is registered from the
  earliest DBnomics `MEI_CLI` commit carrying the same CLIs (basis "dated DBnomics
  git commit carrying this edition's figures", `dbnomics_check` in the
  register): for all 13 economies the commit's latest reference month equals the
  edition's, and all ~7,000–7,200 overlapping values agree within rounding (the
  database prints two decimals, DBnomics five; largest difference 0.005).
  `retro_audit.py` re-runs that check and re-reads the commit's timestamps from
  GitLab (both before the cutoff, Warsaw date equal to the public-by date).
  Public-by days (Europe/Warsaw): 10 Jan, 7 Feb, 7 Mar, 7 Apr (committed 6 Apr
  22:22 UTC), 6 May, 8 Jun, 6 Jul, 5 Aug, 7 Sep, 6 Oct, 9 Nov, 7 Dec. No 2023
  edition re-estimates the CLI history (revisions to pre-2019 values at most
  0.87, Korea, March), so no method note applies.
- **Euro-area CPI code** (`EA20_FROM`). The January–March 2023 editions carry
  the euro-area CPI as EA19; from the April 2023 edition only as EA20 (Croatia
  joined on 1 January 2023). The aggregate is used as published; the data notes
  say which. Japan's CPI stays on the gated BIS history (`CPI_TRUNCATED_BIS`; the
  vintage index still stops at 2021-06), India's on the Combined CPI.
- **Policy.** No BIS daily errata, bridges or instrument splices were needed:
  every 2023 move in the daily histories is an announced decision (the last
  hikes of the cycle: US to 5.25–5.50% from 27 Jul, euro area to a 4.50% main
  refinancing rate from 20 Sep, UK, Norway, Sweden, Switzerland; Türkiye's hikes from 8.5%
  to 42.5% from 23 Jun; the first cuts: Chile from 31 Jul, Brazil from 3 Aug,
  Poland from 7 Sep, Hungary's base rate from 25 Oct, Czechia 22 Dec, Colombia
  20 Dec). `DAILY_DATE_FIX` gains China's one-year LPR cut to 3.45%, which the
  BIS series carries from Sunday 20 Aug 2023; the fixing was published on Monday
  21 Aug (Xinhua via People's Daily Online), so the change is dated 21 Aug. US
  labels follow the four 2023 target ranges (4.50–4.75% from 2 Feb to
  5.25–5.50% from 27 Jul).
- **Hungary's operational rates** (`data/retro/policy_context.json`;
  disclosures, not model inputs). The 18% overnight deposit quick tender stayed
  the effective rate against the 13% base rate until the Council of 23 May
  (18 → 17% from the next day), then fell in 100bp steps (20 Jun, 25 Jul,
  29 Aug); on 25 Apr only the corridor top was lowered (25 → 20.5%). On 26 Sep
  the effective rate was cut to the 13% base rate, which "will become the
  effective central bank interest rate", with a symmetric ±100bp corridor; the
  base-rate cuts of 24 Oct, 21 Nov and 19 Dec (to 10.75%) follow. Each page
  shows the Council press release and ING Think's same-day review in force at
  its cutoff (21 new items; the open 2022 items now carry `until` dates from
  2022-12-19 on, so 2022 pages are unchanged); the instrument label follows the
  quick-tender, step-down and re-unified regimes. Türkiye: no item added. Every
  2023 CBRT decision defines the policy rate as the one-week repo rate; dated
  commentary (TEPAV, Dec 2023) that lira swap funding ran slightly below it is
  not a CBRT statement and is not disclosed.
- **Benchmarks** (`data/retro/benchmarks_2023.json`): current-year targets
  Brazil 3.50 → 3.25 ±1.5 (CMN Res. 4,831 of 25 Jun 2020, DOU 26 Jun 2020),
  Indonesia 3 ±1 (PMK 101/PMK.010/2021, Art. 2(3)(b)), Thailand 2.0, the
  midpoint of the 1–3% range (Cabinet, 27 Dec 2022; the BoT's scanned
  announcement cited from its file's creation on 3 Jan 2023), Türkiye 5, the
  medium-term target (CBRT Monetary Policy and Liraization Strategy for 2023,
  30 Dec 2022), Colombia 3 (Board of 25 Nov 2022), Korea 2 (unchanged by the
  BoK's review of 20 Dec 2022). Changes announced during 2023, all value-
  unchanged and recorded because they replace the row's wording: China's ~3%
  (Report on the Work of the Government, 5 Mar; applies from 2023-03-12), New
  Zealand's new remit (27 Jun; from 2023-07-02) and amended remit dropping the
  employment objective (13 Dec; from 2023-12-17), Australia's new Statement on
  the Conduct of Monetary Policy (8 Dec; from 2023-12-17). Value-unchanged
  reaffirmations (FOMC 31 Jan, UK remit of 22 Nov, the BoJ's review decision of
  28 Apr, the new Riksbank Act) and targets for later years (Brazil's CMN of
  29 Jun, Thailand's Cabinet of 26 Dec, the CBRT's text of 29 Dec, Colombia's
  Board of 30 Nov) are not recorded; no wording names a later year.

### 2024 editions

Biweekly grid continued: 2024-01-14, 01-28, 02-11, 02-25, 03-10, 03-24,
04-07, 04-21, 05-05, 05-19, 06-02, 06-16, 06-30, 07-14, 07-28, 08-11, 08-25,
09-08, 09-22, 10-06, 10-20, 11-03, 11-17, 12-01, 12-15, 12-29
(`python scripts/retro_build.py --range 2024-01-14 2024-12-31 --every 14`),
published to the site archive on 2026-11-27 (all 26 pages verified
byte-identical live; index 493 archived reports; 35,397 audit checks,
0 failed, and no abbreviated date such as "18 Sep 2024" after any cutoff).
Rebuilt 2023-12-17 and 2023-12-31 pages are byte-identical to the published ones.
Every 2024 edition has 23 clocks. The 2024-12-29 edition is followed a week
later by the live grid's first edition, 2025-01-05.

- **Real-time era extended.** `ERA_LAST_DAY` is now 2024-12-31. The archive-era
  builder cannot take over earlier: DBnomics' OECD archive has no commit between
  2024-01-13 and 2024-10-27, and its BIS CPI archive none before June 2024.
- **CLI editions dated by ALFRED vintages** (`alfred_check` in the register). With
  no news releases and no DBnomics conversions, each 2024 edition is registered
  from the first ALFRED vintage of FRED's copies of the 13 CLIs
  (`<ISO3>LOLITOAASTSAM`) that carries its latest reference month: for all 13
  economies the vintage's latest month equals the edition's, all ~7,200–7,400
  overlapping values agree within rounding (largest difference 0.005), ALFRED
  serves it as that day's vintage, and the previous day's vintage does not yet
  carry the month. ALFRED vintage dates are US Central time, so public-by is the
  next day: 12 Jan, 11 Apr, 16 May, 18 Jun, 17 Sep, 16 Oct, 16 Nov, 17 Dec.
  `retro_audit.py` re-runs the check. The February, March and July releases never
  appear as an ALFRED vintage (FRED next updated with the following release), so
  those editions enter by the edition-month-end rule (2024-03-10, 04-07, 08-11).
- **No CLI in the August 2024 edition** (`NO_CLI_EDITIONS`): the database query
  returns no records for any area, and no ALFRED vintage ever carried July 2024 as
  its newest month. The 2024-08-25 and 2024-09-08 editions keep the July edition;
  the latter says so in its data notes.
- **Business confidence for the other ten** (`BCI_GATED_FROM`, `bts_gated`). The
  DBnomics MEI_CLI archive ends with its commit of 2024-01-13 (BSCICP03 through
  December 2023). From the 2024 editions a second candidate competes for the euro
  area, Switzerland, Sweden, Norway, New Zealand, Poland, Hungary, Czechia, Chile
  and Colombia: the OECD business-tendency-survey composite confidence balance for
  manufacturing (`DSD_STES@DF_BTS`, `BCICP.PB.C`; euro area as EA20, Norway and New
  Zealand quarterly), present-day history requested only through the
  one-full-month gate and normalized to 100 + its deviation from its own
  pre-cutoff average, the archive-era builder's method. The fresher candidate is
  used, the dated archive on a tie: the archive for all ten in 2024-01-14 and
  01-28; the gated balance for Norway, New Zealand and Colombia in 2024-02-11 and
  02-25, and for all ten from 2024-03-10.
  Seasonal-adjustment revisions of the balances are not removed (disclosed).
- **REER from ALFRED vintages** (`REER_ALFRED_FROM`). ALFRED holds vintages of
  FRED's copies of the BIS broad REERs (`RB<cc>BIS`) throughout 2024, so all 24
  REER histories are the Friday vintage before each cutoff instead of present-day
  BIS histories behind a gate (the fallback, unused). The page text says so.
- **Mexico's CPI** (`CPI_TRUNCATED_BIS`): from the October 2024 edition the
  database's MEX index stops at 2024-07, so the 2024-11-03 to 12-29 editions use
  the gated BIS history (latest 2024-09 / 2024-10), the vintage shown as a
  candidate. Japan stays on BIS, India on the Combined CPI.
- **Euro-area instrument switch** (`INSTRUMENT_SWITCH["XM"]`, `new_before`). The BIS
  series is the MRO rate until 17 Sep 2024 and the deposit facility rate from
  18 Sep 2024 (4.25% → 3.50%). That day also carries a real decision (DFR 3.75% →
  3.50%, ECB 12 Sep 2024; the MRO–DFR spread narrowed to 15bp under the
  operational framework of 13 Mar 2024), so earlier history is spliced by −0.50pp,
  the DFR's level before the switch, not by the switch-day jump: the June and
  September 2024 moves read 4.00 → 3.75 and 3.75 → 3.50. Exact for the five years
  before the switch (the spread was 50bp from 18 Sep 2019); disclosed on the page.
- **Policy labels.** US target ranges 4.75–5.00% from 19 Sep, 4.50–4.75% from
  8 Nov, 4.25–4.50% from 19 Dec 2024; Japan's uncollateralized overnight call rate
  at around 0–0.1% from 21 Mar 2024 (BIS midpoint 0.05%, after −0.1%) and around
  0.25% from 1 Aug 2024 (BoJ statements of 19 Mar and 31 Jul, quoted as written).
  China's 2024 LPR cuts were published on the fixing days (Mon 22 Jul, Mon 21 Oct;
  Xinhua), so no `DAILY_DATE_FIX` is needed; every other 2024 move is an announced
  decision. Hungary kept the symmetric ±100bp corridor around the base rate, still
  the effective rate, all year (cuts from 10.75% to 6.50%): no new context item.
- **Benchmarks** (`data/retro/benchmarks_2024.json`): current-year targets
  Brazil 3.25 → 3.0 ±1.5 (CMN Res. 4,918 of 24 Jun 2021, DOU 25 Jun 2021; no
  normativos PDF exists, so the BCB record and Agência Brasil are cited), Indonesia
  3 → 2.5 ±1 (PMK 101/PMK.010/2021, Art. 2(3)(c)), Thailand 2.0, the midpoint of the
  1–3% range (Cabinet, 26 Dec 2023; BoT MPC announcement No. 2/2566), Türkiye 5
  (CBRT Monetary Policy for 2024, 29 Dec 2023; the current PDFs were re-saved on
  26 Dec 2024, so Bloomberg HT's same-day report corroborates the text), Colombia 3
  (Board of 30 Nov 2023), Korea 2 (carried). One change during 2024, value
  unchanged: China's ~3% (Report on the Work of the Government, 5 Mar; applies from
  2024-03-10). Value-unchanged reaffirmations (FOMC, the BoJ's exit from negative
  rates "with the price stability target of 2 percent", the UK remit of 14 Nov, the
  BoK's review of 18 Dec) and targets set during 2024 for later years (Brazil's
  continuous target, Indonesia's PMK 31/2024, Poland's guidelines, Thailand's
  Cabinet of 24 Dec, the CBRT's text of 25 Dec, Colombia's Board of 29 Nov) are not
  recorded; no wording names a later year.

`retro_scorecard.py` (ex-post, deliberately using later data; never an edition input)
scores the published calls: the top three FX crosses held 3 months (BIS daily spot
plus the stated policy-rate differential) and the ★★/★★★ curve calls (3-month change
of 10y minus policy). For the 2019 editions: top cross 62% hit, +1.2% per 3 months
(+2.2% through the 2019-11-10 edition; the 2019-12-08 and 12-22 holds ran into the
February–March 2020 sell-off, MXN/JPY −6% and −21%); ★★★ curve calls 13/15 right,
★★ calls a coin flip (44%). For the 2020 editions: the four January–February
top crosses (long MXN/JPY) lost 23–26% each into the March 2020 crash, a supply
shock the endogenous cycle cannot see (all-cross mean −2.3%, top cross 62% hit
but −0.8%); from 2020-03-15 on, 16 of 21 top crosses gained (+3.8% per 3 months,
every August–September edition positive). Curve calls: 279 ★★/★★★, all but one
steepeners, 68% right (+0.19pp); ★★ 70%, ★★★ only 10/19. For the 2021 editions:
78 crosses, 69% hit, +2.2% per 3 months; the top cross gained in 20 of 26 editions
(+1.9%): long CNY/AUD through February, BRL or CNY against GBP in spring and summer,
long MXN/GBP from August (8 of 10 positive), the best BRL/HUF from 2021-03-28
(+10.8%) and the worst CNY/HUF from 2021-03-14 (−4.7%). Curve calls were a coin flip:
231 ★★/★★★, 45% right (+0.01pp); the 142 flatteners, mostly in the second half as
hiking cycles began, were right only 35% of the time (−0.10pp), the 89 steepeners 61%
(+0.18pp); ★★★ 4 of 8. For the 2022 editions: 78 crosses, 54% hit, +0.1% per 3 months
(H1 +1.6%, 64% hit; H2 −1.4%, 44%), but the top cross gained in only 10 of 26
editions (−1.6%): long MXN/CHF in January (+5.9 to +8.0%), then long ZAR (against
EUR, CHF, AUD, KRW or JPY) in 20 of the remaining 23 editions, which carry could not
save through the spring risk-off (five of the six 2022-04-10 to 06-19 holds lost 5–8%),
and long INR or IDR against CHF or AUD in October–November (−4.6 to −8.1%); best
ZAR/EUR from 2022-01-02 (+12.0%), worst IDR/KRW from 2022-11-06 (−8.5%). Curve calls: 186 ★★/★★★, 176 of them flatteners as hiking
cycles matured, 51% right (+0.15pp; flatteners 53%, +0.21pp; the 10 steepeners 20%);
★★★ 4 of 4 (Norway flatteners, August–September). For the 2023 editions:
81 crosses, 79 scored (the two BRL/CLP holds of September lack a BIS daily CLP rate),
81% hit, +3.2% per 3 months (H1 +4.1%, 31 of 39 positive; H2 +2.3%, 33 of 40); the top cross gained in
25 of 27 editions (+5.6%), riding the year's high-carry rally: long BRL against THB or JPY
through June (+6.1 to +12.8%), long ZAR/JPY in March–April, then long MXN (against CNY,
JPY, KRW, INR, EUR or NZD) from July, losing only in the two August MXN/KRW holds (−3.3%,
−1.5%); best BRL/THB from 2023-03-26 (+16.5%), worst ZAR/CNY from 2023-01-01 (−4.1%).
Curve calls: 151 ★★/★★★, 60% right (+0.15pp; the 104 flatteners 64%, +0.14pp; the 47
steepeners 49%, +0.17pp); ★★★ 7 of 13 (Hungary's November–December steepeners
+1.7 to +2.8pp, Poland's September–October steepeners wrong). For the 2024 editions:
78 crosses, 46% hit, −0.3% per 3 months (H1 −2.2%, 13 of 39 positive; H2 +1.6%, 23 of 39),
and the top cross gained in only 11 of 26 editions (+0.0%): long MXN/CHF in January–February
(+7.4 to +11.2%; −2.1% from 2024-03-10), then long BRL, almost always against CHF, from
2024-03-24 to year-end, which lost from every March–October entry but two as the real slid
(worst BRL/CHF from 2024-05-05, −14.0%) and gained from every November–December entry
(+5.1 to +9.3%); the May–June MXN/CZK holds ran into the Mexican election shock
(−8.9 to −13.8%); best MXN/CHF from 2024-01-14 (+11.2%). Curve calls: 200 ★★/★★★, 51% right
(+0.06pp); the 85 steepeners 79% (+0.44pp), the 115 flatteners only 30% (−0.22pp; worst in
Mexico, the UK, Norway and the US); ★★★ 16 of 23 (Hungary's January–February
steepeners +2.3 to +3.2pp).

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
