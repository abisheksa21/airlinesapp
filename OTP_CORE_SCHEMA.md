# OTP core analytical schema

The warehouse keeps the complete cleaned BTS flight table in flights. The
compact table analytics_flight_core is a deliberate projection used by
repeated dashboard aggregations and the first route-delay forecasting work.

This is a storage and feature contract, not a new source of data:

~~~text
raw BTS monthly files → flights → analytics_flight_core → dashboard aggregates and models
~~~

The raw table is not deleted or changed. If a future analysis needs a field
that is not in the core layer, it must either add that field deliberately to
pipeline/otp_core.py or query the raw table for that specialist analysis.

## Included fields

| Group | Fields | Why they are retained |
|---|---|---|
| Time | FlightDate, Year, Quarter, Month, DayofMonth, DayOfWeek | Temporal splits, seasonality, trend, and date coverage |
| Identity | Marketing_Airline_Network, Operating_Airline, Tail_Number | Carrier comparisons, codeshare context, and aircraft sequencing |
| Route | Origin, Dest, Distance | Directional route definition and route-level context |
| Schedule | CRSDepTime, DepTime, CRSArrTime, ArrTime, CRSElapsedTime | Departure-hour analysis and schedule/actual comparison |
| Outcome | Cancelled, CancellationCode, Diverted, DepDelay, DepDel15, ArrDelay, ArrDel15 | On-time, delay, cancellation, and diversion outcomes |
| Flight operation | ActualElapsedTime, AirTime, TaxiIn, TaxiOut, WheelsOff, WheelsOn | Ground-time and operational-process analysis |
| Delay causes | CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay | Explanatory delay breakdowns |
| Turnbacks/diversions | FirstDepTime, TotalAddGTime, LongestAddGTime, DivAirportLandings, DivReachedDest, DivActualElapsedTime, DivArrDelay, DivDistance | Existing turnback, diversion, and propagation analyses |

## Rules

- One row in analytics_flight_core represents one cleaned OTP flight record.
- It is rebuilt from the raw flights table; it is not an independent dataset.
- Aggregates must be built at their stated grain before joining T-100.
- Forecast features must be computed using information available before the
  prediction period.
- A missing field or missing period must be reported, not replaced with a
  fabricated value.
