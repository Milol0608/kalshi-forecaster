# US-regulated event-contract venues and cross-venue arbitrage with Kalshi (as of 24 Nov 2026)

Research date: 2026-11-24. Many sources are third-party review or affiliate sites, and they often disagree. Where that happens, both versions are given. Facts from earlier years are dated.

## Q1. Which venues can a US resident trade via API, and what do they cost?

### Takeaway
A US retail bot has three realistic API venues: **Kalshi** (the baseline), **Polymarket US** (CFTC-regulated, public Retail API since Feb 2026, taker fees about the same size as Kalshi's), and **ForecastEx through the IBKR TWS API** (near-zero fees but thinner and narrower). PredictIt bans bots. Robinhood, Coinbase, FanDuel/CME and Crypto.com are mainly app distribution channels, and I found no retail trading API for any of them.

### Cited Findings

**Polymarket US (QCX LLC / QCEX)**
- Launched invite-only on 3 Dec 2025 through QCX LLC. Public API access opened 16 Feb 2026. REST base `https://api.polymarket.us`, WebSockets `/v1/ws/markets` and `/v1/ws/private`, Ed25519 key auth, 20 req/s per key. Full KYC required (ID, SSN, proof of address via the iOS app). No sandbox or demo. — [AgentBets Polymarket US API guide](https://agentbets.ai/guides/polymarket-us-api-guide/)
- **Conflict:** another guide (Oct 2026) says "no public trading API is documented". The official changelog contradicts that: it documents a "Retail API" with a 20 req/s per-key limit (10 Apr 2026), and says RFQs and combos are available to all Retail API users (1 Oct 2026). — [polymarket101 guide](https://www.polymarket101.com/en/docs/guides/polymarket-us-vs-international-2026/) vs [docs.polymarket.us changelog](https://docs.polymarket.us/changelog)
- Fee formula Θ × C × p × (1−p). Taker Θ = 0.06 from 1 Jul 2026, which is $1.50 per 100 contracts at p = 0.50. The maker Θ of 0.0125 was a rebate. — [AgentBets](https://agentbets.ai/guides/polymarket-us-api-guide/)
- **Fees changed again.** From 19 Oct 2026 the flat maker rebate became volume-tiered: none below $10M monthly maker volume, so **zero for a small bot**. Taker rebates also start only at $250K monthly volume (3%). A new combo taker fee takes effect 11 Nov 2026. — [docs.polymarket.us changelog](https://docs.polymarket.us/changelog)
- **Conflicting fee reports:** one site cites Θ values that vary by category (4%, 5% and 7% since July 2026). Another cites a 10 Nov 2026 weekly notice to the CFTC listing eight tiers from 0.1170 to 0.0650, which conflicts with the published docs. — [polymarket101](https://www.polymarket101.com/en/docs/guides/polymarket-us-vs-international-2026/); search summary of [Totalis](https://www.totalis.trade/blogs/prediction-markets/polymarket-fees) / [SharpFootballAnalysis](https://www.sharpfootballanalysis.com/prediction-markets/polymarket/)
- Temporary 70% taker-fee rebate on "straight" trades sent through the API direct connection, until 31 Dec (reported 23 Nov 2026). App trades keep the 0–30% tiered rebate. — [ChainCatcher](https://www.chaincatcher.com/en/article/2307128), citing The Defiant
- Categories: sports (deepest, including in-game), politics, crypto, weather, tech, culture, economics. No geopolitics or long-tail markets. Funded in USD only, no crypto. Claimed legal in all 50 states, but state litigation is ongoing: a May 2026 Ninth Circuit ruling denied a pause of the Nevada and Washington enforcement actions. — [polymarket101](https://www.polymarket101.com/en/docs/guides/polymarket-us-vs-international-2026/)
- Polymarket International (the crypto/UMA venue) is not legal for US residents. Polymarket paid $1.4M in its 2022 CFTC settlement. — [polymarket101](https://www.polymarket101.com/en/docs/guides/polymarket-us-vs-international-2026/)

**Kalshi (baseline)**
- Standard taker fee = roundup(0.07 × C × p × (1−p)) to the next cent, so $1.75 per 100 contracts at 50¢. Maker fees (0.0175, a quarter of the taker rate) apply on about 129 series, including most major sports plus CPI, Fed and jobs markets. Other series have a maker multiplier of 0. The API exposes `fee_type` and `fee_multiplier` per series, and `fee_cost`/`is_taker` per fill. — [Kalshi fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf); [OddsShopper](https://www.oddsshopper.com/articles/prediction-markets/kalshi-fee-schedule-by-market); [DEV/polytrage](https://dev.to/polytrage/kalshis-fee-structure-explained-55lg)
- Fee schedule versions are dated 5 Feb 2026 and 7 Jul 2026 in different sources. A copy of the schedule sits in this repo at `docs/kalshi-fee-schedule.pdf`, untracked. — [CFTC filing 0712269458](https://www.cftc.gov/filings/orgrules/rules0712269458.pdf)

**ForecastEx (Interactive Brokers)**
- IBKR commission is $0.00 per contract. The ForecastEx exchange fee is $0.01 per contract, per side. — [IBKR pricing](https://brokerage.ibkr.com/en/pricing/commissions-events.php?re=amer); [CFTC ForecastEx filing](https://www.cftc.gov/filings/orgrules/rules09082624298.pdf)
- ForecastEx keeps 50 bp of the interest earned on cash collateral. Historically it paid holders an incentive coupon on open positions (my recollection, not re-verified for 2026). — [CFTC filing](https://www.cftc.gov/filings/orgrules/rules09082624298.pdf)
- The TWS API supports Forecast Contracts (secType OPT, exchange FORECASTX). The docs also list KALSHI and CME as exchange values for event products. You cannot sell: you exit by buying the opposite contract. TIF is Day, GTC or IOC only, in whole contracts. Contracts pay $0 or $1 with $0.01 ticks. Requires the event-contract permission. — [IBKR TWS API event-trading docs](https://www.interactivebrokers.com/docs/tws-api/doc/event-trading/introduction.md); [IBKR Campus](https://www.interactivebrokers.com/campus/ibkr-api-page/event-trading/)

**Robinhood**
- Prediction markets launched March 2025 with contracts from KalshiEX. — [The Block](https://www.theblock.co/post/346670/robinhood-teams-up-with-kalshi-to-launch-prediction-markets-hub-focusing-on-politics-economics-and-sports); [Axios](https://www.axios.com/2025/03/17/robinhood-prediction-markets-kalshi-sports)
- Robinhood is building its own exchange through a joint venture with Susquehanna and the MIAXdx acquisition, expected to operate in 2026. One AI-generated summary claims it now routes some World Cup contracts away from Kalshi (unconfirmed). — [Cointelegraph](https://cointelegraph.com/news/robinhood-prediction-markets-growth-derivatives-exchange-2026); [FinanceMagnates](https://www.financemagnates.com/fintech/robinhood-shares-surge-11-as-fintech-seeks-independence-from-kalshi-in-prediction-markets/); [Sacra](https://sacra.com/chat/h/80d02a58-a694-4379-99a5-3ca5281d3192/)

**Crypto.com (CDNA / "OG"), CME / FanDuel, Coinbase**
- Crypto.com Derivatives North America is CFTC-registered, sells under the OG Prediction Markets brand, and offers sports contracts nationwide. — [Crypto.com news](https://crypto.com/us/company-news/fanduel-predicts-to-expand-event-contract-offering-through-partnership-with-cryptocom-and-og-prediction-markets); [Fast Company](https://www.fastcompany.com/91396620/crypto-com-bets-big-on-sports-prediction-markets)
- The FanDuel Predicts app comes from a FanDuel–CME joint venture. It lists CME and (from June 2026) Crypto.com contracts. — [FOW](https://www.fow.com/insights/fanduel-partners-with-crypto-com-to-expand-event-contract-offering); [FinanceMagnates](https://www.financemagnates.com/forex/cme-brings-wall-street-to-sports-bettors-with-new-event-contracts-partnership)
- Coinbase offers prediction markets through a Kalshi deal. It is a member of the Coalition for Prediction Markets alongside Kalshi, Crypto.com, Robinhood and Underdog. — [Front Office Sports](https://frontofficesports.com/draftkings-coinbase-dive-into-prediction-markets-in-wild-week/); [Casino.org](https://www.casino.org/news/crypto-com-kalshi-form-prediction-markets-coalition/)

**PredictIt**
- Relaunched 15 Jul 2025 under an amended CFTC no-action letter. The per-contract cap went from $850 to $3,500 and the 5,000-trader cap was removed. One Aug 2026 review still says $850, which looks like an outlier. Its DCM application is shown as **Pending** on the CFTC site. — [GlobeNewswire (Jul 2025)](https://www.globenewswire.com/news-release/2025/07/16/3116432/0/en/PredictIt-Announces-Regulatory-Agreement-Supporting-Broader-Public-Participation.html); [Bloomberg](https://www.bloomberg.com/news/articles/2025-07-15/predictit-says-it-can-expand-political-trades-under-cftc-deal); [CFTC](https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/66541); [tech-insider (conflicting)](https://tech-insider.org/prediction-markets/platforms/predictit-review/)
- Fees: 10% of net profit per market and 5% on withdrawals (secondary source only). The API is a read-only feed. Its terms (inspected 6 Oct 2026) ban automated trading and scraping. — [CryptoSlate](https://cryptoslate.com/prediction-markets/predictit-review/); [Alphascope](https://www.alphascope.app/blog/predictit-api)

### Inferences
- For a bot that pairs against Kalshi, only Polymarket US and ForecastEx are usable. PredictIt is out on its terms of service, and with 10% on profit plus 5% on withdrawal it is also uneconomic at this size.
- Polymarket US's taker cost at mid prices (about 1.5¢ at 50¢) is close to Kalshi's (about 1.75¢). A small bot gets no maker rebate after 19 Oct 2026, so the fees that matter in a Kalshi pair are mostly taker on both legs.
- ForecastEx is the cheapest leg (about 1¢ per contract flat), but its markets lean toward economics, politics and climate, so overlap with Kalshi is narrower.
- Nadex (now Crypto.com/CDNA) and CME event contracts have no documented retail bot API for event contracts. I found nothing usable.

### Gaps
- Official Polymarket US fee page not fetched. I could not settle the category-Θ vs flat-0.06 vs eight-tier conflict. Read docs.polymarket.us/fees before modelling.
- Not confirmed whether IBKR's KALSHI exchange code gives API access to Kalshi markets through IBKR.
- No API docs or fees found for Crypto.com OG, Robinhood's own exchange, or Coinbase event contracts.
- Kalshi's current API rate limits were not checked.

## Q2. Evidence on cross-venue price gaps (size, frequency, persistence)

### Takeaway
Gaps between overlapping markets are documented and can last hours to months at the level of "hold to resolution". They are usually 2–4¢ at the median, and they persist mainly because the contracts are not truly identical (settlement wording) and because capital is locked up. Fast gaps on liquid sports markets close in seconds.

### Cited Findings
- Gebele & Matthes (TUM, arXiv 2601.01706, Jan 2026), covering 102,275 events across 10 platforms including Kalshi, Polymarket and PredictIt, data to Aug 2025:
  - Only about 6% of events have a cross-platform counterpart. About 8% of Polymarket markets have an equivalent elsewhere, against about 2% of Kalshi markets.
  - Median deviation from execution-adjusted parity is 2–4% even for the most liquid pairs. Many pairs show an opportunity nearly all the time.
  - On the 2024 presidential market (Polymarket vs Kalshi), execution-adjusted spreads averaged about 3¢ and held at up to 7¢ for sustained intervals.
  - A naive hold-to-resolution strategy returned 1,218.66% cumulative over 800 days, but from only **15 trades**.
  - Causes: resolution semantics (e.g. Polymarket resolves on network calls while Kalshi resolves on inauguration), regulatory segmentation of traders, capital lockup, and fee and tick differences.
  - Source: [arXiv 2601.01706](https://arxiv.org/html/2601.01706v1)
- Saguillo et al. (AFT 2025, arXiv 2508.03474) estimate about $40M of arbitrage profit realized on Polymarket from 1 Apr 2024 to 1 Apr 2025. This counts within-market rebalancing and combinatorial arbitrage on one venue, not cross-venue. — [arXiv 2508.03474](https://arxiv.org/abs/2508.03474)
- Gebele, Mutzel & Matthes (arXiv 2608.00666, 1 Aug 2026) estimate $1.12M of arbitrage profit in Polymarket negative-risk markets: $1.086M converter-enabled, $32K settlement-based. Violations the protocol cannot execute (YES side) persist longer. — [arXiv 2608.00666](https://arxiv.org/abs/2608.00666)
- Practitioner, not peer-reviewed: a Kalshi–Polymarket sports matcher saw 870 gaps in 24h with a median life of about 9 seconds, 96% closed within 30 s. Total net arbitrage over one whole World Cup match was $439. The author concluded "no sizable arbitrage". — [DEV Community](https://dev.to/michaelmustopo/built-a-prediction-market-arbitrage-no-sizable-arbitrage-found-36cf)
- Settlement mismatch risk: Kalshi settles by its rulebook source while Polymarket International uses the UMA oracle, so both legs can lose. — [NexusFi](https://nexusfi.com/a/prediction-markets/arbitrage-prediction-markets); [arXiv 2610.00183](https://arxiv.org/pdf/2610.00183)

### Inferences
- Two different regimes exist:
  - **Fast arb** on liquid sports markets: latency-bound, seconds long, competed away by professionals. Not feasible for a small bot polling REST at 20 req/s.
  - **Slow structural arb**: politics, economics and long-dated markets with a persistent 2–7¢ gap, which pays only at resolution and carries rule-mismatch risk.
- Most evidence comes from Polymarket International (crypto) vs Kalshi. Polymarket US is a separate order book with USD funding and a US-only trader base. Gaps between Kalshi and Polymarket US may be smaller, since trader populations overlap more, but I found no measurement.

### Gaps
- No study specifically on Kalshi vs Polymarket US, or Kalshi vs ForecastEx, for 2026.
- Could not extract the full text of 2608.00666 (PDF unreadable without pypdf). Only the abstract was used.

## Q3. Realistic net return at $200–$500, plus legal and terms risks

### Takeaway
At small size, taker-on-both-legs arbitrage needs a gap above about 3.3¢ at mid prices just to break even, and then ties up capital on two venues until resolution. Expected net is roughly 0–2% per trade, with a tail risk of losing both legs on a rule mismatch. Worth monitoring and paper-trading, not deploying.

### Cited Findings
- Fee inputs: Kalshi taker 0.07·p(1−p), rounded up per order ([Kalshi](https://kalshi.com/docs/kalshi-fee-schedule.pdf)); Polymarket US taker 0.06·p(1−p) ([AgentBets](https://agentbets.ai/guides/polymarket-us-api-guide/)); ForecastEx $0.01 per contract ([IBKR](https://brokerage.ibkr.com/en/pricing/commissions-events.php?re=amer)).
- Polymarket US API access requires full KYC, and the KYC'd entity is responsible for autonomous-agent trading. Kalshi's API allows automation within its terms. PredictIt bans bots. — [AgentBets](https://agentbets.ai/guides/polymarket-us-api-guide/); [PredictionHunt](https://www.predictionhunt.com/blog/how-to-build-prediction-market-trading-bot-api-guide); [Alphascope](https://www.alphascope.app/blog/predictit-api)
- State-level legal risk persists for Polymarket US and sports contracts (Nevada and Washington actions, Ninth Circuit May 2026). — [polymarket101](https://www.polymarket101.com/en/docs/guides/polymarket-us-vs-international-2026/)

### Inferences (my arithmetic, not sourced)
- **Mid-price example.** Kalshi YES at 0.48 and Polymarket US NO at 0.49 cost 0.97, a 3¢ gross gap. Taker fees: Kalshi 0.07×0.25 ≈ 1.75¢ (rounds to 2¢ on a 1-contract order) and Polymarket US 0.06×0.25 = 1.5¢. Total ≈ 3.25–3.5¢, so the trade **loses** money. Break-even at mid prices is a gap of about 3.3¢ or more. At a 5¢ gap, net is about 1.6¢ on about $0.95 of capital, roughly 1.7% until resolution.
- **Tail-price example.** At p ≈ 0.9/0.1, fees are about 0.6¢ + 0.5¢ ≈ 1.1¢, so small gaps there are more capturable, but such gaps are rarer and smaller.
- **Kalshi + ForecastEx pair.** About 1.75¢ + 1¢ ≈ 2.75¢ at mid. Only works where the contracts truly match (e.g. CPI or Fed thresholds). Check strike definitions and settlement sources.
- **Capital.** $300 split across two venues gives about $150 per leg, so about 150 contract pairs at most. At 1.6¢ net, the best case is about $2.40 per opportunity, locked until resolution (days to months). Annualized yield can look high on short-dated markets, but the absolute dollars are trivial. A single rule mismatch that loses both legs (about $1 per pair) wipes out about 60 good trades.
- **Other costs.** Bank ACH funding at both venues, KYC at both, and IBKR account minimums or permissions. These are frictions, not fees, but they slow capital recycling.

### Verdicts for a $200–$500 account
- **Kalshi ↔ Polymarket US, slow structural gaps (econ, politics, weather): MAYBE / worth paper-testing.** Build a read-only matcher that logs Kalshi vs Polymarket US quotes on hand-verified identical markets and computes fee-adjusted gaps (Kalshi `fee_multiplier`, Polymarket US Θ). Run it for 4 weeks before risking anything. The temporary 70% API taker rebate (to 31 Dec 2026) lowers Polymarket US cost to about 0.45¢ at mid, but it expires.
- **Kalshi ↔ ForecastEx (economic data contracts): MAYBE.** Lowest fees, but limited overlap and API quirks (buy-only, IBKR stack). Paper-test only on matched CPI/Fed/jobs strikes.
- **Fast sports cross-venue arb: SKIP.** Gaps close in seconds, latency professionals dominate, and per the constraints it is research-only anyway.
- **PredictIt arb: SKIP.** Bots are banned and the 10% profit plus 5% withdrawal fees kill it.
- **Polymarket International: SKIP.** Not legal for US residents.
- **Robinhood, Coinbase, FanDuel/CME, Crypto.com OG as arb legs: SKIP for now.** No retail API found, and Robinhood and Coinbase largely route to Kalshi anyway.

### Gaps
- No published net-of-fee P&L for small-account cross-venue arbitrage on regulated US venues in 2026.
- Frequency of more than 3.3¢ gaps between Kalshi and Polymarket US on identical markets is unknown. It needs our own logging.
