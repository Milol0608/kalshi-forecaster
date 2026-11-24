# Kalshi market categories beyond daily-high temperature, and Kalshi fees, for a $200–$500 bot

Research date: 2026-11-24. "Measured" means I queried Kalshi's public, unauthenticated REST API (`https://api.elections.kalshi.com/trade-api/v2`) on 2026-11-24. Volumes are in **contracts**, and each contract costs at most $1, so the dollar notional is below the contract count. The API returned at most 1,000 settled markets per series, so these figures cover only recent events.

## 1. Kalshi's current fee schedule (taker formula, maker fees, which series pay them)

### Takeaway
The current schedule is "Fee Schedule for July 2026 – 7.7.26 Update", effective 2026-07-07.

- **Taker fee:** `roundup(M × 0.07 × C × P × (1−P))`, with a default multiplier M of 1. That is at most 1.75¢ per contract, at P = 50¢.
- **Maker fee:** `roundup(M × 0.0175 × C × P × (1−P))`, but the default maker multiplier is **0**.
- **Which series charge makers:** makers pay only in series listed with a maker multiplier of 1. These are mostly economics (CPI, Fed, payrolls, U3, GDP), the monthly gas series, yearly index ranges and most big sports and award series.
- **Weather, TSA, daily and weekly gas:** these series are not listed, so on my reading of the schedule they pay **taker 0.07 and maker 0**.

### Cited Findings
- **Taker formula:** "fees = round up(M x 0.07 x C x P x (1-P))", where P is the price in dollars, C the number of contracts and M a multiplier that defaults to 1. Fees are charged only on orders that execute immediately against resting orders. — [Kalshi Fee Schedule, July 2026 (7.7.26 update), local copy `docs/kalshi-fee-schedule.pdf`; live page kalshi.com/fee-schedule](https://kalshi.com/fee-schedule)
- **Maker formula:** "fees = round up(M x 0.0175 x C x P x (1-P))", where **M defaults to 0 unless otherwise indicated**. Maker fees are charged only when a resting order actually executes. Cancelling is free. — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)
- **Rounding:** the schedule says the round-up applies "such that the fee + positionCost is rounded to a centicent" ($0.0001). Its own table, however, shows a single contract paying $0.01 at prices of 1–15¢ and 85–99¢, and $0.02 at 20–80¢. A 100-contract order pays $0.07 at 1¢, $0.63 at 10¢, $1.75 at 50¢ and $0.63 at 90¢. — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)
- **Other fees:**
  - None for settlement, membership, or ACH deposits and withdrawals.
  - Up to 2% on debit-card deposits.
  - Kalshi "reserves the right to charge between 0% and 2%" on all payment rails.
  — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)
- **Non-standard series (maker multiplier / taker multiplier):**
  - **1/1, economics:** KXCPI, KXCPIYOY, KXFED, KXFEDDECISION, KXGDP, KXPAYROLLS, KXU3, KXRATECUTCOUNT, KXEGGS.
  - **1/1, gas and index:** KXAAAGASM (monthly US gas price), KXINXY (S&P 500 yearly range) and KXNASDAQ100Y.
  - **1/1, other:** KXIPO, KXLLM1, the Emmy and other award series, and most championship and game sports series (KXNFLGAME, KXMLBGAME, KXNBA, KXUCLGAME, KXWCGAME, ATP/WTA matches and others).
  - **0/0 (fee-free):** several long-dated political and crypto year-end series, for example KXBTCY, KXETHY, KXGREENLAND, KXCITRINI and KXLAYOFFSYINFO.
  - **KXMVE (combos):** shows a multiplier of 12 in the text extraction. This may be an extraction artifact; check before relying on it.
  — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)
- **Not listed as non-standard, so general schedule applies:** weather series (KXHIGH*, KXLOWT*, KXRAIN*, snow), TSA (KXTSAW and KXTSAD), and daily and weekly gas (KXAAAGASD and KXAAAGASW). On my reading that means **taker 0.07 and maker 0**. — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)
- **History:** Kalshi charged takers only (0.07·P·(1−P), rounded up to the cent) and charged makers nothing until it "began to charge fees on Makers after April 2025". — [Bürgi, Deng & Whelan, Jan 2026 draft](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Perpetual futures** (a separate product) use a basis-point fee ladder: taker 12 bps at tier 0, maker 5 bps at tier 0. — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)

### Inferences
- **Taker cost as a share of stake** is 0.07·(1−P). That is about 6.3% at 10¢, 3.5% at 50¢ and 0.7% at 90¢, before any per-order rounding.
  - For a small bot buying a few contracts at a time, rounding to the cent can multiply this. One contract at 5¢ pays 1¢, which is a 20% fee.
  - **A $200–$500 bot should trade in lots of 10–100 contracts per order, or rest maker orders.**
- **Maker orders are fee-free** in every non-sports, non-econ category in scope here (weather, TSA, daily and weekly gas). This is the single largest structural lever for a small bot.
- **Econ markets are not fee-free for makers.** In CPI, payrolls, Fed and monthly gas, makers pay 0.0175·P·(1−P), at most 0.44¢ per contract.

### Gaps
- I did not verify the live kalshi.com/fee-schedule page for fee changes scheduled after July 7, 2026. The page returned HTTP 429 or 403 to automated fetches. The schedule itself says "Please refer to https://kalshi.com/fee-schedule for scheduled upcoming fee changes."
- I could not confirm whether the KXMVE "12" is a multiplier or an extraction artifact.

## 2. Bürgi, Deng & Whelan, "Makers and Takers": returns by price, maker vs taker, category and year

### Takeaway
The data are 313,972 contract observations from 2021 to April 2025, covering markets that traded at least $1,000 in volume.

- **Average pre-fee return:** −20%.
- **Makers vs Takers:** Takers averaged **−31.46%** after fees and Makers **−9.64%**.
- **Longshots:** contracts priced 10¢ or below lose over 60%.
- **Favorites:** contracts above 70¢ earn small, statistically significant positive post-fee returns. Makers buying at 50¢ or more earned **+2.6%** on average.
- **Over time:** there is no clear evidence that the bias has shrunk. The 2025 slope is lower but only marginally significant (p < 0.1).
- **Not a strategy return:** returns are averaged per contract and per snapshot, not per dollar traded, and the sample predates maker fees.

### Cited Findings
- **Data:**
  - Transaction-level API data from 2021 through April 2025.
  - Contracts with at least $1,000 total volume. Final bid–ask spreads above 20¢ were dropped.
  - Hourly crypto and index markets were excluded.
  - 12,403 events and 313,972 Yes/No contract observations (a contract can appear at up to 11 snapshot times).
  — [Bürgi, Deng & Whelan, Jan 2026](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Returns by price:**
  - "Average loss rates for contracts costing 10c and under are over 60%." Losses fall as price rises, and there are small positive returns above 50¢.
  - "For contracts above 70c, there is evidence of statistically significant, though small, positive post-fee returns."
  - Worked examples: a 5¢ contract that wins 3% of the time returns −40% before fees, and a 95¢ contract that wins 98% returns +3.1%.
  - The average pre-fee return across contracts is −20%.
  — [Bürgi, Deng & Whelan, Jan 2026](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Makers vs Takers:**
  - "The average return on contracts for Makers was -9.64% while for Takers it was -31.46%."
  - "On average, Makers who buy contracts costing 50c and over earn a 2.6% rate of return."
  - Makers buy 43.5% of 1–10¢ contracts but 56.5% of 90–99¢ contracts (Table 10).
  — [Bürgi, Deng & Whelan, Jan 2026](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Fees in the paper:** Taker fees are computed on 100-contract lots. Rounding makes the effective fee at 50¢ equal to 1.77% of price rather than 1.75%. — [Bürgi, Deng & Whelan, Jan 2026](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **By category (Table 8):** a regression of pre-fee profit (in cents) on price, using makers' contracts (n = 156,986 overall).

  | Category | Slope | Intercept | n | Break-even price |
  |---|---|---|---|---|
  | All | 0.034 | −1.736 | 156,986 | ~51¢ |
  | Financials | 0.032 | −1.431 | 27,123 | ~45¢ |
  | Climate & Weather | 0.031 | −0.997 | 29,924 | ~32¢ |
  | Crypto | 0.058 | −1.944 | 8,150 | ~34¢ |
  | Politics | 0.022 (n.s.) | −1.912 | 26,819 | |
  | Entertainment | 0.020 (n.s.) | −2.809 | 25,541 | |
  | Economics | 0.034 | −0.978 (n.s.) | 24,405 | |
  | Other | 0.053 | −2.392 | 15,192 | |

  A favorite–longshot bias is significant in every category by the F-test. The break-even prices are my own calculation, −intercept ÷ slope. — [Bürgi, Deng & Whelan, Jan 2026](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **By year (Table 9):**

  | Year | Slope | n |
  |---|---|---|
  | 2021 | 0.041 | 3,855 |
  | 2022 | 0.023 | 24,913 |
  | 2023 | 0.036 | 23,559 |
  | 2024 | 0.048 | 53,338 |
  | 2025 (Jan–Apr) | 0.021 (p < 0.1) | 51,321 |

  The unbiasedness F-test rejects in every year. — [Bürgi, Deng & Whelan, Jan 2026](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Versions:** the paper circulates as UCD WP2025_19 (2025), CEPR DP20631, CESifo WP 12122 and GWU WP 2026-001 (Feb 2026). — [IDEAS/RePEc](https://ideas.repec.org/p/cpr/ceprdp/20631.html); [GWU](https://www2.gwu.edu/~forcpgm/2026-001.pdf); [CESifo](https://www.ifo.de/DocDL/cesifo1_wp12122.pdf)

### Inferences
- **Category ranking:** Climate & Weather has the smallest intercept among the significant categories, i.e. the mildest longshot penalty. Weather is among the more efficient Kalshi categories in this sample, not the least.
- **The one robust, testable edge is "be a maker on favorites (≥50–70¢)"**, worth about +2.6% per contract historically. That is thin.
  - Since 2025, makers pay 0.0175·P·(1−P) in the listed series, about 0.4% of stake at 70¢. Makers remain fee-free in weather, TSA and daily gas.
  - **Assumption:** the +2.6% figure also embeds adverse selection on fills that a small bot would face differently. It is not a backtest of a bot.
- **On whether the bias is shrinking:** the slope has not trended steadily down. The 2025 point estimate is the lowest and the least significant, which is weak evidence of shrinking as volume grew.

### Gaps
- I did not find a 2025–2026 follow-up paper using post-April-2025 data, after maker fees and the sports boom. I could not fetch the VoxEU summary (HTTP 403).
- The paper's Figure 5 and 6 bucket-level numbers (other than those quoted above) are only in charts and could not be extracted as text.

## 3. TSA checkpoint markets (KXTSAW weekly, KXTSAD daily)

### Takeaway
**Verdict: MAYBE, but capacity is tiny.**

- **How it settles:** KXTSAW settles on TSA's published Monday–Sunday average of screenings. Revisions after expiration are excluded.
- **When data arrive:** TSA posts on weekdays by about 9 a.m. ET, so Saturday and Sunday counts arrive Monday.
- **What is known mid-week:** by the Friday-morning post the bot knows 4 of the 7 days (Mon–Thu). Friday, Saturday and Sunday stay unknown until the market has closed.
- **Size:** about 8–43k contracts per week across all 21 strikes, with roughly 1–3 strikes trading in the 10–90¢ range at any time.
- **Edge:** the nowcast edge on published days is real in principle, but the books are thin. Practitioners report "$20/week"-scale capacity.

### Cited Findings
- **Settlement:** a KXTSAW market resolves Yes "If weekly average TSA airport screenings are above [X] for the week ending [Sunday]… according to the TSA". There are 21 strikes per event. — [Kalshi API, market KXTSAW-26NOV15-A2.80, measured 2026-11-24](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXTSAW&status=settled)
- **Timing:**
  - Close is Sunday 11:59 pm ET.
  - Expected expiration is Monday 15:00 UTC (10 a.m. ET), with a latest-expiration fallback a week later.
  - Settlement was recorded Tuesday 15:00 UTC.
  - The settlement value for the week ending 2026-11-15 was 2,317,821.
  — [Kalshi API](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXTSAW&status=settled)
- **Rules in the CFTC filing:** the value is the Monday–Sunday average of TSA checkpoint numbers, using data published before expiration, with later revisions excluded. The 2023 filing changed expiration from 10:00 to 9:00 AM ET, so the timing may have changed since. — [CFTC filing, TSAW rules](https://www.cftc.gov/filings/orgrules/rules0426231013.pdf)
- **When TSA publishes:** TSA's passenger-volumes page is updated Monday–Friday by about 9 a.m. ET, holiday weeks can be later, and figures can be adjusted after first posting. These details come from search-result summaries of [tsa.gov passenger volumes](https://tsa.gov/travel/passenger-volumes) and third-party mirrors. I did not fetch the TSA page directly, so treat weekday-only posting as likely but unconfirmed.
- **Volume (measured, contracts per weekly event, last 8 settled weeks):** 8,430; 7,323; 11,811; 12,679; 9,220; 14,919; 19,669; 43,020. The median is about 12.7k, and 43k was the Thanksgiving-adjacent week ending 2026-11-15. — [Kalshi API, measured 2026-11-24](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXTSAW&status=settled)
- **Daily KXTSAD volume (measured, last 8 events):** 4,131; 3,065; 3,562; 1,556; 4,493; 1,843; 1,570; 1,396. The median is about 3k contracts per day across about 15 strikes. — [Kalshi API](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXTSAD&status=settled)
- **How fast prices converge (my own measurement from hourly candlesticks, last 9 weeks):**
  - Only 4–20 of 21 strikes had traded by mid-week, and only **1–3 strikes per week sat between 10¢ and 90¢**.
  - Mean absolute error of last-trade price against the outcome on traded strikes:

    | Checkpoint | Mean abs. error |
    |---|---|
    | Tuesday | 0.05–0.25 |
    | Thursday | 0.04–0.19 |
    | Saturday | 0.04–0.14 |

  - These are last-trade prices in illiquid books, so staleness inflates the errors. This **does not prove mispricing**, only that the books are thin and stale. — [Kalshi API candlesticks, measured 2026-11-24](https://api.elections.kalshi.com/trade-api/v2/series/KXTSAW/markets/KXTSAW-26NOV15-A2.80/candlesticks)
- **Practitioner reports:**
  - **Ferraiolo's TSA bot (simple rolling-average model):** traded "a few weeks" and did "surprisingly well". No P&L numbers are given. Liquidity was "very low": he "could probably make $20/week" and found it "hard to buy more than a handful of contracts at a time". — [Ferraiolo TSA bot series](https://ferraijv.github.io/kalshi_tsa_trading_bot_overview/)
  - **Another bot write-up:** estimates about $10,000 traded per week across all strikes. — [labradords Substack](https://labradords.substack.com/p/kalshi-tsa-check-in-trading-bot-part) (via search snippet, not fetched)
  - **A data archive:** shows about 33 trades per day and an average spread of about 7.5¢. — [CryptoStruct KXTSAW](https://cryptostruct.com/prediction-markets/kalshi-kxtsaw) (via search snippet, not fetched)
  - **A Medium post:** reports a best-model weekly-average miss of about 1,412 passengers, and notes that Kalshi prices already incorporate Monday's number hours before a weekly model refit. — [Sussmeier, Medium](https://medium.com/@colesussmeier/statistical-arbitrage-on-kalshi-2e8ca0470eb5) (via search snippet; fetch returned 403; post date unknown)
- **No out-of-sample P&L:** I found no source with a measured out-of-sample P&L for a TSA strategy. — [search summary](https://www.turbinefi.com/blog/kalshi-automation-time-savings-case-study-2026)

### Inferences
- **What the forecast has to do:** with Mon–Thu known by Friday morning, the remaining uncertainty is three days of a strongly seasonal, day-of-week-patterned series (holidays aside). A simple model (same weekday last year × YoY trend) should put most strikes beyond 95/5 by Friday.
- **The likely edge is maker liquidity provision near the decisive strike**, not buying stale mispriced strikes. It is maker fee-free, but with roughly a 7.5¢ spread and a few hundred contracts of depth.
- **Capacity:** realistic capacity is probably tens of dollars of edge per week. That fits a $200–500 account but will not scale.
- **Time to evidence:** 52 weekly events per year, so a forward test needs about 3–6 months to say anything. KXTSAD (daily, about 3k contracts) gives faster samples but is even thinner.
- **Data cost:** TSA data are free, and the Kalshi API is free.

### Gaps
- The exact daily TSA posting time was not verified on tsa.gov directly. Whether the Friday post includes Thursday was inferred, not confirmed.
- The order-book depth at the decisive strike was not measured. The last-trade-price errors cannot separate stale quotes from genuine mispricing.

## 4. Other weather markets: daily LOW, rain, snow, hourly temperature, monthly precipitation

### Takeaway
**Verdict: daily LOW maybe; everything else skip for now.**

- **Daily LOW:** the only other weather series with daily, regular liquidity. NYC low trades about 20–40k contracts per day, against about 160k for the NYC high. Chicago low is about 13k. It uses the same settlement source as the highs, so the existing NBM pipeline transfers directly.
- **Rain, snow, monthly and hourly:** sporadic (often one market per event) or illiquid, and most daily-rain series showed almost no settled history in the API.
- **Mispricing:** I found no credible evidence of mispricing in any of them. The published weather backtests (all on highs) found no after-fee edge.

### Cited Findings
- **Volume (measured, contracts per daily event, last 8 events):**
  - KXHIGHNY: 149k–221k, median about 162k.
  - KXHIGHCHI: median about 53k.
  - **KXLOWTNYC: 11k–41k, median about 31k.**
  - KXLOWTCHI: 4k–16k, median about 13k.
  - All have 6 strikes per event.
  — [Kalshi API, measured 2026-11-24](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXLOWTNYC&status=settled)
- **Rain series (measured):**
  - KXRAINDNYC (Daily Rain NYC, settled by The Weather Company): only 3 settled single-market events were visible, at 47k, 4k and 3k contracts, the last on 2026-11-02.
  - KXRAINNYCM (monthly NYC rain): 3 events at 113k, 25k and 0.8k.
  - KXRAINNYCW (weekly): 1 event at 1.8k.
  — [Kalshi API](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXRAINDNYC&status=settled)
- **Snow and hourly series (measured):** KXTEMPNYCH (hourly NYC temperature) and KXNYCSNOWM showed no settled markets in the API on 2026-11-24. They may be inactive or listed seasonally. — [Kalshi API](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXTEMPNYCH&status=settled)
- **Settlement sources (series metadata):**
  - The Weather Company settles the KXLOWT* series (NYC, CHI, MIA, LAX, SAN), the daily rain series KXRAIND*, and the hourly KXTEMP*H series.
  - Synoptic Data, or "Kalshi", settles some "HS" hourly variants.
  - The NWS Climatological Report or NOAA settles older series (KXRAINNYC, KXRAINNYCM, KXSNOWNYM).
  - The series list for "Climate and Weather" had 540 series.
  — [Kalshi API /series?category=Climate and Weather](https://api.elections.kalshi.com/trade-api/v2/series?category=Climate%20and%20Weather)
- **Weather backtests:**
  - **GitHub walk-forward backtest of daily highs, about 48 days per city:** "Can free weather data beat Kalshi's temperature markets? … (answer: no)". The best after-fee combination lost about 5¢. Longshot NO lost in every bucket. Only the maker results looked profitable, and the author says those assume every order fills, so they are an upper bound. Winter is untested. — [MiguelTheGamer/kalshi-weather-backtest](https://github.com/MiguelTheGamer/kalshi-weather-backtest)
  - **1,506 weather events, three strategies:** none was consistently profitable after fees. Tail-selling came closest to break-even. — [oddsreference.com](https://oddsreference.com/predictions/research/kalshi-weather-model)
  - **A vendor site:** claims "favorite-band NO" returns 1.5–2.4% per trade after fees. It gives no methodology or sample size, and the vendor sells trading content. It is unverified. — [predictionpilot.io](https://predictionpilot.io/markets/weather)

### Inferences
- **Daily LOW:** the cheapest new category to test. It is the same model family, the same settlement source as the existing high-temperature work (assuming the project's highs also settle on The Weather Company), and maker fee-free.
  - With about 30k contracts per day in NYC, $200–500 positions fit.
  - Lows are arguably harder to forecast (radiational cooling, timing of the overnight minimum), which cuts both ways.
  - Time to evidence: daily events across 5 cities give about 150 settled events per month. Expect signal in 4–8 weeks.
- **Rain, snow and hourly:** skip for now. Daily rain is a single binary per day with sporadic volume. Hourly series were not live. Monthly and snow series offer a handful of events per season, so time to evidence is a year or more.

### Gaps
- No per-category mispricing study exists for lows, rain or snow. The settled-market API listing caps at 1,000, so long histories were not pulled.
- I did not confirm whether the project's current KXHIGH settlement source is The Weather Company.

## 5. Gas prices, box office, Billboard/Spotify, mentions, and economics (Fed, CPI, jobs)

### Takeaway
- **Gas (AAA):** deeply liquid, at about 2M contracts per week (KXAAAGASW) and 0.4M per day (KXAAAGASD). It is fee-free for makers in the daily and weekly series but not the monthly. AAA's figure moves slowly and is pre-announced each morning, so it is almost certainly arbitraged by fast players. **Maybe**, only as a maker.
- **Economics (CPI, payrolls, U3, Fed):** the biggest volume on the list (Fed decision about 22–103M contracts per event, CPI about 1.6M). Professionals price these against futures and nowcasts, and makers pay fees. **Skip.**
- **Mentions, Spotify, Billboard and box office:** there are thousands of one-off series. Evidence of an edge is absent. **Skip** for a systematic bot.

### Cited Findings
- **Volume (measured, contracts per event, latest settled):**

  | Series | Contracts per event |
  |---|---|
  | KXAAAGASD (daily gas) | 245k–633k, median about 417k |
  | KXAAAGASW (weekly gas) | 0.6M–3.1M, median about 2.0M |
  | KXAAAGASM (monthly gas) | 0.36M and 1.6M |
  | KXCPI | about 1.5–1.6M |
  | KXPAYROLLS | 352k–437k |
  | KXU3 | 384k–539k |
  | KXFEDDECISION | 22.4M and 103.2M |

  — [Kalshi API, measured 2026-11-24](https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXAAAGASW&status=settled)
- **Fees:** KXAAAGASM, KXCPI, KXCPIYOY, KXPAYROLLS, KXU3, KXFED, KXFEDDECISION, KXGDP and KXEGGS all carry a maker multiplier of 1 (0.0175·P·(1−P)). KXAAAGASD and KXAAAGASW are not listed, so on my reading the default applies: maker 0. — [Kalshi Fee Schedule July 2026](https://kalshi.com/fee-schedule)
- **Mentions and entertainment series:**
  - The full series list returned 16,814 series. Mention markets are mostly "one_off": earnings-call mentions (Palantir, IBM, Caterpillar and others) and speech mentions (Powell, Vance, Newsom and others, settled by ABC or company IR).
  - Entertainment includes daily Spotify chart series (KXSPOTIFY4D, KXSPOTIFYUKD), weekly Billboard series (KXHOT100, KXBILLBOARDRUNNERUPSONG) and many one-off stream-count series.
  — [Kalshi API /series](https://api.elections.kalshi.com/trade-api/v2/series)
- **Entertainment and Politics** show the most negative intercepts in the 2021–Apr 2025 sample (−2.81 and −1.91), with insignificant price slopes. Cheap contracts there are the worst bets, and there is no reliable favorite premium. — [Bürgi, Deng & Whelan, Table 8](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Economics** shows the smallest and insignificant intercept (−0.98), meaning near-efficient pricing. — [Bürgi, Deng & Whelan, Table 8](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Gas and mentions backtests:** none found in my searches. — [search summary; no source]

### Inferences
- **Economics markets:** the edge would require beating Cleveland Fed nowcasts, fed funds futures and professional desks. Volumes are large because pros are there. A $200–500 bot has no informational advantage, and the bias evidence shows near-efficiency. **Skip.**
- **Gas (daily and weekly):**
  - The settlement value (AAA national average) is published each morning, and moves are small and autocorrelated. The mispricing a small bot could catch is probably milliseconds-to-minutes stale quotes, a speed game.
  - Being a fee-free maker on favorites (≥70¢) in daily gas is the only angle, consistent with Bürgi et al.'s maker-favorite result.
  - Time to evidence: daily, so 4–8 weeks. **Maybe**, low priority.
  - **Assumption:** I did not verify AAA's publication time or Kalshi's KXAAAGASD close time.
- **Mentions:** these hinge on the transcript content of one-off events. There is no repeatable data feed or base rate a bot can model systematically, and they are thin and one-off. **Skip.**
- **Spotify daily chart (KXSPOTIFY4D):** at least data-driven (kworb and Spotify charts). However, I found no liquidity data or evidence of mispricing. Not tested here; low priority.

### Gaps
- I did not measure volume for Spotify, Billboard, box-office or mention series.
- I did not verify AAA's or Spotify's data publication times.
- I found no practitioner or academic evidence on gas, mention or chart markets.

## 6. Academic or practitioner evidence of profitable systematic Kalshi strategies after fees

### Takeaway
**There is no credible public evidence of a profitable systematic retail Kalshi strategy after fees.**

- **Academic:** the one robust finding is the maker-favorite premium (+2.6%, pre-maker-fee era).
- **Weather backtests:** the open ones conclude "no".
- **TSA:** practitioners report small anecdotal wins capped by liquidity.

### Cited Findings
- **Bürgi et al.:** makers buying at 50¢ or more earned +2.6%, and contracts above 70¢ earned small significant positive returns after fees. Takers lost 31% on average. — [Bürgi, Deng & Whelan](https://www.karlwhelan.com/Papers/Kalshi.pdf)
- **Kalshi's own blog** discusses the paper. — [Kalshi blog "Makers and Takers"](https://kalshi.com/blog/article/makers-and-takers) (not fetched)
- **Weather (GitHub):** the walk-forward backtest says no edge with free weather data. Maker results are an upper bound because fills are assumed. — [GitHub](https://github.com/MiguelTheGamer/kalshi-weather-backtest)
- **Weather (oddsreference):** across 1,506 events, three strategies, none profitable after fees. — [oddsreference.com](https://oddsreference.com/predictions/research/kalshi-weather-model)
- **Weather (turbinefi, vendor):** 500 strategies on NYC highs. Four families went 0-for-50, and out-of-sample validity of the winners is not established. — [turbinefi.com](https://www.turbinefi.com/blog/how-to-trade-kalshi-weather-markets-2026)
- **Bot timing (secondary claim):** a secondary blog citing Bloomberg (April 2026) says bots win by entering earlier at better prices rather than by forecasting better. I did not verify the Bloomberg original. — [turbinefi.com](https://www.turbinefi.com/blog/kalshi-automation-time-savings-case-study-2026)
- **TSA:** "surprisingly well" but "$20/week" capacity. — [Ferraiolo](https://ferraijv.github.io/kalshi_tsa_trading_bot_overview/)

### Inferences
- **Summary verdicts for a $200–$500 paper-first bot:**

  | Category | Verdict | Note |
  |---|---|---|
  | Daily LOW temperature | **Worth testing** | Reuses the existing pipeline; maker fee-free; about 30k contracts per day in NYC; 4–8 weeks to evidence |
  | Maker-on-favorites (≥70¢) in fee-free maker series (weather, daily gas, TSA) | **Worth testing** | The only academically supported pattern. Must model fill and adverse selection honestly. Expected edge is low single-digit % per contract |
  | TSA weekly/daily | **Maybe** | Real informational structure (4/7 days known by Friday) but tiny depth; 3–6 months to evidence |
  | Daily/weekly gas | **Maybe (low)** | Liquid but likely a speed game |
  | Rain, snow, hourly, monthly precipitation | **Skip** | Too sporadic or inactive |
  | Econ (CPI, jobs, Fed) | **Skip** | Pros, maker fees, efficient |
  | Mentions, Billboard/Spotify, box office | **Skip** | One-off, no evidence |
  | Taker longshots (≤10¢) anywhere | **Skip** | Over 60% average loss |

- **Return expectations:** a realistic upper bound is a few percent per contract on a maker strategy, at a capacity of a few hundred dollars. Absolute expected profit on $200–500 is likely single-to-low-double-digit dollars per month even if an edge exists. **Assumption**, extrapolated from the +2.6% figure and the measured depth.

### Gaps
- I found no peer-reviewed or audited out-of-sample P&L for any Kalshi retail strategy after the April 2025 maker-fee change.
- I found no evidence on how the favorite–longshot bias behaved after April 2025.
