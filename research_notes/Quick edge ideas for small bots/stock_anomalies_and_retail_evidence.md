# Short-horizon US stock/ETF anomalies for a small long-only cash account, and the evidence on retail day trading

Scope: US equities/ETFs, long-only cash account (no shorting, margin or options), $200-$500 with fractional shares, commission-free broker, free Alpaca SIP bars plus SEC EDGAR. Research done 2026-11-24 using web search only (~16 tool calls). Most findings come from abstracts, search excerpts and secondary summaries, not full-text reads. Older results are dated. Anything without a source is under Inferences or Gaps.

Cross-cutting context:
- McLean & Pontiff (JF 2016), 97 predictors: portfolio returns are 26% lower out of sample and 58% lower after publication. They attribute about 32 percentage points (58 - 26) to publication-informed trading — [McLean & Pontiff PDF](https://Www.Gwern.net/doc/economics/2016-mclean.pdf)
- Jacobs & Müller (2017): the US is the only country with a reliable post-publication decline, of 60% (equal-weighted) and 65% (value-weighted) for long/short returns. Part of this is a general time trend — [Jacobs & Müller](https://www.wiwi.hu-berlin.de/en/Professorships/bwl/finance/seminars/papers-fin-acc-res-seminars/17s/jacobs.pdf)
- These figures are for long/short anomaly portfolios. A long-only account captures only the long leg.

---

## Intraday momentum (first half-hour predicts last half-hour, SPY)

### Takeaway
The original effect is real but small: about 1.4% out-of-sample R² on 1993-2013 SPY data. Baltussen et al. (2021) link it to gamma hedging by option market makers and leveraged ETFs, which means it depends on the regime rather than being constant. SPY spreads are tiny, so costs are low. But the expected edge per trade is a few basis points against a much larger per-trade noise, so a $200-$500 account would need roughly a year or more of forward trades before it showed anything. **Verdict: maybe.** It is cheap to paper-trade, but expect no conclusion within weeks.

### Cited Findings
- Gao, Han, Li & Zhou (JFE 2018), SPY 1993-2013: the first half-hour return predicts the last half-hour return. Out-of-sample R² is about 1.4% with that single predictor and 2.0% when combined with the 12th half-hour return. The authors suggest predictability may have dropped after decimalization in 2001 and with faster trading technology; this is offered as a hypothesis — [Gao et al. PDF (nd.edu)](https://www3.nd.edu/~zda/intramom.pdf); [Alpha Architect summary](https://alphaarchitect.com/2014/08/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/)
- Baltussen, Da, Lammers & Martens, "Hedging Demand and Market Intraday Momentum," JFE 142(1):377-403, 2021, more than 60 futures, 1974-2020:
  - The return over the rest of the day positively predicts the last 30 minutes in equities, bonds, commodities and currencies, and this reverts over the following days.
  - Mechanism: short-gamma hedging by options market makers and leveraged-ETF rebalancing — [EUR Pure](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/); [EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:142:y:2021:i:1:p:377-403)
- A secondary summary says the momentum is concentrated on days when net gamma exposure is negative and is insignificant when it is positive. I could not verify this against the paper — [Alpha Architect](https://alphaarchitect.com/hot-topic-does-gamma-hedging-actually-affect-stock-prices/)
- A PhD thesis covering 16 developed markets finds significant first-to-last half-hour predictability in 12 of them, and says the out-of-sample predictability translates into economic gains — [Southampton thesis](https://eprints.soton.ac.uk/452387/1/PhD_thesis.pdf)
- A J. Futures Markets 2022 paper reports that an overnight-return variant of the predictor loses its predictability out of sample — [IDEAS](https://ideas.repec.org/a/wly/jfutmk/v42y2022i12p2218-2234.html)

### Inferences
- **Costs.** SPY's quoted spread is usually 1 cent on a share around $500-$600, about 0.2 bp per side. Over ~250 round trips a year, spread costs are around 0.5-1 bp per trade (about 1.25-2.5% a year) if fills are at or near the touch. Market-on-close orders avoid the closing spread.
  - At $200-$500 with fractional shares, the main real risk is how the broker fills fractional orders and whether MOC orders are supported for fractional shares (assumption; check Alpaca's docs).
- **Time to evidence (assumption-based arithmetic).** Assume a mean edge of about 3 bp per trade and a last-half-hour standard deviation of about 25 bp. Then t ≈ 2 needs about (2 × 25 / 3)² ≈ 280 trades, around 1.1 years of daily trades. Weeks of data say nothing.
  - The better use of this idea is a backtest on Alpaca SIP minute bars, which go back to about 2016. That is free and immediate.
- The gamma mechanism means returns cluster in high-volatility, negative-gamma days. A short forward window can show zero effect even if the long-run effect is real.
- **Data:** Alpaca SIP 1-minute or 30-minute SPY bars are sufficient.

### Gaps
- I did not find a peer-reviewed 2024-2026 out-of-sample update for SPY specifically.
- A 2024 practitioner paper by Zarattini and co-authors ("Beat the Market", SPY intraday momentum) appeared in search results, but I did not verify its numbers. One snippet attributed a 1974-2020 sample to it, which may belong to Baltussen instead.
- No source gave net-of-cost annual returns for a ~250-trade/year SPY implementation.

---

## Overnight vs intraday returns (buy at close, sell at open)

### Takeaway
Almost all of SPY's price return over 1993-2020 came overnight. But several analyses find that trading costs eat most or all of the overnight edge relative to buy-and-hold, and that the anomaly weakened after about 2009. Long-only can capture it mechanically with MOC buys and MOO sells. However, it costs two crossings a day and gives up intraday returns, which are roughly zero but not reliably negative, and dividends.
**Verdict: skip as a standalone strategy.** At best it could be a component, for example only holding overnight in a filtered set. Statistically it is not testable on forward data on any reasonable horizon.

### Cited Findings
- Alpha Architect, SPY 1993-Jan 2020, before costs: cumulative price returns of 717% for overnight, 627% for buy-and-hold and 12% for intraday. Transaction costs reduce the excess return, outperformance has faded over the years, and statistical robustness is low — [Alpha Architect, "Trading costs wipe out the overnight return anomaly" (2020)](https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/)
- Over 30 years, $1 invested overnight grew to $17.27 versus about $1.20 intraday. Costs including market impact "would erase most or all" of the expected gain for most investors — [Advisor Perspectives / Elm Wealth (2025)](https://www.advisorperspectives.com/articles/2025/03/11/working-night-shift-still); [Elm Wealth "Night Shift" (Mar 2025)](https://elmwealth.com/night-shift/)
- The anomaly became "much less anomalous" around 2009. ETFs launched to capture it (e.g., NightShares) failed partly on timing and costs — [Falkenstein Substack](https://efalken.substack.com/p/the-equity-overnight-anomaly-etfs)
- The strategy trades a lot and is very sensitive to slippage and fees — [QuantConnect strategy library](https://www.quantconnect.com/tutorials/strategy-library/overnight-anomaly)
- Practitioner backtest: more than 88% of SPY's return came overnight, but the edge is not a straight line and failed in crises. Tested with $0-$3 per-trade costs; a mean-reversion-filtered variant did better — [Two Quants](https://twoquants.substack.com/p/trading-the-night-effect)
- US sector ETFs: overnight outperformance "decreases significantly" once transaction costs are included — [MDPI Risks 14(4):84](https://www.mdpi.com/2227-9091/14/4/84/htm)
- Lou, Polk & Skouras have a 2026 working paper, "A Clientele Perspective on the Equity Premium" (dated 2026-06-03), building on their earlier "tug of war" work showing that momentum earns its return overnight. I did not read it — [LSE PDF](https://personal.lse.ac.uk/POLK/research/LPS_ClientelePerspectiveOnEquityPremium_20260603.pdf)

### Inferences
- **Edge per night.** $17.27 over ~30 years (~7,560 nights) implies about 3.8 bp mean overnight log return. That is the gross edge versus holding cash.
  - Versus buy-and-hold, the extra edge is only the intraday return avoided, which is close to zero on average.
  - The SPY round-trip spread (~0.3-0.5 bp) is small. MOO/MOC auction prices avoid the spread but not adverse selection.
  - The real cost for a taxable account is that every gain is short-term, and the account gives up the dividend when not holding at the ex-date close (dividends are paid to holders of record, so overnight holders do get dividends whose ex-date opens the next day; detail unverified).
- **Time to evidence.** With overnight standard deviation of about 60-80 bp and a mean of about 4 bp, t ≈ 2 needs about (2 × 70 / 4)² ≈ 1,200+ nights, about 5 years. The only practical evidence is historical bars.
- **Capacity** is not a constraint at $200-$500.

### Gaps
- I did not verify primary numbers from Cooper, Cliff & Gulen (2008), Kelly & Clark (2011) or Lou, Polk & Skouras (JFE 2019).
- I found no 2024-2026 peer-reviewed estimate of net overnight returns for retail-sized trades.
- I did not check whether Alpaca supports MOO/MOC orders with fractional shares.

---

## Post-earnings-announcement drift (PEAD)

### Takeaway
Martineau (Critical Finance Review 2022) argues that prices now absorb earnings surprises on the announcement day. Drift disappeared for large caps by about 2006 and lingers mainly in microcaps, which have wide spreads. Two 2025 papers push back, so the question is contested. For a long-only small account the residual edge sits in illiquid microcaps where spreads dominate.
**Verdict: skip, or maybe only as a large-cap filter.** It also needs earnings-surprise data, which neither EDGAR XBRL nor Alpaca provides as consensus estimates.

### Cited Findings
- Martineau, "Rest in Peace Post-Earnings Announcement Drift," Critical Finance Review 11(3-4):613-646 (2022). Prices fully reflect earnings surprises on the announcement day. Drift is gone for large stocks by 2006; microcaps lag — [Now Publishers](https://nowpublishers.com/article/Details/CFR-0122); [author PDF](https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf)
- Pushback:
  - A UCLA Anderson Review brief, "Is PEAD a thing again?", covers 2025 papers disputing the conclusion. Dickerson, Julliard & Mueller find that earnings drift remains an important priced factor.
  - Subrahmanyam argues the disagreement reflects research-design choices — [UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again)
  - I saw this only via a search summary and did not read the papers.

### Inferences
- Where PEAD survives (microcaps), $1-$5 stocks often have spreads of 50-200+ bp. That likely exceeds the residual drift per trade. This is an assumption; no source quantified net returns.
- **Time to evidence.** There are hundreds of earnings events per quarter, so a test could reach 100+ trades a month in season. Event volatility is high (5-10% two-month standard deviation), so even 300 events gives only about ±1% precision.
- **Data gap.** A standardized surprise needs analyst consensus, which is not free. A free proxy is a price-based surprise: the announcement-day abnormal return or gap, computable from Alpaca bars plus EDGAR 8-K Item 2.02 timestamps.

### Gaps
- No net-of-cost long-only PEAD return estimate for 2015-2026.
- No numeric microcap-versus-large-cap drift for recent years.
- I did not read the full text of either 2025 rebuttal.

---

## Insider purchases (SEC Form 4)

### Takeaway
This is the best-supported idea for this account. Insider *purchases*, especially "opportunistic" (non-routine) purchases and cluster buys in small firms, carry information. The data is free on EDGAR and fits a long-only account. Caveats:
- The returns come mostly from small and illiquid stocks.
- Filings become public up to 2 business days after the trade, and part of the move happens before a retail bot can act.
- Rigorous post-2012 replications were not found.

**Verdict: worth testing.** Run an EDGAR-based historical backtest first, with entry at the next open after the *filing* timestamp, not the trade date.

### Cited Findings
- Cohen, Malloy & Pomorski, "Decoding Inside Information," JF 67(3):1009-1043 (2012):
  - Classifying insiders as routine (trading in the same month in past years) versus opportunistic, a portfolio following only opportunistic trades earns value-weighted abnormal returns of 82 bp a month. Routine trades earn about 0.
  - More than half of insider trades are routine.
  - The most informative traders are local, non-executive insiders at geographically concentrated, poorly governed firms — [NBER w16454](https://www.nber.org/papers/w16454); [NBER digest](https://www.nber.org/digest/apr11/decoding-inside-information); [EconPapers](https://econpapers.repec.org/RePEc:bla:jfinan:v:67:y:2012:i:3:p:1009-1043)
- Cluster purchases earn about 3.8% abnormal return over 21 trading days versus 2.0% for non-cluster purchases. About 23% of purchases occur on the same day as another insider's purchase at the same firm — [Interactive Brokers Campus summary of academic research](https://www.interactivebrokers.com/campus/traders-insight/securities/stocks/what-corporate-insider-buying-can-tell-investors-evidence-from-academic-research/)
- The same summary attributes to Lakonishok & Lee a buy-minus-sell return gap that is strongest in small stocks and much weaker in large firms. It cites a sample of 52,532 insiders at 8,789 firms, 1986-2014.
  - **Conflict/caution:** the original Lakonishok & Lee (RFS 2001) covered an earlier period (I believe 1975-1995, unverified). The 1986-2014 sample may belong to a different study the summary merged in.
- Jeng, Metrick & Zeckhauser (REStat 2003): a paper by Zeckhauser on insider trading returns is hosted at Harvard, but I did not extract its figures — [Harvard PDF](https://scholar.harvard.edu/sites/scholar.harvard.edu/files/rzeckhauser/files/insider_trading.pdf)
- **Practitioner warnings:**
  - A data vendor (Quiver) reports its cluster-ranked insider strategy underperformed buy-and-hold badly, which it attributes to routine director purchase programs — [Quiver tutorial](https://www.quiverquant.com/tutorials/insiderbuyingstrategy/). This is marketing-adjacent.
  - A Substack analysis argues that acting at the next open after the filing date faces a strong headwind that academic trade-date backtests don't capture. Its cluster sample is only n=4 — [Johnsen Substack](https://tommijohnsen.substack.com/p/most-of-the-insider-trading-alpha)
- A 2024 Nova SBE master's thesis tests insider filings over 2003-2022; I did not see its results — [Nova thesis](https://run.unl.pt/bitstream/10362/173619/1/FALL24_42997_Rodrigo_Baptista.pdf)

### Inferences
- **Capacity.** With fractional shares, $200-$500 can hold 5-10 positions of $40-$100. Many qualifying names will be small caps, possibly not fractionable at Alpaca, and spreads of 20-100 bp eat part of a ~2-4% expected 1-month abnormal return.
- **Time to evidence.**
  - Opportunistic or cluster buys run perhaps tens to low hundreds of events a month across all US stocks (assumption; measure from EDGAR).
  - Per-event 1-month return standard deviation is about 10-15%. Detecting a 2% mean at t ≈ 2 needs about (2 × 12 / 2)² ≈ 150 events. A forward test therefore takes months, but an EDGAR backtest on 2010-2026 data can be done immediately.
- **Implementation:**
  - Parse Form 4 XML (transaction code "P" = open-market purchase).
  - Apply the CMP routine filter (needs 3 years of history per insider).
  - Use the filing acceptance timestamp for entry.
  - Exclude 10b5-1 planned trades, which have a checkbox on Form 4 since April 2023 (from memory, unverified).

### Gaps
- No peer-reviewed post-2012 out-of-sample replication of the CMP opportunistic strategy or cluster buying was found.
- No net-of-spread return estimate for filing-date entry.
- I did not confirm the Lakonishok & Lee 2001 numbers.

---

## Turn-of-the-month (TOM) and pre-holiday effects

### Takeaway
McConnell & Xu (FAJ 2008) found that 1926-2005 equity returns came almost entirely from the turn-of-month window. Later evidence is mixed:
- One recent thesis finds the end-of-month effect gone over 2006-2023.
- Other work finds it persisted but shifted earlier.

Pre-holiday effects were strong up to 1987 and much weaker since. Both are cheap to implement with SPY: about 12 round trips a year for TOM, about 9 for holidays. But there are too few events to verify forward, and the cost is lost market exposure on other days.
**Verdict: skip as an alpha source.** Possibly use as a timing overlay; evaluate only by backtest.

### Cited Findings
- McConnell & Xu, "Equity Returns at the Turn of the Month," FAJ 2008, 1926-2005: on average investors received no reward for bearing market risk except at the turn of the month — [CFA Institute](https://rpc.cfainstitute.org/en/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month)
- Universidade Católica Portuguesa thesis:
  - The end-of-month effect is present in CRSP value indices for 1987-2005 and disappears over 2006-2023.
  - Evidence on whether rising efficiency caused this is inconclusive — [UCP thesis](https://repositorio.ucp.pt/bitstreams/8a4ad0ac-a69c-42d2-8611-9a7149577751/download)
- Opposing evidence:
  - SPY 2001-2011: TOM still exists but has moved to earlier dates — [Purdue CIBER WP](https://docs.lib.purdue.edu/ciberwp/43)
  - Arkansas thesis: continued evidence over 2005-2014, with a backward shift — [Arkansas](https://scholarworks.uark.edu/finnuht/10)
- The proposed mechanism is institutional liquidity demand and settlement timing (month-end cash flows) — [RFS 33(1):75](https://academic.oup.com/rfs/article/33/1/75/5494694)
- **Pre-holiday:**
  - S&P 500 1930-1999: strong pre-holiday effect up to 1987, "greatly diminished after 1987". The Labor Day effect is not observed after 1987 — [core.ac.uk](https://core.ac.uk/works/2843318)
  - Christmas window 1950-2024: modest strength, but "noise generally dominates signal" — [CXO Advisory](https://cxoadvisory.com/calendar-effects/stock-returns-around-christmas)
  - Fisher Investments: the S&P 500's 1.3% median Santa-rally return since 1928 is skewed by 1971, 1987 and 1991 — [Fisher](https://www.fisherinvestments.com/en-us/insights/market-commentary/dont-tell-the-kids-but-santa-rallies-arent-real)

### Inferences
- **Time to evidence.** TOM gives 12 events a year and pre-holiday about 9. Forward testing is hopeless (decades); backtest only.
- Being in SPY only on TOM days gives up the equity premium on the other days unless those days really earn about zero.
- Recent evidence says they don't reliably earn zero, so the expected net benefit versus buy-and-hold is about zero or negative.

### Gaps
- No peer-reviewed 2020s US TOM or pre-holiday study was found.

---

## Index additions and deletions (S&P 500 inclusion effect)

### Takeaway
The S&P 500 addition effect has collapsed: about +7.4% abnormal return in the 1990s to under 1% recently. The deletion effect went from about -16% in the 1990s to -0.6% in 2010-2020. This is partly because many changes are now migrations from the S&P MidCap 400, where forced buying and selling offset each other. Shorting deletions is impossible here anyway.
**Verdict: skip.**

### Cited Findings
- Greenwood & Sammon, "The Disappearing Index Effect," Journal of Finance 80(2):657-698 (2025):
  - The addition abnormal return fell from 7.4% in the 1990s to under 1%.
  - Deletion effects: -4.6% in the 1980s, -16.1% in the 1990s, -12.4% in 2000-2009 and -0.6% in 2010-2020. The 2022 working-paper version reports slightly different figures (-16.6% and -12.3%).
  - Migrations from the S&P MidCap offset the price pressure.
  - Index-size composition does not fully explain the decline. A similar decline appears in other index families — [SSRN 4294297](https://papers.ssrn.com/abstract=4294297); [NBER w30748](https://www.nber.org/system/files/working_papers/w30748/w30748.pdf); [IDEAS](https://ideas.repec.org/a/bla/jfinan/v80y2025i2p657-698.html)
- Selecting the largest eligible non-member firm has become a better predictor of addition, but predicting the exact names remains difficult — [HKS summary](https://www.hks.harvard.edu/centers/mrcbg/programs/growthpolicy/disappearing-index-effect)

### Inferences
- Only about 20-30 S&P 500 changes a year (assumption) produce too few events, and the edge is under 1%. Not worth building.

### Gaps
- No 2021-2026 extension of the series was found.

---

## Dividend capture

### Takeaway
On the ex-date the price drops by most of the dividend: historical drop ratios are about 0.8, with later microstructure work narrowing the gap as tick sizes fell. A retail taxable investor holding briefly gets non-qualified dividends, taxed as ordinary income, plus spread costs on each round trip. Any residual premium is what tax-advantaged arbitrageurs already compete for.
**Verdict: skip.**

### Cited Findings
- Without taxes and costs the drop ratio should be 1. Elton & Gruber (1970) and Kalay (1982) find it closer to 0.8 — [Bond University / core.ac.uk](https://core.ac.uk/download/196603653.pdf); [NBER w0496](https://www.nber.org/papers/w0496)
- Graham, Michaely & Roberts (JF 2003): the median effective ex-day spread fell from 0.125 to 0.0625 to 0.020 as ticks shrank, which is evidence against a pure discreteness explanation. Dividend-capture arbitrage limits how far the drop ratio can deviate from 1 — [Wharton PDF](https://finance.wharton.upenn.edu/~mrrobert/resources/Publications/ExDayStockReturnsJF2003.pdf)
- Measurement matters: using opening prices biases the drop ratio toward 1.0 — [EUR thesis](https://thesis.eur.nl/pub/53289/Final-version-Thesis-Bob-Graat-471516.pdf)

### Inferences
- US qualified-dividend treatment requires holding more than 60 days in the 121-day window around the ex-date. This is general tax knowledge, not from the sources above.
- A capture trade therefore gets ordinary-income tax on a dividend the price already mostly gave back. Net expected value is about zero or negative after spread.

### Gaps
- No post-decimalization (2010-2026) drop-ratio estimate for US large caps was found.

---

## Sector rotation / ETF momentum

### Takeaway
Industry momentum (Moskowitz & Grinblatt 1999) is well documented and survived in post-2000 sector-ETF samples. It is long-only friendly (hold the top N sector ETFs and rebalance monthly), cheap to trade in liquid SPDR sector ETFs, and fully implementable with fractional shares at $200-$500. But it is a medium-horizon strategy (monthly rebalance), not a short-horizon one. Monthly rebalancing means very slow evidence accumulation, and recent 2024-2026 out-of-sample performance was not found.
**Verdict: maybe.** It is a reasonable low-turnover core, but it will not produce evidence in weeks.

### Cited Findings
- Moskowitz & Grinblatt: industry components account for much of individual-stock momentum — [Quantpedia screener](https://quantpedia.com/Screener/Details/3); [Quantpedia sector momentum](https://quantpedia.com/strategies/sector-momentum-rotational-system)
- Sector-ETF momentum portfolios remain robust after controlling for risk (Bond University working paper, Vanstone) — [core.ac.uk](https://core.ac.uk/download/363989861.pdf)
- US equity ETF momentum (2004 onward) is not explained by stock momentum or macro/liquidity risk (SMU 2019) — [core.ac.uk](https://core.ac.uk/download/275589701.pdf)
- Andreu, Swinkels & Tjong-A-Tjoe: country and industry ETF momentum produced economically significant excess returns over the ETFs' trading period, which is in-sample — [arXiv 151 Trading Strategies reference list](https://arxiv.org/pdf/1912.04492)
- Market states condition sector-ETF momentum — [NAU](https://experts.nau.edu/en/publications/market-states-and-momentum-in-sector-exchange-traded-funds/)

### Inferences
- **Time to evidence.** 12 rebalances a year; distinguishing a 2-4% a year edge from noise takes a decade or more. Judge it by backtest on Alpaca daily bars plus a long public history (Ken French industry portfolios), not forward data.
- Momentum crashes (e.g., 2009) are the main tail risk.

### Gaps
- No 2024-2026 out-of-sample results.
- No net-of-cost long-only top-3-of-11 SPDR evidence from a peer-reviewed source.

---

## Retail day trading evidence

### Takeaway
The evidence is overwhelmingly negative:
- In Taiwan, fewer than 1% of day traders predictably earn positive returns net of fees.
- In Brazil, 97% of persistent futures day traders lost money and only 0.4% earned more than a bank teller, with no learning.
- US 2019-2021: retail options traders lost over $1 billion, with very high spreads on short-dated options. Robinhood herding into "top movers" predicted -4.7% 20-day abnormal returns.

Realistic expectations for a retail bot: zero or negative before learning, and short-window profits are mostly luck.

### Cited Findings
- Barber, Lee, Liu & Odean, "The cross-section of speculator skill: Evidence from day trading," J. Financial Markets 18:1-24 (2014):
  - Data: all Taiwan Stock Exchange day trades over 15 years.
  - Only the top ~4,000 prior-year day traders (under 1% of the population) earn reliably positive abnormal returns net of fees.
  - Day traders as a group: -11.5 bp a day before fees, -28.9 bp after fees.
  - The top-to-bottom skill spread exceeds 70 bp a day — [IDEAS](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html); [Odean working paper](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf)
- Companion paper: unprofitable day traders with 50+ days of experience have a 95.3% probability of day trading again within 12 months, about the same as profitable ones — [Odean "day trading and learning"](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/day%20trading%20and%20learning%20110217.pdf)
- Chague, De-Losso & Giovannetti, "Day Trading for a Living?" (SSRN 3423101, working paper 2019-2020):
  - Sample: Brazilians who began day trading equity mini-futures in 2013-2015 and persisted at least 300 days.
  - 97% lost money; only 0.4% earned more than a bank teller's wage.
  - Expected profit is negative and does not improve with experience — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101); [Quantpedia summary](https://quantpedia.com/retail-day-trading-is-an-uphill-battle/); [Investing.com](https://investing.com/news/stock-market-news/day-traders-in-brazil-study-wouldve-done-better-with-9to5-job-2267260)
- Follow-up: about 100,000 active Brazilian day traders a day during COVID — [Brazilian Review of Finance](https://periodicos.fgv.br/rbfin/article/view/94291)
- Bryzgalova, Pavlova & Sikorskaya, "Retail Trading in Options and the Rise of the Big Three Wholesalers," JF 2023:
  - Retail lost $1.14B trading options from Nov 2019 to Jun 2021, assuming 10-day holding.
  - Retail options trading grew 101% from Jan 2020 to Jul 2021.
  - Options expiring within a week had an average bid-ask spread of about 12.3%.
  - Preferences are lottery-like — [LBS PDF](https://lbsresearch.london.edu/id/eprint/2827/1/The%20Journal%20of%20Finance%20-%202023%20-%20BRYZGALOVA%20-%20Retail%20Trading%20in%20Options%20and%20the%20Rise%20of%20the%20Big%20Three%20Wholesalers.pdf); [MIT Sloan](https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows)
- de Silva, Smith et al. (Nasdaq options, 32,791 earnings announcements, 2010-Feb 2021): retail options investors lose 5-9% on average around earnings announcements, and 10-14% for high expected volatility — [MIT Sloan](https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows)
- Barber, Huang, Odean & Schwarz, "Attention-Induced Trading and Returns: Evidence from Robinhood Users," JF 77(6):3141-3190 (2022):
  - Intense Robinhood buying predicts -4.7% average 20-day abnormal returns for the top stocks bought each day.
  - Herding is driven by app features such as the "Top Movers" list.
  - Data covers May 2018 to Aug 2020 — [WUSTL profile](https://profiles.wustl.edu/en/publications/attention-induced-trading-and-returns-evidence-from-robinhood-use/); [IIMB PDF](https://iimb.ac.in/sites/default/files/inline-files/attention-induced-trading.pdf)

### Inferences
- **Fraction profitable over 1-3 months.** No source gave it directly. With per-day returns that are noisy and slightly negative, a sizable minority (likely 20-40%) will be in profit over any 1-3-month window by chance, while over 300 days only about 3% are (Brazil).
  - This is the core reason a few weeks of forward P&L cannot distinguish skill from luck (inference, not sourced).
- **Lessons for a bot:**
  - Avoid options and attention/"top mover" chasing; retail flow there is the dumb-money side.
  - Prefer liquid ETFs or low-turnover event signals.
  - Judge edges by long backtests plus pre-registered forward tests sized by the trade-count arithmetic above.
- **Realistic return expectation for a $200-$500 account:** dollar P&L will be tiny (a 5% annual edge on $300 is $15 a year). The value of the exercise is learning and infrastructure, not income.

### Gaps
- No study found reporting the fraction of US retail stock (non-options) day traders profitable over 1-3 months.
- No 2024-2026 Robinhood/retail profitability study was found in this pass.
- The Brazil paper's peer-reviewed publication status was not confirmed.
