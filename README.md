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
reaches back to 2008, so editions dated on or before 2017-12-31 are built by
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

### 2019 editions

Biweekly grid continued: 2019-01-06, 01-20, 02-03, 02-17, 03-03, 03-17,
03-31, 04-14, 04-28, 05-12, 05-26, 06-09, 06-23, 07-07, 07-21, 08-04, 08-18,
09-01, 09-15, 09-29, 10-13, 10-27, 11-10, 11-24, 12-08, 12-22
(`python scripts/retro_build.py --range 2019-01-06 2019-12-31 --every 14`),
published to the site archive on 2026-11-26 (26 pages; 33,804 audit checks,
0 failed). 2018 is being built separately; its builder extension (US target
ranges of 2018, Türkiye's label from 1 Jun 2018) is included here unchanged.

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

`retro_scorecard.py` (ex-post, deliberately using later data; never an edition input)
scores the published calls: the top three FX crosses held 3 months (BIS daily spot
plus the stated policy-rate differential) and the ★★/★★★ curve calls (3-month change
of 10y minus policy). For the 2019 editions: top cross 62% hit, +1.2% per 3 months
(+2.2% through the 2019-11-10 edition; the 2019-12-08 and 12-22 holds ran into the
February–March 2020 sell-off, MXN/JPY −6% and −21%); ★★★ curve calls 13/15 right,
★★ calls a coin flip (44%).

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
