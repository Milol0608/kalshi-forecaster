# Tennis prediction markets and other quick edge ideas for a small US retail bot

Researched 2026-11-24. Snapshot figures from Kalshi pages are dated where known; many are from July–Aug 2026 caches and may be stale. Most findings come from abstracts and secondary sources, not full-text papers. Where that is the case, the bullet says so.

## Q1. Tennis: are bookmaker or exchange prices beatable, and is a Kalshi tennis research path feasible and affordable?

### Takeaway
**Verdict: maybe. Worth only a cheap, offline backtest, and no live plan.**

- The academic record is consistent: bookmaker odds are the best available tennis forecaster. Kovalchik (2016) ranked a bookmaker consensus first and Elo first among data-only models. Wilkens (2021) found that ML betting returns were mostly negative and very volatile.
- Inefficiency is most plausible in lower-tier and lower-ranked matches. There, the favourite-longshot bias is larger and integrity risk (match-fixing) is higher.
- Kalshi now lists ATP, WTA, Challenger and ITF match markets. Tennis match series reportedly pay maker fees (0.0175 coefficient) on top of the taker fee (0.07).
- A small or negative edge after fees is therefore the base case.

### Cited Findings

**Market efficiency evidence**
- Kovalchik, "Searching for the GOAT of tennis win prediction" (J. Quantitative Analysis in Sports, 12(3):127–138, 2016) compared 11 pre-match models on 2014 ATP tour-level matches. The market-based Bookmaker Consensus Model performed best, and Elo was the best of the methods built on historical data. — [EconPapers/RePEc](https://econpapers.repec.org/RePEc:bpj:jqsprt:v:12:y:2016:i:3:p:127-138:n:1); [VU repository](https://vuir.vu.edu.au/34652/)
- Wilkens, "Sports prediction and betting models in the machine learning age: The case of tennis" (J. Sports Analytics 7(2):99–117, 2021, DOI 10.3233/JSA-200463):
  - Betting returns from ML predictions were highly volatile and mostly negative over the long run.
  - Model ensembles were the most promising approach.
  - Source: [abstract record](https://lida.sport-iat.de/twm/Record/4073773?lng=en).
  - A secondary review reports about 70% accuracy for gradient boosting and neural nets. This is not verified against the paper. — [arXiv review 2410.21484](https://arxiv.org/pdf/2410.21484)
- A 2020 JQAS study comparing forecasts across Grand Slams found that "betting odds perform relatively well." — [De Gruyter, jqas-2019-0110](https://www.degruyterbrill.com/document/doi/10.1515/jqas-2019-0110/pdf)
- Lahvička (2013), about 45,000 singles matches: the favourite-longshot bias is much stronger in matches between lower-ranked players, in later rounds, and at high-profile tournaments. — [MPRA 47905](https://mpra.ub.uni-muenchen.de/47905/1/MPRA_paper_47905.pdf)
- Forrest & McHale (2007), "Anyone for Tennis (Betting)?": the first test of longshot bias in men's tennis betting. I did not see its results. — [ResearchGate PDF](https://www.researchgate.net/profile/IG_Mchale/publication/24080578_Anyone_for_Tennis_Betting/links/550809ff0cf27e990e08caef/Anyone-for-Tennis-Betting.pdf)
- Valtonen (2013 thesis), 7,555 men's matches on a betting exchange, 2010–2013: no statistical test could reject market efficiency. — [Aalto thesis](https://epub.lib.aalto.fi/en/ethesis/id/13771)
- Hegarty & Whelan (UCD WP24/03): the common "inverse odds" efficiency test is biased toward accepting efficiency even when a favourite-longshot bias exists, shown on tennis and soccer data. Some "efficient" findings may therefore be artefacts of the test. — [UCD WP24_03](https://www.ucd.ie/economics/t4media/WP24_03.pdf)
- arXiv 2510.20454 (2025 preprint, not peer reviewed): a graph neural network model claims a +3.26% ROI with Kelly staking over 1,903 bets. It bet only on "high-intransitivity" matchups, which it says Pinnacle prices poorly. Treat this as unreplicated. — [arXiv 2510.20454](https://arxiv.org/html/2510.20454v1)
- Clegg & Cartlidge's replication of a tennis "Wikipedia buzz" strategy: most of the reported profit came from one erroneous bet. Once that was fixed, only one strategy (betting on "competitive" matches) stayed significant. This is a caution about data errors producing fake edges. — [arXiv 2306.01740](https://arxiv.org/html/2306.01740v4)

**Lower-tier integrity**
- The Independent Review Panel on tennis integrity found a "very significant" corruption problem at the lower and middle levels of the sport. Of more than 3,200 players surveyed, 464 said they had first-hand knowledge of match-fixing. — [ITIA IRP report](https://itia.tennis/media/bjuateer/irp-report-final.pdf); [Racing Post coverage](https://racingpost.com/sport/tennis-tips/tennis-match-fixing-report-highlights-issues-at-lowest-levels-of-sport-aeyqA7S6xYrB)
- Suspicious betting alerts rose after the ITF sold live scoring data in 2012. About 60,000 matches were open to betting in 2016, up from 40,000 in 2013. — [Yahoo/AP coverage](https://sports.yahoo.com/tennis-engulfed-apos-tsunami-apos-123211213.html)

**Kalshi tennis availability, liquidity and fees**
- Kalshi has a Challenger page (19 open matches at 4 events in the snapshot) and an ITF page (177 open matches at 29 events).
  - The Challenger page says no data feed covers the Challenger circuit, so events, rounds and results are the markets' own.
  - Sources: [Kalshi Challenger](https://kalshi.com/tennis/challenger); [Kalshi ITF](https://kalshi.com/tennis/itf); [ITF doubles](https://kalshi.com/category/sports/tennis/itf-doubles)
- Per-match volume varies widely in the snapshots (mostly July–Aug 2026, likely stale): one ITF match at about $1.32M, one ITF doubles match at $212, and an ATP Challenger Plovdiv match at about $16.9K. — [Kalshi tennis](https://kalshi.com/sports/tennis); [Kalshi tennis games](https://kalshi.com/category/sports/tennis/all/games)
- Contract types include match winner, set winner, total games, exact score and match margin. CFTC self-certifications from January and August 2026 cover the margin, game-differential and total-games contracts. — [CFTC ptc01272637960](https://www.cftc.gov/sites/default/files/filings/ptc/26/01/ptc01272637960.pdf); [CFTC ptc08242619654](https://www.cftc.gov/filings/ptc/ptc08242619654.pdf)
- Fees:
  - Taker fee: roundup(0.07 × C × P × (1−P)).
  - Maker fee: roundup(0.0175 × C × P × (1−P)), and it applies only to some series.
  - An API audit on Aug 11, 2026 found 129 of 12,699 series with maker fees. 106 of them are sports series, and "tennis matches" are among them; the article did not say which tours.
  - Source: [OddsShopper, Aug 12 2026](https://www.oddsshopper.com/articles/prediction-markets/kalshi-fee-schedule-by-market); see also [Kalshi help: market-specific fees](https://help.kalshi.com/getting-started/market-specific-fees)
- Worked example at P = 0.50: 100 contracts pay $1.75 as taker versus $0.44 as maker. Motley Fool describes the 50-cent taker cost as "up to 3.5%" of the amount staked. — [OddsShopper](https://www.oddsshopper.com/articles/prediction-markets/kalshi-fee-schedule-by-market); [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)

**Data sources and costs**
- tennis-data.co.uk: free ATP and WTA results and odds files (CSV/XLS) going back to 2000. The `deuce` R package uses its odds file. — [DataHub listing](https://old.datahub.io/dataset/atp-wta-professional-tennis-tournament-data); [deuce atp_odds.R](https://rdrr.io/github/skoval/deuce/src/R/atp_odds.R)
- The Odds API (official page), monthly plans:

  | Plan | Credits per month | Price |
  |---|---|---|
  | Free | 500 | $0 |
  | Paid | 20K | $30 |
  | Paid | 100K | $59 |
  | Paid | 5M | $119 |
  | Paid | 15M | $249 |

  - Paid plans include historical odds.
  - Historical tennis odds start around 2020, beginning with Grand Slams.
  - Third-party sources say historical calls cost 10× credits.
  - Sources: [the-odds-api.com](https://the-odds-api.com/); [tennis odds page](https://the-odds-api.com/sports/tennis-odds.html); [OddsPapi on credits (a competitor)](https://oddspapi.io/blog/the-odds-api-free-tier-limits)
- Betfair historical data:
  - Basic tier is free (last traded price at 1-minute intervals, no volume).
  - Advanced (1-second intervals) and PRO (50ms) cost extra; prices were not found.
  - Coverage is almost every exchange market back to 2016.
  - Betfair's data scientists say PRO files are required for robust backtesting.
  - Sources: [Betfair data scientists: data sources](https://betfair-datascientists.github.io/modelling/dataSources); [using the historic data site](https://betfair-datascientists.github.io/data/usingHistoricDataSite)
- Matchstat (commercial API) claims historical odds since 2010. — [matchstat](https://matchstat.com/predictions-tips/the-best-tennis-data-api-for-stats/)
- Pinnacle's API is closed to the public. — [OddsPapi blog](https://oddspapi.io/blog/?p=2938)

### Inferences
- **Fee hurdle.** A Kalshi tennis strategy has to beat about 1.75¢ per contract at P = 0.5 as a taker, or about 0.44¢ as a maker. Published "edges" against Pinnacle are about 3% ROI on selected subsets and unreplicated. Taker fees alone would consume a large share of that.
- **Where an edge could exist.**
  - Kalshi tennis prices may lag sharp books, especially on thin Challenger/ITF matches. That would make "Kalshi vs Pinnacle-implied probability" a more realistic signal than a home-built Elo model.
  - This is untested. Collect Kalshi tennis snapshots alongside an odds feed and measure the gap before modelling anything.
- **Integrity risk.** Lower tiers are where any mispricing is likeliest, but also where match-fixing is concentrated. Apparent edges there may be informed flow from fixers, which makes them adverse selection rather than real edges.
- **Cheapest research path, $0–60 per month.**
  1. Use tennis-data.co.uk (free) plus Jeff Sackmann-style results data to build Elo.
  2. Reproduce the Kovalchik result that the bookmaker beats Elo.
  3. Log Kalshi tennis order books through the existing bot's API code for 4–8 weeks.
  4. Compare against The Odds API at the $30–59 tier.
  5. Do not buy Betfair PRO or Sportradar unless step 3 shows a persistent gap.
- **Fit with existing work.** The repo already measured favourite-longshot bias in weather markets (commit 3155b73). The same test applied to Kalshi tennis is a natural low-cost extension.

### Gaps
- I could not verify that tennis-data.co.uk includes Pinnacle closing odds (columns PSW/PSL from memory) or covers Challenger/ITF; check its notes file directly. I believe it covers main tour only, but that is unverified.
- I found no OddsPortal terms of service in my searches. Scraping legality and terms are unresolved.
- Sportradar pricing is enterprise and unpublished; nothing was found.
- Betfair's paid-tier prices and whether US residents can buy historical data were not found.
- No study measures Kalshi tennis efficiency or Challenger/ITF pricing efficiency against Pinnacle.
- Whether the Kalshi maker fee covers Challenger/ITF or only ATP/WTA main-tour series is unknown. Check `docs/kalshi-fee-schedule.pdf` in the repo, or the Kalshi API series fee fields.
- I did not read the full text of Wilkens 2021 or Kovalchik 2016. Exact accuracy numbers (for example Elo versus bookmaker log-loss) are unverified.

## Q2. Matched betting and bonus arbitrage in the US

### Takeaway
**Verdict: skip (out of scope).**
- It is generally not illegal under state law. It does violate operator terms when it involves duplicate accounts, and it gets accounts limited.
- It sits outside CFTC-regulated prediction markets, cannot be automated against sportsbook terms, and is a one-off source of income rather than a repeatable bot edge.

### Cited Findings
- About 32 states permit statewide online or mobile sports wagering as of August 2026. — [tech-insider.org](https://tech-insider.org/sports-betting/are-online-sportsbooks-legal-in-the-usa/)
- An activity can be legal under state law and still lead to an account ban, because operators enforce their own terms. Duplicate accounts violate KYC terms and can lead to confiscated balances. — [Bleacher Nation, May 2026](https://www.bleachernation.com/betting/2026/05/17/can-i-delete-my-sportsbook/)
- Sportsbooks cite "abusing bonus offers" among their reasons for limiting accounts. — [ESPN](https://africa.espn.com/sports-betting/story/_/id/41231266/espn-sports-betting-news-sportsbooks-defend-practice-limiting-sharp-customers)
- Limits are legal across the US. New Jersey bars banning rule-abiding customers merely for winning, but differential limits are allowed. A New York "Fair Play Act" proposal would ban limiting winners. — [IBJ](https://www.ibj.com/articles/sportsbooks-say-you-can-win-big-then-they-try-to-limit-winners); [iGaming Business](https://igamingbusiness.com/sports-betting/new-york-fair-play-act-sportsbooks-limiting-ban/)
- Arbitrage-like patterns get flagged (secondary source). — [DeucesCracked](https://www.deucescracked.com/blog/sportsbook-account-limits-why-winning-bettors-get-restricted)

### Inferences
- Promo value is front-loaded, roughly a few hundred dollars per new account, and requires manual identity and KYC per operator. It is not a bot strategy and does not compound.

### Gaps
- I found no operator's actual promo-abuse clause text and no state regulator ruling on matched betting specifically.

## Q3. Retail-accessible weather derivatives beyond Kalshi (CME)

### Takeaway
**Verdict: skip for a $200–500 account.**
- CME HDD/CDD futures are $20 per index point. A monthly HDD index in winter is typically several hundred points, which implies a notional of thousands of dollars per contract.
- The market is thin and institutional, and futures accounts carry their own minimums.

### Cited Findings
- The CME monthly and seasonal HDD/CDD contract unit is $20 × the CME Degree Days index, with a minimum tick of 1 index point ($20). — [CME HDD contract specs](https://cmegroup.com/markets/weather/temperature/us-monthly-weather-heating.contractSpecs.html); [CME CDD specs](https://cmegroup.com/markets/weather/temperature/us-monthly-weather-cooling.contractSpecs.options.html)
- An older Kentucky PSC training page lists $100 per index point, which conflicts with CME's own specs and appears outdated. — [KY PSC](https://psc.ky.gov/agencies/psc/training/risk/tsld026.htm)
- Daily HDD/CDD uses a 65°F base. Seasonal strips run Nov–Mar for HDD and Apr–Oct for CDD. — [CME weather fact card](https://www.cmegroup.com/trading/weather/files/weather-fact-card.pdf)

### Inferences
- Example: a January HDD of about 900 points × $20 is about $18,000 notional, plus margin. That is far beyond $500. Kalshi daily temperature markets remain the only weather product sized for this bankroll.

### Gaps
- Current exchange and broker margin for HDD/CDD was not found.
- Open interest and liquidity figures were not found.
- Whether retail brokers (for example IBKR) allow weather futures was not verified.

## Q4. Public alternative data for event markets (TSA, AAA gas, BTS, box office)

### Takeaway
**Verdict: worth testing (TSA, AAA gas) as cheap nowcasting projects.**
- Kalshi lists daily and weekly TSA check-in markets and daily, weekly and monthly AAA gas markets, all settled on the same public source a bot can read.
- Any edge is nowcasting: knowing the partial week's TSA numbers before the market prices them, or extrapolating AAA's daily series.
- Expect it to be small and competed for. No published evidence of an edge was found.

### Cited Findings
- Kalshi's weekly "TSA avg check-ins" markets (KXTSAW) resolve on the Monday–Sunday average of TSA screenings, for example an outcome of 2,571,680 for one week. There is also a daily series (KXTSAD) with thresholds such as ≥2.7M. A snapshot showed "Above 2.5M" at 82% for the Oct 5–11, 2026 week. — [KXTSAW](https://kalshi.com/markets/kxtsaw/tsa-checkins-this-week); [KXTSAD Oct 11 2026](https://kalshi.com/markets/kxtsad/daily-tsa-passenger-screenings/kxtsad-26oct11)
- TSA market rules bar source-agency employees and holders of material non-public information. — [Kalshi KXTSAW market page](https://kalshi.com/markets/kxtsaw/tsa-checkins-this-week/kxtsaw-26oct11)
- AAA gas markets:
  - AAA is the Source Agency (gasprices.aaa.com), and a market resolves Yes if the national regular average is strictly above the strike on the measurement date.
  - Daily, weekly, monthly and yearly series exist; some yearly-range markets settle on EIA data instead.
  - Sources: [Kalshi AAAGAS contract terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/AAAGAS.pdf); [OddsShopper guide](https://www.oddsshopper.com/articles/prediction-markets/kalshi-gas-price-markets)

### Inferences
- **TSA weekly.** By Thursday or Friday, four or five of the seven daily values are published. The remaining days are highly predictable from same-weekday-last-year and holiday adjustments. Late-week weekly markets should be close to determined, so the question is whether the market already prices that.
  - The test: log Kalshi prices against a simple partial-week projection.
  - Data cost: $0.
- **AAA gas.** The daily national average moves slowly and is autocorrelated, so short-horizon strikes are mostly a volatility question. Wholesale RBOB futures lead retail by days, and that is a known lead-lag. This is also a $0 data test.
- **Box office and BTS.** Not assessed (see Gaps). Box-office tracking from The Numbers or Box Office Mojo is public but widely watched, so any lead time is likely minimal. This is unverified.

### Gaps
- No search results covered Kalshi box-office market rules or volumes.
- I did not examine the BTS airline data release lag.
- No study measures how quickly Kalshi TSA or gas prices incorporate published data.
- Order-book depth and volume for TSA and gas markets were not retrieved.

## Q5. Honest base rate: how many sports bettors and prediction-market traders are profitable?

### Takeaway
Most lose.
- Polymarket studies find 69–87% of wallets lose money, and profits are extremely concentrated: the top 1% of winners take 76–94% of profits.
- On Kalshi, CEPR research finds the average contract loses about 10–32% of the amount wagered, depending on maker versus taker.
- Sportsbooks limit only about 0.6% of accounts, but disproportionately the ones that beat the closing line. A US retail bot should assume a losing base rate unless it measures otherwise.

### Cited Findings
- Motley Fool (2026) analysed about 313K Polymarket wallets across 210 high-volume markets that resolved in 2025:
  - About 17% profited and more than 82% lost.
  - The median result was a loss of $0.16, and about 95% of wallets finished within ±$100.
  - The top 1% of winners took about 85% of profits.
  - **Sports wallets: 94% lost, and the top 1% took 94% of sports profits.**
  - The period predates Polymarket's 2026 fees.
  - Source: [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- CEPR (Akey et al.), more than 2.4M wallets and 588M trades, 2022–2026: 69% lost, and the top 1% of profitable users took 76.5% of profits. On Kalshi, the average contract lost about 10–32% of the amount wagered depending on whether the trader posted or accepted the price. Low-priced longshots underperform and high-priced contracts earn small positive returns. — cited via [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- Sergeenkov via The Defiant: about 2.5M wallets, 84% in the red. — cited via [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- Bloomberg (April 2026): since the start of 2025, more than 100,000 Polymarket accounts lost at least $1,000, almost twice the number that gained that much. 5% of wallets made 75% of volume, and the winners "look like bots." — [Bloomberg](https://bloomberg.com/news/articles/2026-04-28/most-prediction-market-traders-are-losing-money-while-bots-rack-up-gains); [Finance Magnates](https://www.financemagnates.com/fintech/100000-polymarket-wallets-lost-at-least-1000-bloomberg-analysis-shows/)
- Earlier claims put 2024 losers at 70%, with profits concentrated in under 0.04% of addresses. A LayerHub analysis found only 12.7% of wallets profitable (secondary crypto press, lower quality). — [KuCoin flash](https://www.kucoin.com/news/flash/polymarket-profitability-crisis-70-of-users-lose-money-profits-concentrated-among-0-04); [Decrypt](https://decrypt.co/290625/most-polymarket-traders-have-lost-money)
- Pew (May 7–Jun 19, 2026, 11,989 accounts): the average trader spent a little over $600 and lost less than $2. — cited via [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- Sportsbooks kept about 9.74% of wagers in 2025. — cited via [Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- Massachusetts Gaming Commission data (as of Dec 10, 2024, presented Sep 30, 2025):
  - 0.64% of accounts were limited, and 57.6% of those were capped at 1–24% of the default stake.
  - Bettors who consistently beat the closing line were more likely to have limits lowered.
  - Source: [Covers](https://www.covers.com/industry/massachusetts-limiting-sports-betting-prediction-markets-exchanges-sharps-box-september-2025)
- Wyoming also reports fewer than 1% of accounts limited. In the UK, 643,779 accounts were limited, about 4% of the total. — [SBC Americas](https://sbcamericas.com/2025/07/25/uk-regulator-sports-betting-limits/); [IBJ](https://www.ibj.com/articles/sportsbooks-say-you-can-win-big-then-they-try-to-limit-winners)

### Inferences
- Roughly 1 in 6 wallets profit in a single year, and about 1 in 20 sports wallets.
- Because profits are this concentrated, the realistic prior for a new small bot is "loses slowly to fees and spread" unless it is a maker with a measured edge.
- The CEPR finding that longshots underperform on Kalshi is consistent with the repo's own favourite-longshot work in weather markets.
- The share of US sportsbook bettors who are long-run profitable is not directly measured anywhere found. The 0.6% limit rate is a loose proxy for "sharp enough to get noticed" and should not be read as a profitability rate.

### Gaps
- No direct, primary Kalshi user-level P&L distribution was found; the Kalshi figure is via CEPR as cited by Motley Fool. I did not read the CEPR paper itself.
- No multi-month persistence study was found, that is, whether this year's winners win next year.
- No nationwide US figure exists for the share of profitable sportsbook customers.
