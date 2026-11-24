# Short-horizon edges in US crypto SPOT markets for a small retail bot ($200–$500, long-only)

Research date: 2026-11-24. Scope: long-only spot on regulated US venues with APIs; derivatives only where clearly open to US retail. Note: most of the academic evidence covers 2011–2021 and is several years old.

## 1. Current US fee schedules for small accounts (under $10k monthly volume)

### Takeaway
Fees at small-account tiers are the main obstacle. A taker round trip costs about 0.5% on Alpaca, 1.6% on Kraken Pro, 1.2–1.8% on Coinbase Advanced (US) and 2.4% on Gemini. Alpaca is three to five times cheaper than the rest. Any idea that trades more than a few times a month has to clear a 0.3–2.4% hurdle per round trip, before the bid-ask spread.

### Cited Findings
- **Alpaca crypto**, tier 1 ($0–$100k 30-day volume): 0.15% maker / 0.25% taker. Tier 2 ($100k–$500k): 0.12% / 0.22%. Doc page last updated 2025-09-24. — [Alpaca crypto fees](https://docs.alpaca.markets/docs/crypto-fees)
- **Kraken Pro spot**, tier 1 ($0+): 0.40% maker / 0.80% taker. $2.5k+: 0.30% / 0.60%. $10k+: 0.22% / 0.38%. $25k+: 0.20% / 0.35%. A 0.02% discount applies on 634 selected pairs. Stablecoin and FX pairs (for example USDT/USD) cost 0.20% / 0.20% at tier 1. USDG/USD costs 0.00% / 0.01%. The spot table has no date; fetched November 2026. — [Kraken Pro fees](https://www.kraken.com/pro/fees)
- **Gemini ActiveTrader**, schedule dated September 1, 2026: lowest tier (≥$0) is 0.600% maker / 1.200% taker. $10k: 0.400% / 0.800%. $25k: 0.250% / 0.500%. $75k: 0.125% / 0.250%. Tiers are recalculated daily. — [Gemini ActiveTrader fee schedule](https://www.gemini.com/fees/activetrader-fee-schedule)
- **Coinbase Advanced Trade** (the official help page returned HTTP 403, so these figures are from secondary sources):
  - Before September 16, 2026, the $0–$10k tier was 0.40% maker / 0.60% taker. This comes from third-party tables dated May and August 2026. — [CoinCodeCap](https://coincodecap.com/coinbase-fees); [BrokerChooser](https://brokerchooser.com/broker-reviews/coinbase-review/coinbase-fees)
  - A restructuring took effect September 16, 2026. The entry tier now starts at $10k qualifying volume (down from $25k). US entry-tier spot fees are reported as **0.50% maker / 0.90% taker**, compared with 0.25% / 0.50% in the EU/UK and 0.09% / 0.10% in Brazil, India and some other markets. — [CryptoDaily, Sept 2026](https://cryptodaily.co.uk/2026/09/coinbase-advanced-fees-usdc-vip-tiers). Altrady (updated October 2026) agrees: US fees start at 0.50% / 0.90% and fall to 0.35% / 0.75% from $10k monthly volume. — [Altrady](https://www.altrady.com/blog/crypto-trading-platforms/coinbase-advanced-trade)
  - **Conflict:** the sources disagree on whether 0.40% / 0.60% still applies to US accounts under $10k after September 16, 2026. In March 2026 a user reported being moved to an "Intro-1" tier with a 1.2% taker / 0.60% maker fee. — [Stocktwits](https://stocktwits.com/news-articles/markets/cryptocurrency/coinbase-faces-criticism-for-fee-structure-again-nansen-ceo-calls-it-insane/cmUY2VlR49B)

### Inferences
- Round-trip costs at the lowest tier, fees only (no spread or slippage):

  | Venue | Maker round trip | Taker round trip |
  |---|---|---|
  | Alpaca | 0.30% | 0.50% |
  | Kraken Pro | 0.80% | 1.60% |
  | Coinbase (US, post-Sept 2026, reported) | 1.00% | 1.80% |
  | Coinbase (pre-Sept 2026) | 0.80% | 1.20% |
  | Gemini | 1.20% | 2.40% |

- A $500 account that trades its full balance weekly does about $4k of round-trip volume a month. That never leaves the lowest tier on any of these venues. Volume discounts are out of reach for this account size.
- Alpaca is the only venue where a weekly-rebalance strategy is plausibly viable. For example, 52 round trips a year at 0.5% is about 26% a year in fees on Alpaca, compared with about 83% on Kraken tier 1. Even at Alpaca's maker rate, 52 round trips cost about 15.6% a year.

### Gaps
- I could not reach Coinbase's own fee page (HTTP 403), so the exact current US 0–$10k tier needs checking in the account's order preview.
- Alpaca's crypto spreads, and how its execution compares with direct exchange order books, were not measured.
- I did not verify which coins Alpaca lists (it is a much smaller universe than Coinbase or Kraken).

## 2. Time-series momentum / trend following in BTC/ETH (Liu & Tsyvinski 2021; Liu, Tsyvinski & Wu 2022; later out-of-sample evidence)

### Takeaway
The original papers find strong in-sample time-series momentum at daily and weekly horizons, measured mostly on 2011–2018 data. Later out-of-sample and high-frequency work finds the edge decays sharply and does not survive realistic costs when turnover is high. A low-turnover weekly or longer trend filter is the only version worth testing, and it is most realistic on Alpaca.

### Cited Findings
- Liu & Tsyvinski (RFS 2021, vol 34(6), pp. 2689–2727) find significant time-series momentum at daily and weekly frequencies for Bitcoin, Ripple and Ethereum. — [NBER w24877](https://www.nber.org/papers/w24877); [SSRN](https://papers.ssrn.com/abstract=3226806)
- For Bitcoin, a one-standard-deviation rise in the current week's return goes with a 3.16% higher return the next week. — [VoxEU summary](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies)
- In the NBER draft, at the 1-week horizon the top quintile averages about 11.2% a week (Sharpe about 0.45–0.48) and the bottom quintile 2.60% a week. The figures differ slightly between drafts. — [NBER w24877 PDF](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)
- Liu, Tsyvinski & Wu ("Common Risk Factors in Cryptocurrency", JF 2022): a long-short one-week cross-sectional momentum strategy earns about 2.7% a week in excess returns, and their CSMB and CMOM factors account for it. — [Cowles PDF](https://cowles.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf)
- Shen et al., "Bitcoin intraday time-series momentum":
  - The intraday momentum effect holds across exchanges and out of sample.
  - The mean Sharpe ratio of technical-rule portfolios falls from 0.66 in-sample to 0.06 out-of-sample.
  - Returns do not survive modest transaction costs out of sample.

  — [Reading accepted version](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf); [ResearchGate](https://www.researchgate.net/publication/355603160_Bitcoin_intraday_time_series_momentum)
- In a walk-forward ML study on hourly BTC (arXiv 2606.00060, 2026), the 24-hour momentum benchmark loses heavily after transaction costs because it trades too often. — [arXiv 2606.00060](https://arxiv.org/html/2606.00060v1)
- "Dynamic time series momentum of cryptocurrencies" reports momentum profits after costs. It also warns that the choice of sample period and the fee assumption strongly drive profitability. — [PDF](https://community.portfolio123.com/uploads/short-url/amrMsuqIKzdHcHHyvMud4YNPwZB.pdf)

### Inferences
- **Mechanism:** slow diffusion of information and attention, plus retail herding and feedback trading. In a long-only setting the strategy becomes "hold BTC/ETH when the trailing return is positive, otherwise hold cash/USD." It switches rarely, which keeps the fee drag small.
- **Risk:** BTC's annualized volatility has historically been very high, roughly 50–80% (my assumption, not sourced here). A trend filter mainly cuts deep drawdowns. It does not raise the Sharpe ratio much out of sample, and it whipsaws in sideways markets, paying the round-trip cost each time.
- **Capacity at $200–$500:** not a constraint. Fractional crypto orders are possible on Alpaca, Kraken and Coinbase.
- **Time to evidence:** a weekly signal produces about 52 decisions a year. The strategy switches only a handful of times a year, so it would take years of live trading to distinguish skill from luck. Paper trading plus a long backtest (BTC daily data back to about 2014) is the practical route.
- **Data/API:** free daily and hourly OHLCV from the Coinbase, Kraken and Alpaca market-data APIs.
- **Legal:** spot trading is fine for US residents. Gains are taxable, and each switch to cash is a taxable event.
- **Verdict: worth testing.** Use a low-frequency (weekly or longer) BTC/ETH trend filter on Alpaca, with limit orders. Skip intraday or daily-flip versions; the evidence above says costs kill them.

### Gaps
- I found no rigorous 2022–2026 out-of-sample study of weekly BTC trend filters with net-of-fee figures at retail fee levels.
- Volatility and drawdown figures for trend-filtered BTC were not sourced.

## 3. Day-of-week, weekend and intraday (time-of-day) effects

### Takeaway
Volatility, volume and liquidity show strong, well-documented intraday and weekly patterns. Return patterns are weak, unstable and differ by asset. None of the sources tested them net of costs. At retail fee levels (0.3–1.8% per round trip) a trade-every-day seasonality strategy will not survive.

### Cited Findings
- Strong periodicity in volatility and liquidity exists by day of week, hour of day and even within the hour. — [arXiv 2109.12142](https://arxiv.org/pdf/2109.12142)
- Centralized exchanges worldwide show pronounced time-of-day patterns in activity, volatility and liquidity. These patterns are not driven solely by trading halts in other markets. — [Review of Quantitative Finance and Accounting (Springer), 2024](https://link.springer.com/article/10.1007/s11156-024-01304-1)
- Time-of-day trading surges raise volatility and transaction costs but have no significant adverse price impact. — [ResearchGate](https://www.researchgate.net/publication/334727071_Time-of-Day_Periodicities_of_Trading_Volume_and_Volatility_in_Bitcoin_Exchange_Does_the_Stock_Market_Matter)
- Volatility rises during weekdays and falls on weekends. — [arXiv 2009.04200](https://arxiv.org/pdf/2009.04200)
- Day-of-week return effects look unreliable. Some individual weekdays are significant, but joint tests find no reliable weekday pattern, and the significant hours differ by coin. This is a secondary, non-peer-reviewed source. — [ML Quants Substack](https://mlquants.substack.com/p/are-day-of-the-week-effects-in-cryptocurrencies); [Securities.io](https://www.securities.io/crypto-day-of-the-week-effects-intraday-patterns/)

### Inferences
- The useful, robust finding is about **execution**: place limit orders during high-liquidity hours (US/EU overlap) to cut spread and slippage. It is not an alpha source in its own right.
- A daily seasonality trade makes about 365 round trips a year. Even on Alpaca's maker rate that is about 110% a year in fees, so it is infeasible.
- **Verdict: skip as a stand-alone edge.** Use time-of-day only as an execution-timing overlay.

### Gaps
- I found no peer-reviewed study showing that crypto day-of-week or hour-of-day *return* effects survive costs out of sample.
- The full texts of the key papers were not checked for their cost assumptions.

## 4. Cross-sectional momentum and reversal among altcoins (survivorship and liquidity issues)

### Takeaway
Published results depend heavily on size, liquidity and survivorship. Large caps show short-horizon momentum. Small and illiquid coins show reversal driven by illiquidity. Once delisting bias is corrected, the momentum premium may vanish. The academic versions are long-short, which this account cannot do.

### Cited Findings
- Liu, Tsyvinski & Wu: one-week long-short momentum earns about 2.7% a week (in-sample). — [Cowles PDF](https://cowles.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf)
- "Up or down?" (International Review of Financial Analysis; more than 3,600 coins, 2015–2021) finds that daily reversals stem from the illiquidity of most coins, while the handful of largest, most tradeable coins show daily momentum. — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1057521921002349)
- Finance Research Letters 2024 (survivorship-free sample of 24,625 coins): large caps show significant momentum; small and mid caps show reversal. — [DOI](https://doi.org/10.1016/j.frl.2024.106531)
- "Survivorship and Delisting Bias in Cryptocurrency Markets" (St. Gallen working paper, 3,904 coins, 2014–2021):
  - Momentum and market beta show no positive relation with returns once delisting returns are included.
  - The size effect is overstated in survival-conditioned samples.
  - A non-trivial share of published crypto anomaly evidence is an artefact of data truncation.

  — [Working paper](https://www.sebastianstoeckl.com/publications/wp2022_liebi_survivorship/)
- Dobrynskaya: short-horizon momentum turns into reversal at longer holding periods. — [HSE PDF](https://conference.hse.ru/files/download_file_ex?hash=FAE0AB2DC7A67656E89A0B1CB27D8C7D&id=3B5EE9A5-0B18-458A-9458-B4ED0F6C6664)
- Another study finds strong time-series momentum but weak cross-sectional momentum. — [AUT/ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)

### Inferences
- A long-only "hold the top-k large caps by one-week return" strategy captures only the long leg. In crypto that leg is highly correlated with BTC beta, so it is mostly beta plus turnover cost.
- Weekly rebalancing across 3–5 coins at $200–$500 means many small orders. Minimum order sizes and per-coin spreads on thin altcoin pairs, which are wider than BTC, add to the fee drag.
- Using a US exchange's current listing as the universe adds survivorship bias to any backtest.
- **Verdict: skip, or at most "maybe"** as a large-cap-only, low-turnover variant on Alpaca. The best-documented profits rely on shorting and on illiquid coins the account cannot trade efficiently.

### Gaps
- I found no study of long-only, large-cap, US-listed altcoin momentum net of retail fees.

## 5. Funding-rate and basis carry trades (derivatives needed)

### Takeaway
Carry needs a short derivative leg, and US retail now has regulated access. Coinbase Financial Markets (CFM) launched CFTC-regulated "perpetual-style" nano BTC and ETH futures for US retail on July 21, 2025, and Kraken also offers US perps. CME micro futures need a futures broker. Carry is therefore *available* but outside a spot-only mandate, and at $200–$500 a single hedged contract may exceed the capital.

### Cited Findings
- CFM launched US perpetual-style futures on July 21, 2025:
  - Contracts: nano BTC-PERP (1/100 BTC) and nano ETH-PERP (1/10 ETH).
  - Expiry: 5-year, not monthly or quarterly.
  - Leverage: capped at 10x.
  - Fees: reported as low as 0.02%.
  - Access: requires a separate CFM derivatives application.

  — [CryptoSlate](https://cryptoslate.com/coinbase-starts-cftc-regulated-perpetuals-for-us-traders-offering-10x-leverage-and-0-02-fees/); [The Block](https://www.theblock.co/amp/post/363796/coinbase-launches-perpetual-futures); [Decrypt](https://decrypt.co/331180/coinbase-opens-perpetuals-trading-us-customers)
- Decrypt describes Coinbase as "following Kraken's lead" in offering perps to US customers, so Kraken also offers US perps. — [Decrypt](https://decrypt.co/331180/coinbase-opens-perpetuals-trading-us-customers)
- Coinbase's earlier nano Bitcoin dated futures for US retail date from its 2021 FCM approval. — [The Block](https://www.theblock.co/amp/post/260396/coinbase-crypto-futures-for-retail-us-traders-goes-live-includes-nano-bitcoin-trading)
- "Crypto carry: market segmentation and price distortions" (VoxEU/CEPR) studies crypto futures carry as a segmentation and price-distortion phenomenon. The page returned 403, so I could not extract its figures. — [VoxEU](https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets)

### Inferences
- A cash-and-carry trade means long spot BTC plus short one nano BTC-PERP (0.01 BTC). Its notional is 0.01 × the BTC price, for example about $1,000 if BTC is about $100k (an assumption; check the live price). That likely exceeds a $200–$500 account once margin is added.
- The ETH nano (0.1 ETH) may fit the budget better.
- **Verdict: maybe.** Treat it as a separate project only if the mandate is widened to regulated derivatives. It is unavailable under a strict spot-only rule.

### Gaps
- Current CFM funding-rate history, margin minimums, and the dollar minimum per contract were not verified.
- Carry return figures (annualized basis, Sharpe) from the Schmeling, Schrimpf & Todorov line of work could not be retrieved; source them before citing.

## 6. Cross-exchange arbitrage among US exchanges

### Takeaway
Makarov & Schoar (JFE 2020) document large, recurrent arbitrage spreads, but they are much larger *across countries* (capital controls) than *within* a country. Between US venues the spread has to beat two taker fees (roughly 1.0–2.4% combined at the lowest tiers), plus withdrawal fees and transfer delays. At $200–$500 this is not viable.

### Cited Findings
- Makarov & Schoar, "Trading and Arbitrage in Cryptocurrency Markets," Journal of Financial Economics 2020:
  - Large, recurrent arbitrage opportunities exist across exchanges.
  - Deviations are much larger across than within countries, which points to capital controls limiting arbitrage capital.

  — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301746); [MIT DSpace](https://dspace.mit.edu/bitstream/handle/1721.1/130495/SSRN-id3171204.pdf)

### Inferences
- **Fee hurdle:** a simultaneous buy on Alpaca and sell on Kraken costs about 0.25% + 0.80% = 1.05% in taker fees before withdrawal fees. Within-US BTC spreads among major venues are normally far below that (assumption; not measured here).
- **Inventory approach:** pre-positioning inventory on both venues removes the transfer delay but halves capital per venue and adds rebalancing withdrawals.
- **Verdict: skip.**

### Gaps
- I did not measure current US cross-venue BTC/ETH spreads, on-chain transfer times, or withdrawal fees.

## 7. Evidence on retail crypto trader profitability and drawdowns

### Takeaway
BIS evidence says most retail crypto app users lost money on bitcoin, and a few made large gains.

### Cited Findings
- BIS Bulletin No 69 ("Crypto shocks and retail losses," Cornelli, Doerr, Frost & Gambacorta, February 2023): the majority of crypto app users in nearly all economies likely lost money on bitcoin, and only a few investors made large gains. The bulletin also links this to a possible wealth transfer to insiders. — [BIS Bulletin 69](https://www.bis.org/publications/bulletin-69-crypto-shocks-and-retail-losses.pdf); related [BIS WP 1049](https://www.bis.org/publ/work1049.pdf)

### Inferences
- The default outcome for retail is a loss. Any bot should be benchmarked against simple buy-and-hold of BTC net of one round-trip fee, and against cash.

### Gaps
- The exact BIS percentage of losers (I recall about three-quarters; unverified because the PDF text could not be extracted) and its sample dates need checking from the PDF.
- I found no sourced, current figures for typical retail drawdowns or for the share of active day-traders (as opposed to holders) who are profitable.

## Summary verdicts (for the report writer)

| Idea | Verdict | Main reason |
|---|---|---|
| Weekly or slower BTC/ETH trend filter, long or cash, on Alpaca | **Worth testing** | Documented momentum and low turnover. Alpaca's 0.30–0.50% round trip is tolerable. |
| Large-cap long-only cross-sectional momentum | Maybe (weak) | Long leg is mostly beta. Survivorship-corrected evidence is weak. |
| Day-of-week / intraday return seasonality | Skip (use only for execution timing) | Unstable returns and too much turnover for retail fees. |
| Funding / basis carry | Maybe, only if derivatives are allowed | Regulated US perps exist (CFM, Kraken), but contract size may exceed capital. |
| US cross-exchange arbitrage | Skip | Two taker fees exceed typical within-US spreads. Transfer delays add risk. |
