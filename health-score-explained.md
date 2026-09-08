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
