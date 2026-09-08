# Real-data sources and pipeline

The app's core `flights` table is the BTS Marketing Carrier On-Time
Performance dataset. The enrichment pipeline adds only official BTS sources
and keeps each source at its native grain.

## Sources

| Dataset | Native grain | What it adds | Storage |
|---|---|---|---|
| Marketing Carrier On-Time Performance | one reported flight | scheduled/actual times, delays, cancellations, diversions, distance, and delay causes | `Data/Raw/` → `flights` |
| T-100 Domestic Segment | carrier + origin + destination + aircraft type + service class + month | scheduled/performed departures, seats, passengers, distance, aircraft, service class | `Data/Raw/bts/t100_segment/` → `bts_t100_segment` |
| T-100 Domestic Market | carrier + origin + destination + service class + month | market-level passengers, freight, and mail | `Data/Raw/bts/t100_market/` → `bts_t100_market` |
| Carrier Decode | carrier code + effective date range | time-aware carrier identity and code history | `Data/Raw/bts/support/` → `bts_carrier_decode` |
| Master Coordinate | airport attribute version + effective date range | stable airport IDs, names, coordinates, geography, and code history | `Data/Raw/bts/support/` → `bts_master_coordinate` |
| AircraftTypes | aircraft type | aircraft type/model/manufacturer descriptions | `Data/Raw/bts/support/` → `bts_aircraft_types` |

The T-100 route-month views are derived aggregates, not new observations:

- `bts_t100_segment_route_month` aggregates aircraft/service-class rows and
  calculates `load_factor = passengers / seats_available` and
  `completion_rate = departures_performed / departures_scheduled`.
- `bts_t100_market_route_month` aggregates market rows by carrier, route, and
  month.

These views are intentionally not joined one-to-many onto `flights`. A
monthly T-100 passenger or seat value must not be copied onto every flight in
that month.

The Researcher view's Decision Center now exposes a **T-100 & On-time**
comparison. It first aggregates the flight-level OTP data to the same
carrier/route/month grain, then joins it to
`bts_t100_segment_route_month`. The comparison shows the matched observations
and Pearson correlations between load factor, passengers, seats, and on-time
rate through `/api/capacity/correlation`. The result is exploratory association,
not a causal claim.

## Reproducible commands

From the repository root:

```powershell
# Monthly capacity data; start with one year to verify the workflow.
python -m pipeline.download_bts t100_segment --years 2025
python -m pipeline.clean_bts t100_segment

# Optional demand and identity enrichment.
python -m pipeline.download_bts t100_market --years 2025
python -m pipeline.clean_bts t100_market
python -m pipeline.download_bts carrier_decode
python -m pipeline.clean_bts carrier_decode
python -m pipeline.download_bts master_coordinate
python -m pipeline.clean_bts master_coordinate
python -m pipeline.download_bts aircraft_types
python -m pipeline.clean_bts aircraft_types

# Load whatever has been cleaned into the existing warehouse atomically.
python -m pipeline.load_bts
python -m pipeline.validate
```

To backfill several years, pass a range such as `--years 2018-2026`. The
downloader skips already validated canonical ZIPs. Every clean file records
its source URL, SHA-256 hash, columns, row count, and processing time in
`Data/bts_manifest.json`.

`python -m pipeline.build_warehouse` also includes any available cleaned BTS
tables in the staged warehouse build. If the flight warehouse is rebuilt
before enrichment is cleaned, simply rerun `python -m pipeline.load_bts`.

## What is deliberately not claimed

BTS data does not provide the airline's live gate occupancy, crew legality,
aircraft rotation assignment, airport slot allocation, or internal operating
costs. The decision tools must continue to label those as unmodeled or proxy
inputs until a real source is supplied. T-100 seats and passengers are traffic
and capacity statistics, not certified real-time operational capacity.

## Official references

- [BTS Airline On-Time Performance](https://www.transtats.bts.gov/tables.asp?QO_VQ=EFD+&QO_anzr=Nv4yv0r)
- [BTS T-100 Domestic Segment](https://www.bts.gov/browse-statistical-products-and-data/bts-publications/data-bank-28ds-t-100-domestic-segment-data-us)
- [TranStats T-100 Segment table profile](https://www.transtats.bts.gov/TableInfo.asp?QO_fu146_anzr=Nv4+Pn44vr45&gnoyr_VQ=FIM)
- [TranStats T-100 Market table profile](https://www.transtats.bts.gov/TableInfo.asp?QO_fu146_anzr=Nv4+Pn44vr45&gnoyr_VQ=FIL)
- [TranStats Aviation Support Tables](https://www.transtats.bts.gov/Tables.asp?QO_VQ=IMI)
- [BTS release information](https://www.transtats.bts.gov/releaseinfo.asp)
