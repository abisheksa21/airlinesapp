# What is the Health Score?

The Health Score is a single number (0–100) that sums up how reliable a route, airport, or airline has been. Instead of making you read five separate numbers and guess what they add up to, we do that math for you and hand you one score, plus a plain label: **Excellent, Strong, Watch, Weak, or Critical.**

You can always see the five numbers behind it too — the score isn't hiding anything, it's just doing the averaging for you.

## The five ingredients

Think of the score like a report card with five subjects. Each one is scored 0–100 on its own, then we blend them together.

1. **Reliability** — how often flights actually arrive on time.
2. **Delay severity** — when flights *are* late, how late are they, on average?
3. **Severe-delay exposure** — how often is a flight *seriously* late (over an hour), not just a little late?
4. **Cancellation resilience** — how rarely do flights get cancelled outright?
5. **Diversion resilience** — how rarely does a flight get redirected to a different airport mid-trip?

## Why don't all five count equally?

This is the part worth explaining honestly, because it's easy to get wrong.

The simplest approach would be to just average all five equally, or pick weights that "feel right." We didn't want to do that, because a guess dressed up as a formula isn't actually more trustworthy than no formula at all.

Instead, we asked a real question: **if we only knew how a route performed in the past, which of these five things actually tells us something useful about how it'll perform in the future?**

Here's how we tested that. We took thousands of real routes and split each one's history chronologically into an earlier 70% chunk and a later 30% chunk. We calculated all five scores using *only* the earlier chunk. Then we checked: for each of the five, how well did it predict that same route's *actual* on-time performance in the later chunk — performance we hadn't shown it yet?

Some of the five turned out to be much better predictors than others. So instead of guessing, we let the past-vs-future test decide how much each one should count.

## What we found

- **Reliability** and **severe-delay exposure** turned out to be the strongest predictors of future performance. If a route has a track record of on-time flights, or a track record of *avoiding* seriously long delays, that tends to keep being true.
- **Delay severity** (how late flights typically run) was also a solid predictor.
- **Cancellations** were a much weaker predictor. A route having a cancelled flight in the past doesn't tell you much about whether it'll happen again — cancellations tend to be one-off events (bad weather that day, a mechanical issue) rather than a persistent trait of the route.
- **Diversions** were the weakest predictor of all. They're rare, and when they happen, it's usually due to very specific circumstances on that particular day — not something baked into how the route normally operates.

So the final weighting looks like this:

| Ingredient | Weight |
|---|---|
| Reliability | 29% |
| Severe-delay exposure | 27.5% |
| Delay severity | 25% |
| Cancellation resilience | 12.5% |
| Diversion resilience | 6% |

## What this score is — and isn't

**It is:** a fair, tested summary of past performance, weighted by what actually turned out to matter for predicting the future, not by what sounded reasonable.

**It isn't:** a guarantee. Even the strongest predictor in our test wasn't a perfect one — routes, airports, and airlines do change over time. A great score means "this has a strong track record," not "this will definitely go well next time you fly it."

**It also isn't:** a measure of things it was never built to measure — comfort, price, customer service, or anything outside of the flight actually running on schedule.

## The ratings, in plain terms

- **90–100: Excellent** — consistently reliable, rarely a problem.
- **80–89: Strong** — good track record, occasional hiccups.
- **70–79: Watch** — decent overall, but with a real weak spot worth knowing about.
- **60–69: Weak** — noticeably below average; expect delays or disruptions more often than not.
- **Below 60: Critical** — a genuinely rough track record across multiple dimensions.

---

# The full math, for anyone who wants it

Everything above is the honest summary. Below is exactly how the number is actually produced, step by step, with real formulas.

## Step 1: Five raw measurements

For whatever you're looking at (a route, an airport, or an airline, over whatever date range is selected), we start with five raw statistics computed directly from the flight data:

| Raw statistic | What it counts |
|---|---|
| `on_time_pct` | % of completed flights that arrived within 15 minutes of schedule (the same standard the US Department of Transportation uses) |
| `avg_delay` | average arrival delay, in minutes, across completed flights |
| `severe_delay_pct` | % of completed flights delayed more than 60 minutes |
| `cancellation_pct` | % of all scheduled flights that were cancelled |
| `diversion_pct` | % of all scheduled flights that were diverted to a different airport |

"Completed flights" excludes cancellations and diversions — those don't have a normal arrival delay to measure, so they're counted separately in their own components instead.

## Step 2: Convert each into a 0–100 component score

Each raw statistic gets turned into a score where **100 is best** and **0 is worst**, using these exact formulas:

```
reliability               = on_time_pct                        (capped to 0-100)
delay_severity             = 100 − (avg_delay × 2)               (capped to 0-100)
severe_delay_exposure      = 100 − (severe_delay_pct × 5)        (capped to 0-100)
cancellation_resilience    = 100 − (cancellation_pct × 10)       (capped to 0-100)
diversion_resilience       = 100 − (diversion_pct × 20)          (capped to 0-100)
```

Notice the multipliers get bigger as the underlying problem gets more severe — a 1-percentage-point rise in diversions costs 20 points, but a 1-minute rise in average delay only costs 2 points. That reflects that diversions, cancellations, and severe delays are worse passenger experiences than routine minor lateness, so they're penalized harder per unit.

## Step 3: Combine with the calibrated weights

The five component scores are combined into the final Health Score using a straightforward weighted sum:

```
Health Score =
    (reliability            × 0.290) +
    (delay_severity          × 0.251) +
    (severe_delay_exposure   × 0.275) +
    (cancellation_resilience × 0.125) +
    (diversion_resilience    × 0.059)
```

Those five weights sum to exactly 1.0, so the Health Score itself always lands between 0 and 100.

## Where the weights came from (the calibration method, in full)

1. **Split each route's history in two, by date.** Using the full 2018–present dataset, we found the midpoint that put roughly 70% of each route's flights in an "early" period and 30% in a "late" period.
2. **Compute all five component scores using only the early period.** This simulates "what we'd know about this route if we could only see its past."
3. **Compute the actual on-time rate the route went on to have in the late period.** This is the real, observed outcome — not a formula, just what actually happened.
4. **Repeat across every route with enough data in both periods** (minimum 100 flights per period, to avoid noisy small samples). This produced 6,133 qualifying routes.
5. **For each of the five components, calculate its Pearson correlation coefficient** with the route's actual future on-time rate. A correlation of 0 means no relationship at all; 1.0 would mean a perfect one; negative would mean the opposite relationship.

**What "Pearson correlation coefficient" actually means, and how it's calculated.** For two lists of paired numbers (here: each route's early-period component score, and that same route's actual late-period on-time rate), Pearson's r is:

```
r = Σ[(x - x̄)(y - ȳ)] / √[Σ(x - x̄)² × Σ(y - ȳ)²]

where x  = each route's early-period component score
      y  = that same route's actual late-period on-time rate
      x̄, ȳ = the average of all x's and all y's
      Σ   = "sum over every route"
```

In plain terms: for each route, check whether its component score and its future on-time rate are *both above average* or *both below average* at the same time (that pulls r toward +1), versus one being above average while the other is below (that pulls r toward -1). Routes where the two aren't related either way average out toward 0.

**A small illustrative example** — 5 made-up routes, not real site data, just enough points to show the formula actually working:

```
Route   Early reliability score (x)   Later actual on-time rate (y)
  1              92                              88
  2              78                              75
  3              85                              81
  4              65                              70
  5              90                              85

x̄ = (92+78+85+65+90)/5 = 82.0
ȳ = (88+75+81+70+85)/5 = 79.8

Σ(x-x̄)(y-ȳ) = (10)(8.2) + (-4)(-4.8) + (3)(1.2) + (-17)(-9.8) + (8)(5.2)
             = 82 + 19.2 + 3.6 + 166.6 + 41.6  = 313.0

Σ(x-x̄)²  = 100 + 16 + 9 + 289 + 64   = 478
Σ(y-ȳ)²  = 67.24 + 23.04 + 1.44 + 96.04 + 27.04 = 214.8

r = 313.0 / √(478 × 214.8) = 313.0 / √102,674.4 = 313.0 / 320.4 ≈ 0.977
```

That r ≈ 0.98 is deliberately close to a perfect relationship, since this toy example was built to show the formula clearly, not to resemble real flight-delay data. The site's actual measured correlations (0.119 to 0.585, in the table above) are much weaker and messier, which is exactly what a real 6,133-route dataset should look like &mdash; genuine, moderate signal, not a suspiciously clean fit.
6. **Keep only positive correlations** (a component that's unrelated or inversely related to future performance shouldn't get positive weight), then **normalize them to sum to 1.0** — each weight is simply that component's share of the total positive correlation.

The actual correlations we measured:

| Component | Correlation with future on-time rate |
|---|---|
| Reliability | +0.585 |
| Severe-delay exposure | +0.556 |
| Delay severity | +0.507 |
| Cancellation resilience | +0.253 |
| Diversion resilience | +0.119 |

Normalizing those five numbers to sum to 1.0 produces the weights used in Step 3 above.

**The normalization itself, worked out:**

```
Sum of correlations = 0.585 + 0.556 + 0.507 + 0.253 + 0.119 = 2.020

reliability_weight              = 0.585 / 2.020 = 0.2896  →  29.0%
severe_delay_exposure_weight    = 0.556 / 2.020 = 0.2752  →  27.5%
delay_severity_weight           = 0.507 / 2.020 = 0.2510  →  25.1%
cancellation_resilience_weight  = 0.253 / 2.020 = 0.1252  →  12.5%
diversion_resilience_weight     = 0.119 / 2.020 = 0.0589  →   5.9%

Check: 29.0% + 27.5% + 25.1% + 12.5% + 5.9% = 100.0%
```

Each weight really is exactly that component's share of the total correlation across all five &mdash; nothing hand-tuned after the fact. If a future re-calibration ever finds different correlations, this exact same division is what would produce new weights from them.

## A worked example

Suppose a route has, over some date range:

- On-time rate: 82%
- Average arrival delay: 9 minutes
- Severe-delay rate (over 60 min): 6%
- Cancellation rate: 2%
- Diversion rate: 0.5%

**Component scores:**

```
reliability            = 82
delay_severity          = 100 − (9 × 2)     = 82
severe_delay_exposure   = 100 − (6 × 5)     = 70
cancellation_resilience = 100 − (2 × 10)    = 80
diversion_resilience    = 100 − (0.5 × 20)  = 90
```

**Weighted sum:**

```
Health Score = (82 × 0.290) + (82 × 0.251) + (70 × 0.275) + (80 × 0.125) + (90 × 0.059)
             = 23.78 + 20.58 + 19.25 + 10.00 + 5.31
             = 78.92  →  rounds to 78.9
```

A score of 78.9 falls in the **Watch** band (70–79) — decent overall, on-time and delay numbers are solid, but the 6% severe-delay rate is dragging it down more than any other factor, since severe-delay exposure carries the second-highest weight.

## Honest limits of this approach

- The correlations we measured (0.12 to 0.59) are all real but **moderate** — none are close to a perfect predictor. Past performance tells you something, not everything.
- This is a **linear, transparent v2 formula**, not a machine-learning model. It doesn't account for interactions between factors (e.g., a route that's bad on both delay *and* cancellations isn't penalized any more than the simple sum would suggest).
- The calibration was done once, on the data available at the time. If BTS data patterns shift meaningfully over time, these weights could eventually warrant re-testing.
- A small-sample warning appears on the score itself when there isn't much data behind it, since percentages computed from a handful of flights are noisy.

---

# Decision Center methodology

The Decision Center is a collection of small, explainable tools. They answer
different questions, so they intentionally do not collapse everything into one
opaque “airline intelligence” score.

## How to read the tools

- **Descriptive tools** summarize what happened in the historical data.
- **Predictive tools** estimate what may happen next and must be checked against
  their test metrics.
- **Optimization tools** choose an action under explicit limits. They do not
  prove that the recommended action will cause a particular improvement.

Every result should be read with its data grain, sample size, and limitations.
The application uses real BTS records and transparent derived measures. A
historical proxy is labeled as a proxy; it is never presented as certified
airport capacity or as a causal intervention effect.

## Health Score Levers

This view uses the Health Score formula above. For one selected carrier, each
component is changed one at a time to the current network median:

```text
hypothetical score = current score
  - (current component × component weight)
  + (network median × component weight)
```

The difference is the **point gain**. This is a sensitivity calculation: it
answers “where is the arithmetic gap?” It does not answer “which fix is easiest?”
and it does not claim that a carrier can actually move a component to the
median.

The Network Opportunity Ranking repeats the same calculation for every carrier.
Point gain and flight volume remain separate because multiplying them would
create a priority number with no validated meaning.

## Turnaround Scenarios

This view is a 3 × 3 historical table. Flights are paired only when they use
the same aircraft tail on the same calendar day. Flights are ordered by their
scheduled departure time. The table groups the scheduled turnaround between
the two flights as:

- **Tight:** 25 minutes or less
- **Normal:** 26–45 minutes
- **Loose:** more than 45 minutes

The previous flight’s arrival delay is grouped as on time, 1–60 minutes late,
or more than 60 minutes late. Each cell reports the average departure delay of
the next flight and the number of observed pairs.

This is an association in observed operations, not a controlled experiment. A
carrier may assign short turnarounds to different kinds of flights than long
turnarounds, so the table should not be read as “changing the turnaround will
produce exactly this delay.”

## Network Opportunity Ranking

This is a network-wide sensitivity ranking, not a new model. For each carrier,
the largest positive one-component Health Score gap is retained. The display
also reports the carrier’s flight volume so the reader can compare:

```text
arithmetic opportunity  versus  operational reach
```

The application does not decide which side matters more. That decision belongs
to the analyst and depends on whether the goal is the cleanest measurable gap
or the broadest exposure.

## Predictive Risk Screen

The risk screen predicts whether the following month’s severe-delay rate will
be in the network’s worst quartile. It uses a regularized logistic model:

```text
p = 1 / (1 + exp(-(β₀ + β₁x₁ + ... + β₈x₈)))
```

The eight current-month features are severe-delay rate, cancellation rate,
average departure delay, late-aircraft delay share, ground-time share, logged
flight volume, recent severe-delay trend, and seasonal index.

The recent trend compares the current month with the entity’s prior three
calendar months. The seasonal index compares the same calendar month in prior
history with the entity’s own overall historical level. Both use only history
available before the feature month.

The panel is split chronologically into training, validation, and test data.
Features are standardized using the training set. A Platt calibrator is fit on
validation predictions so a displayed probability is more than a ranking. The
test set is kept separate and reports PR-AUC, Brier score, log loss, and
predicted-versus-observed calibration bins.

If PR-AUC is close to the test-set positive rate, the model found little useful
signal. A high or low label is therefore a screening signal, not a certainty.

The researcher view also shows a transparent math baseline beside the ML model.
It estimates the next risk probability from the entity's own earlier labelled
months using Laplace smoothing:

```text
math baseline = (earlier risky months + 1) / (earlier labelled months + 2)
```

When an entity has no earlier labelled months, the baseline uses the training
panel's overall risky-month rate. The Comparison tab evaluates this baseline and
the ML model on the same later test months. Lower Brier score and log loss mean
the probability was closer to what happened; higher PR-AUC means better ranking
of difficult months. This makes the choice between a simple rule and ML an
empirical question rather than an assumption that a more complex model is
automatically better.

## Departure Bank Smoothing

This is the most detailed optimizer in the Decision Center. A departure bank
is divided into 15-minute buckets. For every flight `i` and feasible bucket
`t`, the binary variable `x(i,t)` is 1 when that flight is assigned there.

The core rule is:

```text
sum over feasible t of x(i,t) = 1       for every flight i
```

Feasible buckets are limited by the selected ±15, ±30, or ±45 minute movement
window. An optional moved-flight cap limits disruption.

The optimizer minimizes three visible ideas:

```text
congestion exposure
+ historical delay proxy
+ schedule-shift penalty
```

Overload above the preferred bank limit uses three increasing cost tiers. This
means placing the same excess into one new peak is more expensive than spreading
it across several nearby buckets.

The expected mode uses the historical average delay of each bucket. The
risk-averse mode uses a standard CVaR construction to give extra weight to bad
historical scenarios. CVaR is useful when avoiding tail risk matters more than
the average, but it is not required for the basic interpretation.

The public application uses the open-source HiGHS solver through
`scipy.optimize.milp`. The optional Gurobi backend is an explicit research
adapter and is not silently selected or treated as validated.

The “capacity” limit is an empirical throughput proxy derived from the project’s
queue-pressure analysis and, by default, a seasonal historical baseline. BTS
does not provide certified gate, runway, or slot capacity in this dataset. The
optimizer also lacks crew legality, aircraft rotation, connection, curfew, and
gate constraints. Its result means “this historical bank can be mathematically
spread under these stated assumptions,” not “this is an executable airline
schedule.”

The optional **Check prior years** control replays the same experiment in
earlier equivalent calendar windows. For a past test window, its preferred bank
limit and delay proxy are built from still-earlier equivalent years only. This
is a stability check: it asks whether the MILP repeatedly creates a smaller
*simulated* 15-minute peak under the same constraints. It is not an observed
before/after intervention study and cannot estimate a causal delay reduction.

## Network Protection Portfolio

This is a small resource-allocation optimizer. Each candidate carrier or
airport has a binary selection variable `x(j)`:

```text
maximize  sum(metric(j) × x(j))
subject to sum(cost(j) × x(j)) <= budget
           x(j) is either 0 or 1
```

The user chooses exactly one primary metric, such as severe-delay exposure,
reliability, cancellation exposure, or flight volume. The optimizer does not
silently blend all metrics. It reports the other metrics afterward so the
trade-offs stay visible.

The available costs are resource proxies: equal attention, flight-volume
exposure, or square-root flight-volume exposure. They are not dollars unless
real intervention-cost data is supplied.

For selected candidates, marginal gain is calculated by removing one candidate
and solving again. This shows how much the optimized coverage would fall if
that candidate were unavailable. It is a sensitivity result, not an estimate
of the operational benefit of an intervention.

## Network Resilience Ranking

The network is represented as a directed graph:

- Airport = node
- Origin → destination route = edge
- Route volume = edge reference weight

Routes below the selected minimum-flight floor are excluded so one-off service
does not dominate the graph.

Two measures are kept separate:

1. **Degree / volume:** how many routes touch an airport and how many flights
   pass through it.
2. **Betweenness centrality:** the share of shortest paths between other
   airports that pass through the airport. Shortest path means fewest hops in
   the current unweighted directed graph.

Betweenness is a structural bridge proxy. It is not a simulation of closing an
airport, rerouting passengers, or calculating the resulting delay impact. The
current graph is also static over the full available history rather than a
month-by-month network evolution model.

## T-100 and On-time correlation

The T-100 enrichment is loaded separately from the flight-level OTP table. The
current warehouse contains:

| Dataset | Warehouse object | Grain | Current loaded history |
|---|---|---|---|
| T-100 Domestic Segment | `bts_t100_segment` and `bts_t100_segment_route_month` | carrier + route + month, with aircraft/service-class rows aggregated | January 2018–May 2026 |
| T-100 Domestic Market | `bts_t100_market` and `bts_t100_market_route_month` | carrier + market + month | January 2018–May 2026 |
| Carrier Decode | `bts_carrier_decode` | carrier code + effective dates | reference table |
| Master Coordinate | `bts_master_coordinate` | airport version + effective dates | reference table |
| Aircraft Types | `bts_aircraft_types` | aircraft type | reference table |

There are 101 raw and cleaned monthly files for each T-100 Segment and Market
dataset. The Segment route-month view calculates:

```text
load factor       = passengers / seats available
completion rate   = departures performed / departures scheduled
```

The **T-100 & On-time** Decision Center view uses a safe grain-matched process:

1. Aggregate the OTP flight table to carrier + origin + destination + month.
2. Calculate OTP flights, completed flights, on-time rate, and average arrival
   delay at that same grain.
3. Join that result to the T-100 Segment route-month view on carrier, route,
   year, and month.
4. Display the matched observations and Pearson correlations.

The correlation is calculated as:

```text
r = covariance(T-100 measure, on-time rate)
    / (standard deviation of T-100 measure × standard deviation of on-time rate)
```

The displayed measures include load factor, passengers, and seats. The value is
between −1 and +1: positive values move together, negative values move in
opposite directions, and values near zero show weak linear association.

This is exploratory evidence, not causation. Season, route mix, weather,
airport congestion, schedule design, and carrier decisions can affect both
traffic measures and OTP. The view requires a minimum OTP flight count so tiny
route-month samples do not look more precise than they are.

Most importantly, a monthly T-100 passenger or seat total is never copied onto
every flight row. That would multiply the aggregate and create false exposure.
The source and availability status remain available through
`/api/data-sources`; the matched comparison is served by
`/api/capacity/correlation`.

## Route delay forecast baseline

The route lookup includes a first, deliberately interpretable forecast. It is
not trying to predict the exact delay of one future flight. It answers a more
modest question: **when we look at comparable earlier flights, what outcome is
the most reasonable starting expectation for this route?**

The user can choose an origin, destination, airline, departure hour, and target
month. For a target month, the model applies a strict cutoff:

```text
training flights = flights with FlightDate before the first day of target month
```

This prevents the target month from quietly becoming part of its own forecast.
If no target month is supplied, the target defaults to the month after the
latest dated observation in the warehouse.

The comparison starts at the most specific level requested:

1. route + airline + departure hour
2. route + airline, or route + departure hour when only one filter was given
3. route

The model widens the level only when the more specific slice has fewer than 30
completed flights. The response reports the level actually used, the training
cutoff, the sample size, and the date range so a result is not presented with
false precision.

The visible outputs are simple summaries of the matched history:

```text
expected delay       = average ArrDelay over completed flights
late-arrival chance  = flights with ArrDel15 = 1 ÷ completed flights
cancellation chance  = cancelled flights ÷ scheduled flights
```

For uncertainty, the API also returns a 95% Wilson interval for the late and
cancellation rates. This is useful when comparing a large route history with a
small one: a percentage based on 30 flights should be read more cautiously than
the same percentage based on 3,000 flights.

The baseline is checked with an expanding time split. It predicts each later
month using only the months before it, records the error, and then adds that
month to the historical pool. The displayed delay error is mean absolute error:

```text
MAE = average of |predicted monthly delay − actual monthly delay|
```

When the T-100 Segment route-month table is available, the forecast adds one
small traffic feature without copying a monthly value onto individual flights.
It looks at the latest T-100 route-month before the target, calculates its load
factor, and labels it **lower load** (<70%), **typical load** (70–85%), or
**higher load** (85%+). It then finds earlier OTP months with the same band and
uses their weighted late rate and average delay. At least three earlier
traffic-matched months and 30 completed OTP flights are required; otherwise the
plain historical baseline remains the answer.

The researcher view reports both checks so we can ask the useful question:

```text
Did the T-100 traffic-band estimate reduce held-out error
relative to the plain historical baseline?
```

This is still a benchmark, not a weather or live-operations forecast. It does
not include aircraft rotations, airport congestion, or causal intervention
effects. A change from the historical baseline is an association to investigate,
not proof that fuller flights caused more delay.

## First route ML candidate

The researcher API also exposes `/api/route-ml-forecast`. This is deliberately
separate from the public route answer while it is being evaluated. It uses a
regularized ridge regression at the selected route-scenario + month grain to
produce three estimates:

```text
expected arrival-delay minutes
late-arrival rate
cancellation rate
```

The features are all available before the target month: the route's expanding
and recent historical rates, recent average delay, lagged T-100 load factor,
lagged passengers and seats, lagged T-100 completion rate, calendar seasonality,
and the amount of prior completed history. The feature builder enforces the
period boundary itself, so a future row cannot alter an earlier feature vector.

The model uses a chronological 60% / 20% / 20% train, validation, and test
split. It is refit on all pre-target examples only after the held-out check is
recorded. The response returns model coefficients, target features, validation
metrics, test metrics, and the equivalent historical-baseline test metrics.
That comparison is essential: if the ML candidate loses to the transparent
baseline, it remains a research result and is not promoted to the public view.

This first version is intentionally modest. It is a route-specific monthly
candidate, not a flight-level operational prediction. A later panel model or
tree-based model should be added only if it improves time-based test results
across several routes, not just one example. T-100 remains a predictive context
feature and an association to investigate, not evidence that passenger demand
causes delay.

## Shared route-panel candidate

The researcher Routes page can also run `/api/route-panel-forecast`. This model
learns from many route-month histories in the materialized `analytics_route_month`
table and then scores the selected route. Its panel features are prior route
late rate, prior delay, prior cancellation rate, recent movement, lagged T-100
load factor/passenger/seat context, lagged origin-airport operational context,
distance, and calendar seasonality. The operational context contains historical
WeatherDelay and NASDelay exposure, average departure delay, and how much of
the airport's scheduled month was concentrated in its busiest clock hour.
T-100 and operations are joined as-of each OTP month, so the model only sees
the latest record that was available before that month. It currently does not use the
selected airline or departure hour; the interface says so explicitly instead
of implying a more specific forecast than the data supports.

The panel is split by calendar period into training, validation, and test
examples. Its held-out MAE is compared with the same expanding historical
baseline. This gives us a fair progression: first test whether shared network
history and lagged T-100 context help, then compare a tree-based model only if
the simpler candidate justifies the extra complexity.

### T-100 ablation: testing whether the extra source earns its place

The panel model now runs one additional held-out experiment. It fits the same
ridge model twice on the same chronological train/test split:

```text
with T-100    = OTP history + lagged seats/passengers/load/completion + distance + season
OTP-only      = OTP history + distance + season
```

The T-100 version is useful only when it lowers the later-month error for an
outcome. This is an ablation, not a causal experiment: it tells us whether the
traffic variables add predictive information in this dataset and time window;
it does not prove that fuller flights cause delays. The Routes Comparison tab
shows this result beside the ordinary Math-versus-ML comparison so the extra
dataset remains auditable.

## Repeated temporal validation

The **Model evidence** page does not choose a single favorable train/test
split. It creates several rolling checks. For each check, it trains only on
route-month examples before a cutoff, then measures error on the following
months. The next cutoff moves forward and repeats the same rule.

```text
earlier history  → fit model → later untouched months → record error
move cutoff      → fit again  → next untouched months  → record error
```

Three nested candidates are compared whenever the matching source history is
available:

```text
historical baseline        = the route's earlier OTP history
OTP-only ML                = OTP history + distance + seasonality
OTP + lagged T-100         = OTP-only ML + prior seats/passengers/load/completion
OTP + T-100 + operations   = above + prior WeatherDelay/NASDelay/airport concentration
```

The page shows every time window, the average MAE across them, coverage for
each added source, and how often a method has the lowest error. It does not
hide a window that makes a richer model look worse. Lower MAE supports
predictive usefulness; it does not show that traffic, weather, NAS, or
concentration caused a later delay or cancellation.

For an interactive local run, the repeated check uses a disclosed deterministic
sample of 200 route identifiers from the available network. The sample is not
chosen using delay, cancellation, or model outcome values. This keeps a laptop
run responsive while preserving multiple routes and multiple future windows;
the page states both the sampled and available network route counts.

The operational fields are delayed by at least one calendar month. They are
observed BTS delay coding, not a live weather feed, an air-traffic-control
forecast, or a certified airport capacity estimate.

## Supporting queue-pressure model

Queue pressure is currently an API capability and supporting input to the
departure-bank optimizer. It groups departures into hourly banks and estimates
historical effective capacity as the 90th percentile of completed departures
for that airport and hour.

The visible pressure score combines four normalized signals:

```text
45% utilization + 25% delay accumulation
+ 20% departure delay + 10% taxi-out time
```

The additional M/G/c estimate uses taxi-out as the service-time proxy:

```text
utilization ρ = arrival rate λ / (servers c × service rate μ)
```

Erlang-C estimates the chance of waiting, and the Allen–Cunneen adjustment
accounts for variation in taxi-out times. The number of parallel “servers” is
inferred from historical throughput, not claimed to be the number of runways
or gates. If utilization is at least 1, the model reports an unstable queue
instead of inventing a finite steady-state wait.

## Supporting Markov delay propagation

The Markov endpoint models four arrival-delay states: on time, minor,
moderate, and severe. For each turnaround bucket, it estimates:

```text
P(from state → next state)
```

from consecutive same-tail, same-day flights. A multi-leg forecast uses matrix
powers:

```text
future state distribution = current distribution × P^k
```

This is an empirical propagation pattern, not proof that one delay caused the
next. The convenience forecast assumes the same turnaround bucket on every
leg; real rotations can mix buckets. The endpoint is available in the backend
but is intentionally kept out of the main Decision Center until it has a
simple visual explanation.

## What is deliberately not modeled

The current Decision Center does not claim to solve the full airline planning
problem. It does not have certified airport capacity, gate assignments, crew
rules, aircraft rotations, passenger itineraries, ticket revenue, or airline
intervention costs. Those would be required before building a full scheduling,
fleet, crew, or revenue optimizer.

The current design is intentionally a small stack of transparent arithmetic,
descriptive statistics, one interpretable predictive model, graph measures, and
bounded optimizers. That gives useful data intelligence without hiding the
assumptions inside unnecessary mathematical complexity.
