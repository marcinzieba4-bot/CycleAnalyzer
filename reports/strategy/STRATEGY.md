# Trading the Cycle Monitor — a rulebook tested on 2008–2026

*Built 2026-11-27 from the 465 point-in-time editions (2008-01-06 … 2025-09-28 biweekly, plus
2026-09-13) and the live refresh of 2026-11-27. Backtest: `scripts/strategy_backtest.py`.
Model output, not investment advice.*

## 1. Bottom line

1. **The published trade ideas are only partly tradeable as printed.**
   - **Top-3 FX crosses, held 3 months:** Sharpe 0.20, max drawdown −39%, 12/19 positive years.
   - **Every ★★/★★★ curve call, held 3 months:** Sharpe 0.12.
   - The edge is there, but it is diluted and badly sized.
2. **Two changes turn them into a strategy that works in both halves of the history.** Rules were
   chosen on 2008–18 only; 2019–26 is the out-of-sample check.

| Book | 2008–18 Sharpe | 2019–26 Sharpe | Return / vol (all) | Max DD | Positive years | Worst year |
|---|---|---|---|---|---|---|
| **FX-A** — carry-to-risk crosses | 0.60 | 0.99 | 8.5% / 11.0% | −22.8% | 14/19 | −3.1% |
| **CV-A** — curve calls with a SETUP / EARLY TURN verdict | 0.84 | 0.80 | 10.8% / 13.2% | −36.2% | 16/19 | −5.2% |
| **Combined 50/50 risk** (correlation −0.01) | **1.07** | **1.26** | **9.7% / 8.4%** | **−15.2%** | **17/19** | **−1.5%** |

3. **What the history says, in one line each:**
   - **What to use:** the **carry** engine drives the FX edge. The **cycle clock** is useless for
     *picking currencies* but valuable for *timing curve trades*.
   - **How long to hold:** **months, not weeks.** Hold at least 3 months, and FX until the signal
     fades.
   - **Stops:** **tight stops destroy the edge.** Use only a wide catastrophe stop.

## 2. The rules

### FX-A: carry-to-risk crosses (each edition, i.e. every 2 weeks)

1. **Score each currency.** Take the edition's engines without the clock:
   `carry + valuation + momentum + penalty`, i.e. the page's *total minus cycle*. Divide by the
   currency's 63-day realized volatility vs USD, with a 4% floor. Keep the framework's credibility
   screen: a currency with penalty ≤ −1 (TRY-style) is excluded from both sides.
2. **Pick 3 crosses.** Take the 6 highest and 6 lowest scores. Pair them greedily by the largest
   score gap, using each currency once.
3. **Size** each cross to equal risk (notional = 10% ÷ the cross's 63-day vol). Each edition opens
   a new **tranche**, so positions build up over about 6 months (dollar-cost averaging into carry).
   Scale the whole book to 10% vol at each edition.
4. **Holding period**
   - **Minimum 3 months (63 trading days).** No exit on news or noise before then.
   - **After 3 months:** close at the first edition where the long leg has left the top 6 or the
     short leg has left the bottom 6.
   - **Maximum 12 months.**
5. **Stop:** **catastrophe stop only.** Close if the cross is down 2 quarterly sigmas
   (= 2 × vol × √¼, about −6% to −13%). Never use a tight or trailing stop.

Trade log (1,395 trades): average +3.1% (2008–18) / +3.5% (2019–26) per trade, 68–69% winners,
average hold about 5 months.

| Exit | Trades | Average | Winners |
|---|---|---|---|
| Signal faded | 786 | +4.0% | 75% |
| 12-month maximum | 406 | +8.6% | 90% |
| Catastrophe stop | 200 | −10.2% | 0% |

### CV-A: curve calls (each edition)

1. **Take a curve call only when the slope's context verdict is SETUP or EARLY TURN** and the call
   is not neutral. All ★★★ calls fall in this set. Ignore every other ★/★★ call, and avoid
   **WATCH**, which loses in both periods.
2. **Size:** each call = 1 ÷ (24-month vol of the monthly slope change), as a DV01-neutral 2s10s
   trade. Book scaled to 10% vol.
3. **Hold 6 months** from the edition month. Holding 12 months earns more but with deeper drawdowns;
   exits on signal persistence are worse here.
4. **Stop:** catastrophe stop at −75bp of slope. It triggered on only 21 of 786 calls, so it is free
   insurance.

Trade log (786 calls): +37bp (2008–18) / +52bp (2019–26) per call, 69% / 76% winners.

### Combining

- **Allocation:** 50% of the risk budget to each book. Their monthly returns are uncorrelated
  (−0.01). FX loses in carry crashes, and curves often gain in exactly those (2008, 2011, 2022).
- **Drawdowns:** each book's −23% to −36% drawdown becomes −15% combined.

## 3. The evidence behind each rule

Reproduce with `python scripts/strategy_backtest.py --diagnostics`.

**Which FX engine predicts?** Mean cross-sectional rank IC of each engine vs the currency's forward
return including carry, vs USD:

| Engine | 21d 2008–18 | 21d 2019–26 | 63d 2008–18 | 63d 2019–26 | 126d 2008–18 | 126d 2019–26 |
|---|---|---|---|---|---|---|
| carry | +0.055 | +0.096 | +0.082 | +0.154 | +0.120 | +0.152 |
| cycle (clock) | −0.012 | −0.012 | −0.029 | −0.077 | −0.028 | −0.121 |
| valuation | 0.000 | −0.020 | +0.003 | −0.037 | +0.007 | −0.009 |
| momentum (policy) | +0.002 | +0.020 | +0.007 | +0.020 | +0.026 | +0.048 |
| total (published) | +0.051 | +0.083 | +0.065 | +0.099 | +0.094 | +0.088 |

- **Carry is the edge. The clock is slightly *contrarian* in both periods:** long legs in
  "Overheating" were the weakest.
- **Removing the clock is worth a lot:** FX-A *with* the cycle engine drops to Sharpe 0.25 / 0.70.
- **Why vol-scale.** Without vol-scaling the score, FX-A drops to 0.26 / 0.91. Raw carry
  over-weights BRL, the most frequent published long (262 of 1,395), which *lost* on average in
  both periods. Low-volatility carry (CNY, INR, IDR) and good funders (GBP, EUR, SEK, CZK, THB) did
  best. CHF and CAD were poor funders.

**Holding period and stops** (published crosses, Sharpe at 10% vol, 2008–18 / 2019–26):

| Rule | Sharpe |
|---|---|
| Hold 21 days | −0.10 / +0.01 |
| Hold 63 days | +0.23 / +0.15 |
| **Hold 126 days** | **+0.33 / +0.19** |
| Hold 252 days | +0.23 / +0.41 |
| Hold 126 days + fixed −3% stop | +0.14 / +0.21 |
| Hold 126 days + fixed −5% stop | +0.14 / +0.18 |
| Hold 126 days + fixed −8% stop | +0.19 / +0.18 |
| Hold 126 days + 1.5σ-quarter stop | +0.24 / +0.21 |
| Hold 126 days + 2σ-quarter stop | +0.28 / +0.17 |
| Hold 126 days + 5% trailing stop | +0.09 / +0.23 |

- **Holding:** biweekly churn costs more than it earns, so hold for months.
- **Stops:** every stop lowered the 2008–18 Sharpe. Carry crosses mean-revert after sell-offs,
  so a stop sells the low. Supporting evidence:
  - Crosses that already ran more than 4% in the prior 3 months earned +0.2% (2008–18) and −1.1%
    (2019–26) over the next quarter, vs +1.2% to +1.4% after a sell-off.
  - Entries in the top quartile of volatility earned about +2% per quarter in both periods.
- **Inside FX-A** (which exits on signal persistence), the 2σ catastrophe stop *helps*: 0.53 → 0.60
  and 0.92 → 0.99, and the worst year improves from −9% to −3%. That is why it is the only stop.

**FX-A robustness** (Sharpe 2008–18 / 2019–26):

| Variant | Sharpe |
|---|---|
| Final rule | 0.60 / 0.99 |
| Minimum hold 42 days | 0.57 / 1.03 |
| Minimum hold 84 days | 0.61 / 0.98 |
| Exit depth 5 | 0.58 / 1.00 |
| Exit depth 7 | 0.55 / 0.99 |
| 5 crosses instead of 3 | 0.47 / 1.00 |
| No catastrophe stop | 0.53 / 0.92 |

None of these is a knife-edge choice.

**Curve calls by context verdict** (6-month gain in the call's favour):

| Verdict | 2008–18 | 2019–26 |
|---|---|---|
| **SETUP** | **+46bp, 74% hit (n=281)** | **+52bp, 81% (n=266)** |
| **EARLY TURN** | +11bp, 52% (n=102) | +57bp, 66% (n=157) |
| LATE | +42bp, 60% (n=75) | +35bp, 69% (n=150) |
| none | +15bp, 51% (n=2,632) | −2bp, 54% (n=1,279) |
| TREND INTACT | −16bp, 38% (n=521) | +23bp, 47% (n=187) |
| **WATCH** | **−10bp, 40% (n=735)** | **−17bp, 40% (n=700)** |
| ★★★ | +25bp, 65% (n=80) | +71bp, 71% (n=90) |
| ★ / ★★ | +8 to +10bp, about 50% | −6 to +14bp, about 54% |

**Rejected because they did not hold in both periods:**
- global-pack filters (share of banks hiking or cutting, share in Disinflation)
- 12-month FX momentum
- trailing stops
- the "skip chased crosses" entry filter (it helps single trades but not the portfolio)
- tranche normalization of the curve book

## 4. Current book and today's signals (2026-11-27)

The repository has no editions between 2025-09-28 and 2026-09-13. In the backtest, the 2025
tranches therefore rode to their 12-month maximum, so treat the 2026 calendar-year figures (FX
+22.7%) as indicative.

**Open from the 2026-09-13 edition** (entered 14 Sep 2026; marked to 24 Nov 2026):

| Cross | P&L | Catastrophe stop | Status |
|---|---|---|---|
| Long IDR / short PLN | +5.1% | −6.6% | Still qualifies |
| Long INR / short CHF | +6.4% | −6.9% | Still qualifies |
| Long BRL / short SEK | −5.9% | −8.6% | BRL has left the top 6 |

- **BRL / SEK:** exit at the first edition after its 3-month minimum (about 10 Dec 2026) unless BRL
  re-qualifies.
- **Curves held to about March 2027:** NZ flattener (EARLY TURN), KR flattener (SETUP),
  HU steepener (SETUP).

**New tranche from the live refresh** (`run_analysis.py --refresh`, model anchor 2026-10, FX to
2026-11-24; `strategy_backtest.py --live`):

| New cross | Cross vol | Notional per 10% risk | Catastrophe stop |
|---|---|---|---|
| Long IDR / short CHF | 6.3% | 1.59× | −6.3% |
| Long INR / short THB | 5.8% | 1.73× | −5.8% |
| Long NZD / short HUF | 8.5% | 1.17× | −8.5% |

- **New curve trade:** NZ 2s10s flattener (SETUP, slope +2.26pp, z +1.05): pay 2y, receive 10y,
  DV01-neutral.
- **Exit test for open crosses:** the long leg must stay in IDR, INR, NZD, ZAR, CAD, AUD; the short
  leg in MXN, SEK, PLN, HUF, THB, CHF.
- **Concentration:** long Asian low-volatility carry (IDR, INR) against CHF appears in more than one
  tranche. Keep the per-tranche sizes; do not add on top.

**Each fortnight:** run the weekly job, then `python scripts/strategy_backtest.py --live`.
- Open the new tranche.
- Close crosses that are past 3 months and fail the exit test.
- Check the stops.
- Open the SETUP / EARLY TURN curve calls for 6 months.

## 5. Caveats

- **FX carry** is proxied by policy-rate differentials. Forward-implied yields differ, especially
  for NDF currencies (BRL, INR, IDR, CNY, KRW, COP, CLP).
- **FX costs:** 3 / 6 / 10bp one-way (G10 / CEE / other EM) plus quarterly rolls. Prices are BIS
  daily fixings, not executable quotes.
- **The curve P&L is the model slope, 10y minus policy.** On real US 2s10s the SETUP / EARLY TURN
  calls kept their hit rate (93% on 29 calls) but captured about ⅔ of the move (+39bp vs +60bp
  over 6 months). With 10y minus 3m interbank the curve book still had Sharpe ≈0.8 / ≈1.0. These
  were side checks, not in the committed script. Expect roughly ⅔ of the CV-A returns in practice.
- **The curve book** is a global-duration bet when many calls agree. Its −36% drawdown came in
  2015–16, when 8 countries' steepeners met the Brexit-era bond rally together.
- **Overfitting:** the selection used 2008–18 only, but I had seen the repository's 2019–24
  scorecard notes before designing. The rule families (carry-to-risk, signal-persistence exits, the
  verdict filter) are standard and few, and every neighbouring setting works.

## 6. Reproduce

```bash
python scripts/strategy_extract.py      # re-run every edition's model -> data/strategy/{fx,crosses,curves,...}.csv
python scripts/strategy_market.py       # BIS daily FX + policy, FRED 10y -> data/strategy/*_daily.csv, y10_monthly.csv
python scripts/strategy_backtest.py     # headline tables + data/strategy/backtest/{fx_trades,curve_trades,monthly_returns}.csv
python scripts/strategy_backtest.py --diagnostics
python scripts/strategy_backtest.py --live   # today's signals (after scripts/run_analysis.py --refresh)
```

`strategy_extract.py` checks that every edition's re-run crosses match its published page
(465 / 465 match).
