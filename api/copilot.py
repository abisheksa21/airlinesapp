"""
Copilot: Claude (Anthropic Messages API) with native tool use over a fixed
set of grounded, warehouse-backed tools. Claude decides which tool to call
and with what arguments; every tool only returns real DuckDB query results,
so the model can narrate but never invent numbers.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from api.db import open_readonly_connection
from api.health_score import compute_health_score

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL_PUBLIC = os.getenv("CLAUDE_MODEL_PUBLIC", "claude-haiku-4-5")
CLAUDE_MODEL_RESEARCHER = os.getenv("CLAUDE_MODEL_RESEARCHER", "claude-sonnet-5")


def _model_for_tier(tier: str | None) -> str:
    return CLAUDE_MODEL_RESEARCHER if tier == "researcher" else CLAUDE_MODEL_PUBLIC
CLAUDE_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT_SECONDS", "60"))
# 2048 was too tight for claude-sonnet-5's extended thinking, which counts
# against max_tokens -- confirmed directly: a real multi-hop question spent
# its ENTIRE 2048-token budget on an internal thinking block and hit
# stop_reason=max_tokens before producing any visible text or tool_use,
# silently producing an empty answer no error path caught. 8192 gives real
# headroom for thinking + a substantive answer; verified end-to-end against
# a genuinely hard synthesis question. Timeout raised alongside it (35s was
# too tight once thinking made individual calls legitimately take longer).
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "8192"))
# Heuristic floor for a forced-final answer (see ask_copilot/stream_copilot):
# confirmed the model can produce genuine but useless text here, e.g. "Let
# me use the correct dimension names instead" -- leftover self-correction
# narration from a tool-call fix, not a synthesized answer -- which passes
# a bare "is text non-empty" check. A real answer to a real question is
# essentially never this short; treat anything under this as suspect and
# worth the nudge retry, same as empty text.
MIN_PLAUSIBLE_ANSWER_LENGTH = 120
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"

SYSTEM_INSTRUCTION = """You are a data assistant for a public airline on-time performance site,
backed by real US DOT/BTS data (Jan 2018 - present, ~60M flights, 11 carriers).

Rules:
- You MUST call one of the provided tools to get real numbers before answering any factual
  question about flights, delays, carriers, routes, or airports. Never state a statistic you
  did not get from a tool result.
- If a tool result does not support the premise of the user's question, say so plainly rather
  than agreeing with a false premise.
- "On-time" means arrival delay under 15 minutes, per DOT's own standard. Cancelled flights are
  excluded from delay/on-time math.
- Delay causes are BTS's own coded categories (largest contributing category), not root causes.
- Keep answers concise and concrete: lead with the number, then brief context.
- If a question is unrelated to airline on-time performance, say you can only help with that.

Epistemic discipline (write it this way from the start -- don't rely on being corrected):
- Don't claim causation a tool result doesn't demonstrate. Avoid "root cause," "primary driver,"
  "proves," "bottleneck," "caused by" unless the evidence is genuinely causal (e.g. a documented
  event like the 737 MAX grounding). Prefer "associated with," "the largest recorded category,"
  "correlates with," "is consistent with."
- If a finding runs counter to what someone would naively expect, say so directly instead of
  smoothing it over. For example: delay propagation is weakest on the TIGHTEST scheduled
  turnarounds and strongest on normal ones -- the opposite of the intuitive prediction that less
  buffer means more propagation. State surprising results plainly; that's more useful than a tidy
  answer that quietly avoids the surprise.
- A correlation or an average is not proof of a mechanism. When get_delay_propagation returns a
  correlation, describe it as an association, not as delay "spreading" or "transferring."
- When flexible_query is used, always state the exact filters that were actually applied (from
  its applied_filters field) in plain language -- e.g. "Fridays, 8pm-5am departures, Southwest,
  out of Midway" -- so the scope is unambiguous and someone could reproduce it. Prefer the other,
  more specific tools when they directly answer the question; use flexible_query for genuinely
  compound filter combinations none of them cover.
- Same discipline for every other tool, not just flexible_query: always state which carrier,
  airport, route, or date range a number came from -- never report a bare percentage with no
  scope attached. If a tool ran with no filters (full history, all carriers), say that plainly
  too, since "no scope stated" reads as more precise than it is.
- Before saying one thing is "better," "worse," "more reliable," or otherwise declaring a
  comparative winner between two rates (two carriers' on-time rates, a carrier under two
  different filters, etc.), call check_significance on the two numbers first. If the difference
  isn't significant at the 95% level, say so explicitly -- e.g. "these aren't meaningfully
  different given the sample sizes" -- rather than picking a winner from noise. This applies
  whenever the comparison itself is the point of the question, not for purely descriptive
  reporting of a single number.

Voice: don't default to the same bulleted-list-of-every-number shape for every answer. A tool
result usually has one or two numbers that actually matter for what was asked -- lead with those
in a sentence or two, like you're telling a colleague the headline, not filing every field from
the tool result into a list. Save a list for when there are genuinely several comparable items
(e.g. three haul-length buckets, two carriers). Vary sentence structure and length response to
response rather than settling into one template.
"""

# ---- Tool schemas (Claude Messages API input_schema format) ----

TOOLS = [{'name': 'get_summary',
  'description': 'Overall flight-count, on-time rate, avg arrival delay, and cancellation rate, '
                 'optionally filtered by carrier and/or date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code, e.g. WN, DL, AA. '
                                                             'Omit for all carriers.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_trend',
  'description': 'Monthly on-time rate over time, optionally filtered by carrier and/or date '
                 'range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'compare_carriers',
  'description': 'On-time rate, avg arrival delay, and cancellation rate for every carrier, '
                 "ranked. Use this for any 'which airline is best/worst' or head-to-head question.",
  'input_schema': {'type': 'object',
                   'properties': {'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_delay_causes',
  'description': "Breakdown of BTS's coded delay-cause categories (Carrier, Weather, NAS, "
                 'Security, Late Aircraft) by share of total delay-minutes, optionally filtered by '
                 'carrier, airport, and/or date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination). Omit for all '
                                                             'airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_cancellation_causes',
  'description': "Breakdown of WHY flights were cancelled (BTS's CancellationCode: Carrier, "
                 'Weather, National Air System, Security), as a share of cancelled flights. '
                 'Distinct from delay causes, which only covers flights that ran late, not ones '
                 'that never ran. Optionally filtered by carrier, airport, and/or date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination). Omit for all '
                                                             'airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_distance_buckets',
  'description': 'On-time rate, avg arrival delay, and cancellation rate broken out by haul '
                 'length: short-haul (<500mi), medium-haul (500-1500mi), long-haul (>1500mi). Use '
                 "this for any 'does flight distance affect delays/on-time performance' question. "
                 'Optionally filtered by carrier, airport, and/or date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination). Omit for all '
                                                             'airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_time_of_day',
  'description': 'On-time rate and avg arrival delay by scheduled departure hour (0-23), for '
                 "questions like 'what time of day should I fly' or 'is it better to fly early "
                 "morning or evening'. Airport filter matches DEPARTURES from that airport only, "
                 'not arrivals. Optionally filtered by carrier, airport, and/or date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code of DEPARTURE (not '
                                                             'arrival). Omit for all airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_codeshare',
  'description': 'Self-operated vs codeshare-operated flight split for a marketing carrier -- a '
                 "codeshare-operated flight is sold under one carrier's code but actually flown by "
                 'a regional partner (e.g. a Delta-coded flight operated by Endeavor Air). Use '
                 "this for 'does this carrier codeshare' or 'who actually flies X's flights' "
                 'questions. Optionally filtered by carrier, airport, and/or date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination). Omit for all '
                                                             'airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_delay_propagation',
  'description': "Whether a late-arriving aircraft's delay carries over to its NEXT flight (same "
                 "tail, same day) -- for 'does delay carry over between flights' or 'if my inbound "
                 "plane is late, will my flight be late too' questions. Returns a correlation and "
                 'average departure delay conditioned on how late the predecessor flight arrived. '
                 'Optionally filtered by marketing carrier only (no airport/date filter '
                 'available).',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'}}}},
 {'name': 'get_health_score',
  'description': "The site's calibrated 0-100 health score (Excellent/Strong/Watch/Weak/Critical) "
                 'for exactly one of: a carrier, an airport, a route (origin+dest), or an aircraft '
                 'tail number. Exactly one of carrier/airport/(origin+dest)/tail must be given. '
                 "Use this for 'how reliable is X' or 'what's the health score for X' questions.",
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': "IATA carrier code, for a carrier's "
                                                             'health score.'},
                                  'airport': {'type': 'string',
                                              'description': "IATA airport code, for an airport's "
                                                             'health score (matches either origin '
                                                             'or destination).'},
                                  'origin': {'type': 'string',
                                             'description': 'Origin IATA airport code, for a '
                                                            "route's health score. Must be given "
                                                            'together with dest.'},
                                  'dest': {'type': 'string',
                                           'description': 'Destination IATA airport code, for a '
                                                          "route's health score. Must be given "
                                                          'together with origin.'},
                                  'tail': {'type': 'string',
                                           'description': 'Tail number (e.g. N123SW), for one '
                                                          "aircraft's health score."},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_turnbacks',
  'description': 'Gate-return / turnback flights -- flights that pushed back from the gate then '
                 'returned before actually departing. Returns turnback rate, extra ground time '
                 'cost, and on-time rate for turnback vs normal flights. Airport filter matches '
                 'DEPARTURES only, not arrivals. Optionally filtered by carrier, airport, and/or '
                 'date range.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code of DEPARTURE (not '
                                                             'arrival). Omit for all airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_diversions',
  'description': 'Diversion deep-dive: how many flights were diverted, how many intermediate '
                 'airports diverted flights landed at before stopping, and whether they eventually '
                 'reached their original destination. Also returns the actual airports diverted '
                 'flights landed at (top_diversion_airports) and the real cost of a diversion '
                 '(average_diversion_cost: arrival delay, distance difference, time difference, '
                 'all computed from the actual diversion record, not estimated). '
                 'avg_extra_distance_miles is usually NEGATIVE -- a diversion typically means '
                 'landing at an unplanned airport partway through the route rather than completing '
                 'or exceeding it, so distance flown is usually shorter than scheduled even though '
                 'time is usually longer. State that plainly rather than treating a negative value '
                 'as an error. Accepts either a generic carrier/airport filter or an exact '
                 'origin+dest route filter. Optionally filtered by date range too.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination). Omit for all '
                                                             'airports.'},
                                  'origin': {'type': 'string',
                                             'description': 'Origin IATA airport code, for a '
                                                            'specific route. Give together with '
                                                            'dest.'},
                                  'dest': {'type': 'string',
                                           'description': 'Destination IATA airport code, for a '
                                                          'specific route. Give together with '
                                                          'origin.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'get_schedule_padding',
  'description': 'Yearly trend of scheduled vs actual flight time -- whether a carrier is padding '
                 'its schedule (inflating scheduled elapsed time) to make its on-time stats look '
                 "better without flights actually getting faster. Use this for 'does X pad its "
                 "schedule' questions. Optionally filtered by carrier, airport, and/or date range.",
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code. Omit for all '
                                                             'carriers.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination). Omit for all '
                                                             'airports.'},
                                  'start_date': {'type': 'string',
                                                 'description': 'YYYY-MM-DD. Omit for full '
                                                                'history.'},
                                  'end_date': {'type': 'string',
                                               'description': 'YYYY-MM-DD. Omit for full '
                                                              'history.'}}}},
 {'name': 'flexible_query',
  'description': "General-purpose query for compound or novel questions that don't fit the other "
                 "tools -- e.g. 'on-time rate for Southwest red-eye flights out of Midway on "
                 "Fridays in Q4' or 'cancellation rate by day of week for United out of ORD in "
                 "2023'. Combine any of: carrier, airport, origin/dest, date range, day(s) of "
                 'week, time-of-day bucket, distance bucket, tail number. Optionally group results '
                 'by one dimension to get a breakdown instead of a single aggregate. PREFER the '
                 "other specific tools when they directly answer the question (they're more "
                 'established) -- use this specifically when the question combines filters or '
                 'dimensions no single other tool covers.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string',
                                              'description': 'IATA carrier code.'},
                                  'airport': {'type': 'string',
                                              'description': 'IATA airport code (matches either '
                                                             'origin or destination).'},
                                  'origin': {'type': 'string',
                                             'description': 'Origin IATA airport code.'},
                                  'dest': {'type': 'string',
                                           'description': 'Destination IATA airport code.'},
                                  'start_date': {'type': 'string', 'description': 'YYYY-MM-DD.'},
                                  'end_date': {'type': 'string', 'description': 'YYYY-MM-DD.'},
                                  'days_of_week': {'type': 'array',
                                                   'items': {'type': 'string',
                                                             'enum': ['Mon',
                                                                      'Tue',
                                                                      'Wed',
                                                                      'Thu',
                                                                      'Fri',
                                                                      'Sat',
                                                                      'Sun']},
                                                   'description': 'One or more days of week to '
                                                                  'restrict to. Omit for all '
                                                                  'days.'},
                                  'time_of_day': {'type': 'string',
                                                  'enum': ['early_morning',
                                                           'morning',
                                                           'afternoon',
                                                           'evening',
                                                           'red_eye'],
                                                  'description': 'Scheduled departure window: '
                                                                 'early_morning 5-8am, morning '
                                                                 '8-11am, afternoon 11am-3pm, '
                                                                 'evening 3-8pm, red_eye 8pm-5am.'},
                                  'distance_bucket': {'type': 'string',
                                                      'enum': ['short_haul',
                                                               'medium_haul',
                                                               'long_haul'],
                                                      'description': 'short_haul <500mi, '
                                                                     'medium_haul 500-1500mi, '
                                                                     'long_haul >1500mi.'},
                                  'tail': {'type': 'string',
                                           'description': 'Tail number, e.g. N123SW.'},
                                  'group_by': {'type': 'string',
                                               'enum': ['carrier',
                                                        'origin',
                                                        'dest',
                                                        'year',
                                                        'month',
                                                        'day_of_week',
                                                        'hour',
                                                        'distance_bucket'],
                                               'description': 'Optional -- return a breakdown by '
                                                              'this dimension (e.g. '
                                                              'group_by=carrier to compare all '
                                                              'carriers under the same filters) '
                                                              'instead of one aggregate number.'},
                                  'limit': {'type': 'integer',
                                            'description': 'Max groups to return when group_by is '
                                                           'used. Default 20.'}}}},
 {'name': 'check_significance',
  'description': 'Two-proportion statistical significance test (z-test). Call this whenever '
                 "comparing two rates/percentages (e.g. two carriers' on-time rates, or the same "
                 "carrier under two different filters) before stating one is 'better' or 'worse' "
                 "than the other -- a numeric gap isn't meaningful unless it's large relative to "
                 'the sample sizes involved. Takes the two rates as decimals (0-1, not 0-100) and '
                 'their sample sizes (the total_flights or similar count each rate was computed '
                 'from).',
  'input_schema': {'type': 'object',
                   'properties': {'rate_a': {'type': 'number',
                                             'description': 'First rate as a decimal, e.g. 0.782 '
                                                            'for 78.2%.'},
                                  'n_a': {'type': 'integer',
                                          'description': 'Sample size (flight count) the first '
                                                         'rate was computed from.'},
                                  'rate_b': {'type': 'number',
                                             'description': 'Second rate as a decimal.'},
                                  'n_b': {'type': 'integer',
                                          'description': 'Sample size the second rate was computed '
                                                         'from.'},
                                  'label_a': {'type': 'string',
                                              'description': 'Short label for the first group, '
                                                             "e.g. 'Southwest'."},
                                  'label_b': {'type': 'string',
                                              'description': 'Short label for the second group, '
                                                             "e.g. 'American'."}},
                   'required': ['rate_a', 'n_a', 'rate_b', 'n_b']}},
 {'name': 'get_carrier_profile',
  'description': 'Consolidated carrier profile in one call: overall stats, health score, delay-cause '
                 'mix, and top routes. Use this for open-ended "tell me about X airline" questions '
                 'instead of chaining get_summary/get_delay_causes/get_health_score separately.',
  'input_schema': {'type': 'object',
                   'properties': {'carrier': {'type': 'string', 'description': 'IATA carrier code.'},
                                  'start_date': {'type': 'string', 'description': 'YYYY-MM-DD. Omit for full history.'},
                                  'end_date': {'type': 'string', 'description': 'YYYY-MM-DD. Omit for full history.'}},
                   'required': ['carrier']}},
 {'name': 'get_airport_profile',
  'description': 'Consolidated airport profile in one call: overall stats (departures + arrivals '
                 'combined), health score, delay-cause mix, and top routes through it. Use this for '
                 'open-ended "tell me about X airport" questions instead of chaining several tools.',
  'input_schema': {'type': 'object',
                   'properties': {'airport': {'type': 'string', 'description': 'IATA airport code.'},
                                  'start_date': {'type': 'string', 'description': 'YYYY-MM-DD. Omit for full history.'},
                                  'end_date': {'type': 'string', 'description': 'YYYY-MM-DD. Omit for full history.'}},
                   'required': ['airport']}}]


# ---- Tool implementations (real DuckDB queries) ----


def get_summary(carrier: str | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
    clauses = ["1=1"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        row = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                MIN(FlightDate) AS start_date,
                MAX(FlightDate) AS end_date,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate,
                COUNT(DISTINCT Origin || '-' || Dest) AS unique_routes,
                COUNT(DISTINCT Marketing_Airline_Network) AS carrier_count
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

        if row is None or row[0] == 0:
            return {"error": "No flights matched that filter."}

        # Unique airports touched, counting an airport once whether it shows
        # up as an origin, a destination, or both. Do the two DISTINCT
        # reductions separately: a UNION over both full table projections
        # can materialize a very large intermediate relation on the complete
        # warehouse before reducing it to the few hundred airport codes.
        origin_airports = {
            r[0]
            for r in connection.execute(
                f"SELECT DISTINCT Origin FROM flights WHERE {where} AND Origin IS NOT NULL",
                params,
            ).fetchall()
        }
        destination_airports = {
            r[0]
            for r in connection.execute(
                f"SELECT DISTINCT Dest FROM flights WHERE {where} AND Dest IS NOT NULL",
                params,
            ).fetchall()
        }
        unique_airports = len(origin_airports | destination_airports)

    return {
        "total_flights": row[0],
        "start_date": str(row[1]),
        "end_date": str(row[2]),
        "on_time_rate": row[3],
        "avg_arrival_delay_minutes": row[4],
        "cancellation_rate": row[5],
        "unique_routes": row[6],
        "unique_airports": unique_airports,
        "carrier_count": row[7],
    }


def get_trend(carrier: str | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
    clauses = ["1=1"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                strftime(FlightDate, '%Y-%m') AS year_month,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights
            WHERE {where}
            GROUP BY year_month
            ORDER BY year_month
            """,
            params,
        ).fetchall()

    if not rows:
        return {"error": "No flights matched that filter."}

    return {"months": [{"month": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in rows]}


def compare_carriers(start_date: str | None = None, end_date: str | None = None) -> dict:
    clauses = ["Marketing_Airline_Network IS NOT NULL"]
    params: list[Any] = []
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                Marketing_Airline_Network AS carrier,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {where}
            GROUP BY carrier
            ORDER BY on_time_rate DESC
            """,
            params,
        ).fetchall()

    return {
        "carriers": [
            {
                "carrier": r[0],
                "total_flights": r[1],
                "on_time_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
                "cancellation_rate": r[4],
            }
            for r in rows
        ]
    }


def get_delay_causes(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["Cancelled = 0"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        row = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                SUM(CASE WHEN ArrDel15 = 1 THEN 1 ELSE 0 END) AS delayed_flights,
                SUM(CarrierDelay) AS carrier_delay,
                SUM(WeatherDelay) AS weather,
                SUM(NASDelay) AS nas,
                SUM(SecurityDelay) AS security,
                SUM(LateAircraftDelay) AS late_aircraft
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

    if row is None or row[0] == 0:
        return {"error": "No flights matched that filter."}

    causes = {
        "Carrier": row[2] or 0,
        "Weather": row[3] or 0,
        "NAS": row[4] or 0,
        "Security": row[5] or 0,
        "Late Aircraft": row[6] or 0,
    }
    total = sum(causes.values()) or 1
    return {
        "total_flights": row[0],
        "delayed_flights": row[1] or 0,
        "causes": [{"cause": k, "minutes": v, "share": v / total} for k, v in causes.items()],
    }


def get_cancellation_causes(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["Cancelled = 1"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    base_where = " AND ".join(clauses)
    coded_where = base_where + " AND CancellationCode IS NOT NULL"

    with open_readonly_connection() as connection:
        total_cancelled = connection.execute(
            f"SELECT COUNT(*) FROM flights WHERE {base_where}", params
        ).fetchone()[0]

        if total_cancelled == 0:
            return {"error": "No cancelled flights matched that filter."}

        rows = connection.execute(
            f"""
            SELECT CancellationCode, COUNT(*) AS cancelled_flights
            FROM flights
            WHERE {coded_where}
            GROUP BY CancellationCode
            """,
            params,
        ).fetchall()

    code_labels = {"A": "Carrier", "B": "Weather", "C": "National Air System", "D": "Security"}
    causes = {label: 0 for label in code_labels.values()}
    coded_total = 0
    for code, count in rows:
        label = code_labels.get(code)
        if label:
            causes[label] = count
            coded_total += count

    return {
        "total_cancelled_flights": total_cancelled,
        "coded_cancelled_flights": coded_total,
        "causes": [
            {"cause": label, "cancelled_flights": count, "share": (count / coded_total if coded_total else 0)}
            for label, count in causes.items()
        ],
    }


def get_distance_buckets(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["Distance IS NOT NULL"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CASE
                    WHEN Distance < 500 THEN 'Short-haul'
                    WHEN Distance < 1500 THEN 'Medium-haul'
                    ELSE 'Long-haul'
                END AS bucket,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate,
                AVG(Distance) AS avg_distance_miles
            FROM flights
            WHERE {where}
            GROUP BY bucket
            """,
            params,
        ).fetchall()

    if not rows:
        return {"error": "No flights matched that filter."}

    bucket_order = {"Short-haul": 0, "Medium-haul": 1, "Long-haul": 2}
    buckets = sorted(
        (
            {
                "bucket": r[0],
                "total_flights": r[1],
                "on_time_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
                "cancellation_rate": r[4],
                "avg_distance_miles": r[5],
            }
            for r in rows
        ),
        key=lambda b: bucket_order[b["bucket"]],
    )
    return {"buckets": buckets}


def get_time_of_day(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["CRSDepTime IS NOT NULL"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("Origin = ?")
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CAST(FLOOR(CAST(CRSDepTime AS INTEGER) / 100) AS INTEGER) AS scheduled_hour,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes
            FROM flights
            WHERE {where}
            GROUP BY scheduled_hour
            HAVING scheduled_hour BETWEEN 0 AND 23
            ORDER BY scheduled_hour
            """,
            params,
        ).fetchall()

    if not rows:
        return {"error": "No flights matched that filter."}

    return {
        "hours": [
            {"scheduled_hour": r[0], "total_flights": r[1], "on_time_rate": r[2], "avg_arrival_delay_minutes": r[3]}
            for r in rows
        ]
    }


def get_codeshare(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["Operating_Airline IS NOT NULL", "Operating_Airline != ''"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CASE WHEN Operating_Airline = Marketing_Airline_Network
                     THEN 'Self-operated' ELSE 'Codeshare-operated' END AS group_label,
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {where}
            GROUP BY group_label
            """,
            params,
        ).fetchall()

        if not rows:
            return {"error": "No flights matched that filter."}

        total_flights = sum(r[1] for r in rows)

    group_order = {"Self-operated": 0, "Codeshare-operated": 1}
    groups = sorted(
        (
            {
                "group": r[0],
                "total_flights": r[1],
                "on_time_rate": r[2],
                "avg_arrival_delay_minutes": r[3],
                "cancellation_rate": r[4],
                "share": (r[1] / total_flights if total_flights else 0),
            }
            for r in rows
        ),
        key=lambda g: group_order.get(g["group"], 2),
    )
    return {"total_flights": total_flights, "groups": groups}


def get_delay_propagation(carrier: str | None = None) -> dict:
    # 25/45-minute thresholds mirror main.py's TIGHT_TURNAROUND_MINUTES /
    # TARGET_TURNAROUND_MINUTES constants -- duplicated here as literals
    # rather than imported, same reasoning as main.py's own comment on this.
    clauses = ["Cancelled = 0", "Diverted = 0", "Tail_Number IS NOT NULL", "Tail_Number != ''"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        row = connection.execute(
            f"""
            WITH scoped AS (
                SELECT
                    Tail_Number, FlightDate,
                    TRY_CAST(CRSDepTime AS INTEGER) AS crs_dep_hhmm,
                    TRY_CAST(CRSArrTime AS INTEGER) AS crs_arr_hhmm,
                    ArrDelay, DepDelay
                FROM flights
                WHERE {where}
            ),
            minutes AS (
                SELECT
                    Tail_Number, FlightDate, ArrDelay, DepDelay,
                    (crs_dep_hhmm / 100) * 60 + (crs_dep_hhmm % 100) AS crs_dep_minutes,
                    (crs_arr_hhmm / 100) * 60 + (crs_arr_hhmm % 100) AS crs_arr_minutes
                FROM scoped
                WHERE crs_dep_hhmm IS NOT NULL AND crs_arr_hhmm IS NOT NULL
            ),
            sequenced AS (
                SELECT
                    DepDelay,
                    LAG(ArrDelay) OVER (
                        PARTITION BY Tail_Number, FlightDate ORDER BY crs_dep_minutes
                    ) AS predecessor_arr_delay,
                    crs_dep_minutes - LAG(crs_arr_minutes) OVER (
                        PARTITION BY Tail_Number, FlightDate ORDER BY crs_dep_minutes
                    ) AS scheduled_turnaround_minutes
                FROM minutes
            ),
            pairs AS (
                SELECT * FROM sequenced
                WHERE predecessor_arr_delay IS NOT NULL AND DepDelay IS NOT NULL
            )
            SELECT
                COUNT(*) AS pairs,
                CORR(predecessor_arr_delay, DepDelay) AS correlation,
                AVG(CASE WHEN predecessor_arr_delay <= 0 THEN DepDelay END) AS avg_dep_delay_predecessor_on_time,
                AVG(CASE WHEN predecessor_arr_delay > 15 THEN DepDelay END) AS avg_dep_delay_predecessor_late_15plus,
                AVG(CASE WHEN predecessor_arr_delay > 60 THEN DepDelay END) AS avg_dep_delay_predecessor_late_60plus,
                CORR(
                    CASE WHEN scheduled_turnaround_minutes <= 25 THEN predecessor_arr_delay END,
                    CASE WHEN scheduled_turnaround_minutes <= 25 THEN DepDelay END
                ) AS correlation_tight,
                COUNT(*) FILTER (WHERE scheduled_turnaround_minutes <= 25) AS pairs_tight,
                CORR(
                    CASE WHEN scheduled_turnaround_minutes > 25 AND scheduled_turnaround_minutes <= 45 THEN predecessor_arr_delay END,
                    CASE WHEN scheduled_turnaround_minutes > 25 AND scheduled_turnaround_minutes <= 45 THEN DepDelay END
                ) AS correlation_normal,
                COUNT(*) FILTER (WHERE scheduled_turnaround_minutes > 25 AND scheduled_turnaround_minutes <= 45) AS pairs_normal,
                CORR(
                    CASE WHEN scheduled_turnaround_minutes > 45 THEN predecessor_arr_delay END,
                    CASE WHEN scheduled_turnaround_minutes > 45 THEN DepDelay END
                ) AS correlation_loose,
                COUNT(*) FILTER (WHERE scheduled_turnaround_minutes > 45) AS pairs_loose
            FROM pairs
            """,
            params,
        ).fetchone()

    if row is None or row[0] == 0:
        return {"error": "No same-day multi-leg rotations matched that filter."}

    return {
        "pairs": row[0],
        "correlation": row[1],
        "avg_dep_delay_predecessor_on_time": row[2],
        "avg_dep_delay_predecessor_late_15plus": row[3],
        "avg_dep_delay_predecessor_late_60plus": row[4],
        "turnaround_strata": [
            {"label": "Tight (\u226425 min)", "pairs": row[6], "correlation": row[5]},
            {"label": "Normal (26\u201345 min)", "pairs": row[8], "correlation": row[7]},
            {"label": "Loose (>45 min)", "pairs": row[10], "correlation": row[9]},
        ],
    }


def get_health_score(
    carrier: str | None = None,
    airport: str | None = None,
    origin: str | None = None,
    dest: str | None = None,
    tail: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    given = sum(1 for v in (carrier, airport, (origin and dest), tail) if v)
    if given != 1:
        return {"error": "Give exactly one of: carrier, airport, origin+dest, or tail."}

    clauses: list[str] = []
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    elif airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    elif origin and dest:
        clauses.append("Origin = ? AND Dest = ?")
        params.append(origin.upper())
        params.append(dest.upper())
    elif tail:
        clauses.append("Tail_Number = ?")
        params.append(tail.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    health = compute_health_score(where, params)
    if health is None:
        return {"error": "No flights matched that filter."}
    return health


def get_turnbacks(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["Cancelled = 0"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        # Origin-only: a turnback is a departure-side event.
        clauses.append("Origin = ?")
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        row = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                SUM(CASE WHEN FirstDepTime IS NOT NULL THEN 1 ELSE 0 END) AS turnback_flights,
                AVG(CASE WHEN FirstDepTime IS NOT NULL THEN TRY_CAST(TotalAddGTime AS DOUBLE) END) AS avg_add_gtime_minutes,
                AVG(CASE WHEN FirstDepTime IS NOT NULL
                    THEN (CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END) END) AS turnback_on_time_rate,
                AVG(CASE WHEN FirstDepTime IS NULL
                    THEN (CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END) END) AS non_turnback_on_time_rate
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

    if row is None or row[0] == 0:
        return {"error": "No flights matched that filter."}

    total_flights, turnback_flights, avg_add_gtime, turnback_otr, non_turnback_otr = row
    return {
        "total_flights": total_flights,
        "turnback_flights": turnback_flights,
        "turnback_rate": (turnback_flights / total_flights if total_flights else 0),
        "avg_add_gtime_minutes": avg_add_gtime,
        "turnback_on_time_rate": turnback_otr,
        "non_turnback_on_time_rate": non_turnback_otr,
    }


def get_diversions(
    carrier: str | None = None,
    airport: str | None = None,
    origin: str | None = None,
    dest: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    clauses = ["1=1"]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if origin:
        clauses.append("Origin = ?")
        params.append(origin.upper())
    if dest:
        clauses.append("Dest = ?")
        params.append(dest.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)
    diverted_where = where + " AND Diverted = 1"

    with open_readonly_connection() as connection:
        overall = connection.execute(
            f"SELECT COUNT(*), SUM(Diverted) FROM flights WHERE {where}", params
        ).fetchone()

        if overall is None or overall[0] == 0:
            return {"error": "No flights matched that filter."}

        total_flights, diverted_flights = overall
        diverted_flights = diverted_flights or 0

        landing_rows = connection.execute(
            f"""
            SELECT
                CASE
                    WHEN TRY_CAST(DivAirportLandings AS INTEGER) IS NULL
                         OR TRY_CAST(DivAirportLandings AS INTEGER) <= 1 THEN '1 stop'
                    WHEN TRY_CAST(DivAirportLandings AS INTEGER) = 2 THEN '2 stops'
                    ELSE '3+ stops'
                END AS bucket,
                COUNT(*) AS diverted_flights,
                AVG(CASE WHEN TRY_CAST(DivReachedDest AS INTEGER) = 1 THEN 1.0 ELSE 0.0 END) AS reached_destination_rate
            FROM flights
            WHERE {diverted_where}
            GROUP BY bucket
            """,
            params,
        ).fetchall()

        top_diversion_airports = connection.execute(
            f"""
            SELECT
                Div1Airport,
                COUNT(*) AS diverted_flights,
                AVG(CASE WHEN TRY_CAST(DivReachedDest AS INTEGER) = 1 THEN 1.0 ELSE 0.0 END) AS reached_destination_rate,
                AVG(DivArrDelay) AS avg_arrival_delay_minutes,
                AVG(DivDistance - Distance) AS avg_extra_distance_miles
            FROM flights
            WHERE {diverted_where} AND Div1Airport IS NOT NULL
            GROUP BY Div1Airport
            ORDER BY diverted_flights DESC
            LIMIT 5
            """,
            params,
        ).fetchall()

        cost_row = connection.execute(
            f"""
            SELECT
                AVG(DivArrDelay) AS avg_arrival_delay_minutes,
                AVG(DivDistance - Distance) AS avg_extra_distance_miles,
                AVG(DivActualElapsedTime - CRSElapsedTime) AS avg_extra_time_minutes
            FROM flights
            WHERE {diverted_where}
                AND DivArrDelay IS NOT NULL AND DivDistance IS NOT NULL
                AND DivActualElapsedTime IS NOT NULL AND CRSElapsedTime IS NOT NULL
            """,
            params,
        ).fetchone()

    bucket_order = {"1 stop": 0, "2 stops": 1, "3+ stops": 2}
    landing_buckets = sorted(
        (
            {"bucket": r[0], "diverted_flights": r[1], "reached_destination_rate": r[2]}
            for r in landing_rows
        ),
        key=lambda b: bucket_order.get(b["bucket"], 3),
    )
    return {
        "total_flights": total_flights,
        "diverted_flights": diverted_flights,
        "diversion_rate": (diverted_flights / total_flights if total_flights else 0),
        "landing_buckets": landing_buckets,
        "top_diversion_airports": [
            {
                "airport": r[0], "diverted_flights": r[1], "reached_destination_rate": r[2],
                "avg_arrival_delay_minutes": r[3], "avg_extra_distance_miles": r[4],
            }
            for r in top_diversion_airports
        ],
        "average_diversion_cost": (
            {
                "avg_arrival_delay_minutes": cost_row[0],
                "avg_extra_distance_miles": cost_row[1],
                "avg_extra_time_minutes": cost_row[2],
            }
            if cost_row and cost_row[0] is not None else None
        ),
    }


def get_schedule_padding(
    carrier: str | None = None,
    airport: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Yearly-granularity trend by default -- good enough for a
    conversational 'is this carrier padding its schedule' answer without
    needing the finer week/day resolution the site's own UI offers for
    narrow date ranges."""
    clauses = [
        "Cancelled = 0", "CRSElapsedTime IS NOT NULL", "ActualElapsedTime IS NOT NULL",
        "CRSElapsedTime > 0", "ActualElapsedTime > 0",
    ]
    params: list[Any] = []
    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                CAST(EXTRACT(YEAR FROM FlightDate) AS VARCHAR) AS period,
                COUNT(*) AS total_flights,
                AVG(CRSElapsedTime) AS avg_scheduled_minutes,
                AVG(ActualElapsedTime) AS avg_actual_minutes
            FROM flights
            WHERE {where}
            GROUP BY period
            ORDER BY period
            """,
            params,
        ).fetchall()

    if not rows:
        return {"error": "No flights matched that filter."}

    return {
        "periods": [
            {
                "period": r[0],
                "total_flights": r[1],
                "avg_scheduled_minutes": r[2],
                "avg_actual_minutes": r[3],
                "padding_minutes": r[2] - r[3],
            }
            for r in rows
        ]
    }


# BTS's DayOfWeek field (1=Monday...7=Sunday) hasn't been used anywhere
# else in this codebase yet -- this is the standard BTS convention, but
# unconfirmed against this specific warehouse. Verify with:
#   python -c "import duckdb; con = duckdb.connect('Data/Warehouse/airline.duckdb', read_only=True); print(con.execute(\"SELECT DayOfWeek, COUNT(*) FROM flights GROUP BY DayOfWeek ORDER BY DayOfWeek\").fetchall())"
# Should print 7 rows, roughly even counts, ordered 1-7.
_DAY_OF_WEEK_LABELS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
_DAY_OF_WEEK_NUMBERS = {v: k for k, v in _DAY_OF_WEEK_LABELS.items()}

_TIME_OF_DAY_HOUR_RANGES = {
    "early_morning": (5, 8),
    "morning": (8, 11),
    "afternoon": (11, 15),
    "evening": (15, 20),
}

_GROUP_BY_EXPRESSIONS = {
    "carrier": "Marketing_Airline_Network",
    "origin": "Origin",
    "dest": "Dest",
    "year": "CAST(EXTRACT(YEAR FROM FlightDate) AS VARCHAR)",
    "month": "strftime(FlightDate, '%Y-%m')",
    "day_of_week": "DayOfWeek",
    "hour": "CAST(FLOOR(TRY_CAST(CRSDepTime AS INTEGER) / 100) AS INTEGER)",
    "distance_bucket": "CASE WHEN Distance < 500 THEN 'Short-haul' WHEN Distance < 1500 THEN 'Medium-haul' ELSE 'Long-haul' END",
}

_DISTANCE_BUCKET_LABELS = {"short_haul": "Short-haul", "medium_haul": "Medium-haul", "long_haul": "Long-haul"}


def flexible_query(
    carrier: str | None = None,
    airport: str | None = None,
    origin: str | None = None,
    dest: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    days_of_week: list[str] | None = None,
    time_of_day: str | None = None,
    distance_bucket: str | None = None,
    tail: str | None = None,
    group_by: str | None = None,
    limit: int = 20,
) -> dict:
    if group_by is not None and group_by not in _GROUP_BY_EXPRESSIONS:
        return {"error": f"Unrecognized group_by value: {group_by}"}

    clauses: list[str] = ["1=1"]
    params: list[Any] = []

    if carrier:
        clauses.append("Marketing_Airline_Network = ?")
        params.append(carrier.upper())
    if airport:
        clauses.append("(Origin = ? OR Dest = ?)")
        params.append(airport.upper())
        params.append(airport.upper())
    if origin:
        clauses.append("Origin = ?")
        params.append(origin.upper())
    if dest:
        clauses.append("Dest = ?")
        params.append(dest.upper())
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    if tail:
        clauses.append("Tail_Number = ?")
        params.append(tail.upper())
    if distance_bucket and distance_bucket in _DISTANCE_BUCKET_LABELS:
        clauses.append(f"({_GROUP_BY_EXPRESSIONS['distance_bucket']}) = ?")
        params.append(_DISTANCE_BUCKET_LABELS[distance_bucket])
    if days_of_week:
        valid_days = [d for d in days_of_week if d in _DAY_OF_WEEK_NUMBERS]
        if valid_days:
            placeholders = ",".join(["?"] * len(valid_days))
            clauses.append(f"DayOfWeek IN ({placeholders})")
            params.extend(_DAY_OF_WEEK_NUMBERS[d] for d in valid_days)
    if time_of_day:
        hour_expr = "CAST(FLOOR(TRY_CAST(CRSDepTime AS INTEGER) / 100) AS INTEGER)"
        clauses.append("CRSDepTime IS NOT NULL")
        if time_of_day == "red_eye":
            clauses.append(f"(({hour_expr} >= 20) OR ({hour_expr} < 5))")
        elif time_of_day in _TIME_OF_DAY_HOUR_RANGES:
            lo, hi = _TIME_OF_DAY_HOUR_RANGES[time_of_day]
            clauses.append(f"{hour_expr} >= ? AND {hour_expr} < ?")
            params.append(lo)
            params.append(hi)

    where = " AND ".join(clauses)

    applied_filters = {
        k: v
        for k, v in {
            "carrier": carrier, "airport": airport, "origin": origin, "dest": dest,
            "start_date": start_date, "end_date": end_date, "days_of_week": days_of_week,
            "time_of_day": time_of_day, "distance_bucket": distance_bucket, "tail": tail,
            "group_by": group_by,
        }.items()
        if v
    }

    metrics_sql = """
        COUNT(*) AS total_flights,
        AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
        AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
        AVG(CASE WHEN Cancelled = 0 THEN DepDelay END) AS avg_departure_delay_minutes,
        AVG(Cancelled * 1.0) AS cancellation_rate
    """

    # Chronological/natural order reads far better than volume order for
    # these dimensions -- volume order was the original bug (hour groups
    # showing 20, 21, 22, 8, 10, 9 instead of in time order). Carrier/
    # origin/dest have no natural order, so volume (busiest first) stays
    # the more useful default there.
    _NATURAL_ASCENDING_GROUP_BYS = {"year", "month", "day_of_week", "hour"}

    with open_readonly_connection() as connection:
        if group_by:
            group_expr = _GROUP_BY_EXPRESSIONS[group_by]
            safe_limit = max(1, min(int(limit or 20), 100))
            if group_by == "distance_bucket":
                order_clause = "ORDER BY CASE group_value WHEN 'Short-haul' THEN 0 WHEN 'Medium-haul' THEN 1 ELSE 2 END"
            elif group_by in _NATURAL_ASCENDING_GROUP_BYS:
                # Note: hour ordering is plain 0-23 ascending, not aware of
                # a time_of_day=red_eye filter's midnight wraparound (e.g.
                # 20,21,22,23,0,1,2,3,4 in real chronological order) --
                # that'd show as 0,1,2,3,4,20,21,22,23 instead. A real
                # improvement over the old volume-sorted bug, not a
                # complete fix for every case.
                order_clause = "ORDER BY group_value ASC"
            else:
                order_clause = "ORDER BY total_flights DESC"
            rows = connection.execute(
                f"""
                SELECT ({group_expr}) AS group_value, {metrics_sql}
                FROM flights
                WHERE {where}
                GROUP BY group_value
                {order_clause}
                LIMIT {safe_limit}
                """,
                params,
            ).fetchall()
            if not rows:
                return {"error": "No flights matched that filter.", "applied_filters": applied_filters}
            return {
                "applied_filters": applied_filters,
                "group_by": group_by,
                "groups": [
                    {
                        "group": (_DAY_OF_WEEK_LABELS.get(r[0], r[0]) if group_by == "day_of_week" else r[0]),
                        "total_flights": r[1],
                        "on_time_rate": r[2],
                        "avg_arrival_delay_minutes": r[3],
                        "avg_departure_delay_minutes": r[4],
                        "cancellation_rate": r[5],
                    }
                    for r in rows
                ],
            }

        row = connection.execute(f"SELECT {metrics_sql} FROM flights WHERE {where}", params).fetchone()

    if row is None or row[0] == 0:
        return {"error": "No flights matched that filter.", "applied_filters": applied_filters}
    return {
        "applied_filters": applied_filters,
        "total_flights": row[0],
        "on_time_rate": row[1],
        "avg_arrival_delay_minutes": row[2],
        "avg_departure_delay_minutes": row[3],
        "cancellation_rate": row[4],
    }


def _normal_cdf(z: float) -> float:
    """Standard normal CDF via math.erf -- no scipy dependency needed."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def check_significance(
    rate_a: float,
    n_a: int,
    rate_b: float,
    n_b: int,
    label_a: str = "A",
    label_b: str = "B",
) -> dict:
    """Two-proportion z-test. Standard test for whether two observed rates
    differ by more than sampling noise would explain -- the same logic
    used throughout this site's own methodology (e.g. the health score's
    calibration), just applied ad hoc to whatever two numbers the model is
    comparing."""
    if n_a <= 0 or n_b <= 0:
        return {"error": "Sample sizes must be positive."}
    if not (0 <= rate_a <= 1) or not (0 <= rate_b <= 1):
        return {"error": "Rates must be decimals between 0 and 1, not percentages."}

    x_a = rate_a * n_a
    x_b = rate_b * n_b
    p_pool = (x_a + x_b) / (n_a + n_b)
    if p_pool <= 0 or p_pool >= 1:
        return {"error": "Degenerate proportions (0% or 100% on one side), cannot compute a meaningful test."}

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return {"error": "Standard error is zero, cannot compute a test."}

    z = (rate_a - rate_b) / se
    p_value = 2 * (1 - _normal_cdf(abs(z)))

    return {
        "label_a": label_a,
        "rate_a": rate_a,
        "n_a": n_a,
        "label_b": label_b,
        "rate_b": rate_b,
        "n_b": n_b,
        "difference_pct_points": (rate_a - rate_b) * 100,
        "z_score": z,
        "p_value": p_value,
        "significant_at_95pct": p_value < 0.05,
    }


def get_carrier_profile(carrier: str, start_date: str | None = None, end_date: str | None = None) -> dict:
    """Consolidated carrier profile: overall stats, health score, monthly
    trend, delay causes, top routes and airports -- one call instead of
    chaining get_summary/get_trend/get_delay_causes/get_health_score
    separately. Mirrors /api/carrier-detail (the same endpoint behind the
    site's dedicated /carriers/[code] profile pages)."""
    carrier = carrier.upper()
    clauses = ["Marketing_Airline_Network = ?"]
    params: list[Any] = [carrier]
    if start_date:
        clauses.append("FlightDate >= CAST(? AS DATE)")
        params.append(start_date)
    if end_date:
        clauses.append("FlightDate <= CAST(? AS DATE)")
        params.append(end_date)
    where = " AND ".join(clauses)

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights
            WHERE {where}
            """,
            params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            return {"error": "No flights matched that carrier/date range."}

        cause_row = connection.execute(
            f"""
            SELECT SUM(CarrierDelay), SUM(WeatherDelay), SUM(NASDelay), SUM(SecurityDelay), SUM(LateAircraftDelay)
            FROM flights WHERE {where} AND Cancelled = 0
            """,
            params,
        ).fetchone()

        route_rows = connection.execute(
            f"""
            SELECT Origin || ' -> ' || Dest AS route, COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights WHERE {where} AND Origin IS NOT NULL AND Dest IS NOT NULL
            GROUP BY Origin, Dest ORDER BY total_flights DESC LIMIT 8
            """,
            params,
        ).fetchall()

    causes = {"Carrier": cause_row[0] or 0, "Weather": cause_row[1] or 0, "NAS": cause_row[2] or 0,
               "Security": cause_row[3] or 0, "Late Aircraft": cause_row[4] or 0}
    cause_total = sum(causes.values()) or 1

    return {
        "carrier": carrier,
        "total_flights": overview[0],
        "on_time_rate": overview[1],
        "avg_arrival_delay_minutes": overview[2],
        "cancellation_rate": overview[3],
        "health": compute_health_score(where, params),
        "delay_causes": [{"cause": k, "share": v / cause_total} for k, v in causes.items()],
        "top_routes": [{"route": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in route_rows],
    }


def get_airport_profile(airport: str, start_date: str | None = None, end_date: str | None = None) -> dict:
    """Consolidated airport profile: overall stats, health score, monthly
    trend, delay causes, top routes -- one call instead of chaining several
    separate tools. Mirrors /api/airport-detail (the same endpoint behind
    the site's dedicated /airports/[code] profile pages)."""
    airport = airport.upper()
    date_clauses = []
    date_params: list[Any] = []
    if start_date:
        date_clauses.append("FlightDate >= CAST(? AS DATE)")
        date_params.append(start_date)
    if end_date:
        date_clauses.append("FlightDate <= CAST(? AS DATE)")
        date_params.append(end_date)
    date_where = (" AND " + " AND ".join(date_clauses)) if date_clauses else ""
    where = f"(Origin = ? OR Dest = ?){date_where}"
    params = [airport, airport] + date_params

    with open_readonly_connection() as connection:
        overview = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate,
                AVG(CASE WHEN Cancelled = 0 THEN ArrDelay END) AS avg_arrival_delay_minutes,
                AVG(Cancelled * 1.0) AS cancellation_rate
            FROM flights WHERE {where}
            """,
            params,
        ).fetchone()

        if overview is None or overview[0] == 0:
            return {"error": "No flights matched that airport/date range."}

        cause_row = connection.execute(
            f"SELECT SUM(CarrierDelay), SUM(WeatherDelay), SUM(NASDelay), SUM(SecurityDelay), SUM(LateAircraftDelay) FROM flights WHERE {where} AND Cancelled = 0",
            params,
        ).fetchone()

        route_rows = connection.execute(
            f"""
            SELECT Origin || ' -> ' || Dest AS route, COUNT(*) AS total_flights,
                AVG(CASE WHEN Cancelled = 0 THEN CASE WHEN ArrDel15 = 0 THEN 1.0 ELSE 0.0 END END) AS on_time_rate
            FROM flights WHERE {where}
            GROUP BY Origin, Dest ORDER BY total_flights DESC LIMIT 8
            """,
            params,
        ).fetchall()

    causes = {"Carrier": cause_row[0] or 0, "Weather": cause_row[1] or 0, "NAS": cause_row[2] or 0,
               "Security": cause_row[3] or 0, "Late Aircraft": cause_row[4] or 0}
    cause_total = sum(causes.values()) or 1

    return {
        "airport": airport,
        "total_flights": overview[0],
        "on_time_rate": overview[1],
        "avg_arrival_delay_minutes": overview[2],
        "cancellation_rate": overview[3],
        "health": compute_health_score(where, params),
        "delay_causes": [{"cause": k, "share": v / cause_total} for k, v in causes.items()],
        "top_routes": [{"route": r[0], "total_flights": r[1], "on_time_rate": r[2]} for r in route_rows],
    }


TOOL_FUNCTIONS = {
    "get_summary": get_summary,
    "get_trend": get_trend,
    "compare_carriers": compare_carriers,
    "get_delay_causes": get_delay_causes,
    "get_cancellation_causes": get_cancellation_causes,
    "get_distance_buckets": get_distance_buckets,
    "get_time_of_day": get_time_of_day,
    "get_codeshare": get_codeshare,
    "get_delay_propagation": get_delay_propagation,
    "get_health_score": get_health_score,
    "get_turnbacks": get_turnbacks,
    "get_diversions": get_diversions,
    "get_schedule_padding": get_schedule_padding,
    "flexible_query": flexible_query,
    "check_significance": check_significance,
    "get_carrier_profile": get_carrier_profile,
    "get_airport_profile": get_airport_profile,
}


class CopilotError(RuntimeError):
    pass


def _claude_headers() -> dict:
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": CLAUDE_API_VERSION,
        "content-type": "application/json",
    }


def _claude_request(messages: list[dict], model: str, *, force_final: bool = False) -> dict:
    if not ANTHROPIC_API_KEY:
        raise CopilotError("ANTHROPIC_API_KEY is not configured")

    payload = {
        "model": model,
        "max_tokens": CLAUDE_MAX_TOKENS,
        # System prompt as a content-block array (not a plain string) so a
        # cache_control marker can be attached to it. Anthropic's caching
        # hierarchy is tools -> system -> messages, in that order -- a
        # breakpoint on this system block caches BOTH the tools array and
        # this system prompt as one prefix (everything static and repeated
        # on every single call), leaving only the growing message history
        # uncached, which is exactly what should be re-processed each time.
        # Note: the cache is model-specific -- switching tiers (and
        # therefore models) mid-conversation starts a fresh cache for that
        # model rather than sharing one across tiers. Not a problem in
        # practice since mode is a sticky per-user choice, not something
        # that flips every message.
        "system": [
            {"type": "text", "text": SYSTEM_INSTRUCTION, "cache_control": {"type": "ephemeral"}}
        ],
        "tools": TOOLS,
        "messages": messages,
    }
    if force_final:
        # tool_choice: none forbids another tool_use block, so Claude MUST
        # answer in text using whatever evidence is already in `messages` --
        # used only for the forced last-hop synthesis (see stream_copilot /
        # ask_copilot) after max_hops is reached, so a thorough model that
        # legitimately wanted more tool calls still produces a real answer
        # instead of the conversation just being cut off.
        #
        # thinking explicitly disabled too -- confirmed this matters:
        # with thinking still on, claude-sonnet-5 would sometimes end its
        # turn (stop_reason=end_turn, not truncated) having produced ONLY a
        # thinking block and no text at all, silently reproducing the exact
        # empty-answer failure this force_final call exists to prevent.
        # Disabling thinking here removes that failure mode entirely --
        # verified across repeated runs of the same real multi-hop
        # question that reliably reproduced it beforehand. Not needed for
        # the normal (non-final) hops, where the model deciding to think
        # before calling a tool is fine.
        payload["tool_choice"] = {"type": "none"}
        payload["thinking"] = {"type": "disabled"}
    try:
        response = requests.post(
            CLAUDE_URL,
            headers=_claude_headers(),
            json=payload,
            timeout=CLAUDE_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = f": {exc.response.text[:400]}"
        raise CopilotError(f"Claude request failed{detail}") from exc


def _claude_stream_request(messages: list[dict], model: str, *, force_final: bool = False):
    """Yields text deltas from Claude's SSE streaming endpoint. Only called
    once a hop has already been confirmed (via a prior non-streaming call)
    to be a final text-only answer, not a tool-use turn -- this function
    doesn't handle tool_use reconstruction from streaming deltas at all, by
    design, matching the same reliability lesson learned from the earlier
    Gemini integration (assembling a tool call from incremental chunks is
    where things actually broke). force_final: see _claude_request."""
    if not ANTHROPIC_API_KEY:
        raise CopilotError("ANTHROPIC_API_KEY is not configured")

    payload = {
        "model": model,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "system": [
            {"type": "text", "text": SYSTEM_INSTRUCTION, "cache_control": {"type": "ephemeral"}}
        ],
        "tools": TOOLS,
        "messages": messages,
        "stream": True,
    }
    if force_final:
        payload["tool_choice"] = {"type": "none"}
        payload["thinking"] = {"type": "disabled"}  # see the comment in _claude_request
    try:
        response = requests.post(
            CLAUDE_URL,
            headers=_claude_headers(),
            json=payload,
            timeout=CLAUDE_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()
        current_event = None
        for raw_line in response.iter_lines():
            if not raw_line:
                current_event = None
                continue
            # Same UTF-8 lesson from the Gemini integration: decode raw
            # bytes explicitly rather than trusting requests' guessed
            # response.encoding.
            line = raw_line.decode("utf-8", errors="replace")
            if line.startswith("event:"):
                current_event = line[len("event:"):].strip()
                continue
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if current_event == "content_block_delta":
                delta = data.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if text:
                        yield text
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            detail = f": {exc.response.text[:400]}"
        raise CopilotError(f"Claude streaming request failed{detail}") from exc


def _sanitize_history(history: list[dict] | None) -> list[dict]:
    """Keep only a bounded amount of plain user/assistant text."""
    sanitized: list[dict] = []
    for turn in (history or [])[-12:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        text = content.strip()
        if text:
            sanitized.append({"role": role, "content": text[:4000]})
    return sanitized


def stream_copilot(user_message: str, history: list[dict] | None = None, max_hops: int = 4, tier: str | None = None):
    """Generator yielding SSE-ready event dicts as the pipeline progresses:
    tool_start / tool_complete for each tool call, answer_start once the
    model settles on a final (non-tool-use) response, answer_chunk for each
    piece of streamed text, then done with the full reply + evidence, or
    error.

    `tier` is "public" or "researcher" (default: public, the safer/cheaper
    choice if unset) -- selects which Claude model runs this conversation.
    Same tools, same system prompt, same reasoning either way; only the
    model underneath changes.

    `history` is prior turns as [{"role": "user"|"assistant", "content": "..."}],
    prepended so follow-ups ("compare that with Delta") have the actual
    conversational context, not just the latest message in isolation. Only
    text turns are preserved across turns -- not prior tool_use/tool_result
    blocks -- so a follow-up still triggers fresh tool calls rather than
    reusing earlier evidence; that's an intentional scope cut for size, not
    an oversight.

    Every tool-calling hop uses the NON-streaming Claude call -- assembling
    a tool call from incremental streaming deltas is where the equivalent
    Gemini integration actually broke on real multi-hop questions, so this
    keeps the same proven-safe split: only the FINAL, no-more-tools-needed
    answer streams token by token.

    Claude can request MULTIPLE tool calls in one turn (parallel tool use),
    unlike the one-call-per-hop assumption the Gemini version had -- all of
    them get executed and reported here, and Claude's own protocol requires
    every tool_use block to get a matching tool_result before the next
    call, which this handles by batching them into one follow-up message."""
    model = _model_for_tier(tier)
    messages = _sanitize_history(history)
    messages.append({"role": "user", "content": user_message})
    tools_used: list[dict] = []

    for _ in range(max_hops):
        try:
            body = _claude_request(messages, model)
        except CopilotError as exc:
            yield {"stage": "error", "message": str(exc)}
            return

        content_blocks = body.get("content") or []
        if not content_blocks:
            yield {"stage": "error", "message": "Claude returned no content"}
            return

        tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]

        if tool_use_blocks:
            tool_results_for_followup = []
            for block in tool_use_blocks:
                tool_name = block.get("name")
                tool_args = block.get("input") or {}
                tool_fn = TOOL_FUNCTIONS.get(tool_name)
                if tool_fn is None:
                    yield {"stage": "error", "message": f"Model requested unknown tool: {tool_name}"}
                    return

                yield {"stage": "tool_start", "tool": tool_name, "args": tool_args}
                try:
                    tool_result = tool_fn(**tool_args)
                except Exception as exc:
                    # An unhandled exception here (bad SQL construction from
                    # an unexpected argument combination, etc.) used to kill
                    # the whole generator silently -- surface it instead so
                    # a real failure is diagnosable rather than showing up
                    # as a blank or garbled answer with no explanation.
                    yield {
                        "stage": "error",
                        "message": f"Tool {tool_name} failed: {type(exc).__name__}: {exc}",
                    }
                    return
                tools_used.append({"tool": tool_name, "args": tool_args, "result": tool_result})
                yield {"stage": "tool_complete", "tool": tool_name, "result": tool_result}
                tool_results_for_followup.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(tool_result),
                    }
                )

            # Echo back the model's FULL turn (any text plus every tool_use
            # block), then respond with all tool results batched into one
            # user turn -- Claude requires every tool_use to get a matching
            # tool_result before the next call.
            messages.append({"role": "assistant", "content": content_blocks})
            messages.append({"role": "user", "content": tool_results_for_followup})
            continue

        # No tool use this hop -- this is the final answer. Use the text
        # already in content_blocks from the call above that decided this
        # hop was final, rather than spending a SECOND API call to
        # re-stream a fresh answer. That used to be a real bug, not just
        # inefficiency: the fresh re-stream call didn't disable extended
        # thinking, so it could independently hit the same thinking-only
        # empty-response quirk documented on the force_final path -- when
        # it did, this whole branch silently returned "I couldn't generate
        # a response." even though a perfectly good answer already existed
        # in content_blocks from the first call. Chunking the existing text
        # ourselves keeps the incremental streaming UX without the second,
        # fragile round-trip.
        existing_text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()
        yield {"stage": "answer_start"}
        full_text = existing_text
        chunk_size = 40
        for i in range(0, len(existing_text), chunk_size):
            yield {"stage": "answer_chunk", "text": existing_text[i:i + chunk_size]}

        yield {
            "stage": "done",
            "reply": full_text.strip() or "I couldn't generate a response.",
            "tool_used": [t["tool"] for t in tools_used] or None,
            "evidence": [{"tool": t["tool"], "result": t["result"]} for t in tools_used] or None,
        }
        return

    # Hit max_hops still requesting tools -- a thorough model (Sonnet in
    # particular) can legitimately want more investigation than the hop
    # budget allows on a hard multi-part question. Rather than cutting the
    # conversation off with nothing, force ONE more call with tool use
    # disabled so Claude has to synthesize a real answer from whatever
    # evidence is already gathered -- confirmed this was silently losing
    # answers: Researcher-tier (Sonnet) hit this on a real multi-hop
    # question while Public-tier (Haiku) happened to converge in budget on
    # the identical prompt, so the "smarter" tier looked broken.
    yield {"stage": "answer_start"}
    full_text = ""
    final_messages = messages
    for attempt in range(2):
        # Buffer this attempt's chunks instead of yielding them live -- if
        # this attempt turns out too short and gets retried, the user must
        # never see the discarded attempt's text at all (streaming it live
        # and then retrying would leave stale/garbled partial text in the
        # UI with no way to un-show it). Only the winning attempt's chunks
        # get yielded, right after the loop.
        full_text = ""
        buffered_chunks: list[str] = []
        try:
            for chunk in _claude_stream_request(final_messages, model, force_final=True):
                full_text += chunk
                if chunk:
                    buffered_chunks.append(chunk)
        except CopilotError:
            try:
                body = _claude_request(final_messages, model, force_final=True)
                full_text = "".join(
                    b.get("text", "") for b in (body.get("content") or []) if b.get("type") == "text"
                ).strip()
                if full_text:
                    buffered_chunks = [full_text]
            except CopilotError:
                full_text = ""
        if len(full_text) >= MIN_PLAUSIBLE_ANSWER_LENGTH or attempt == 1:
            for chunk in buffered_chunks:
                yield {"stage": "answer_chunk", "text": chunk}
            break
        # See the matching comment in ask_copilot -- retrying byte-identical
        # input reliably reproduced the same empty result, so the retry has
        # to actually change the input via an explicit nudge turn.
        print(f"[copilot] stream force-final produced no text (attempt {attempt}), retrying with a nudge" if attempt == 0 else
              "[copilot] stream force-final still produced no text after nudge retry")
        final_messages = messages + [
            {"role": "assistant", "content": "(no text produced)"},
            {
                "role": "user",
                "content": (
                    f"Stop investigating and answer now, in plain text, using only what you've "
                    f"already found. The original question was: {user_message!r}"
                ),
            },
        ]

    yield {
        "stage": "done",
        "reply": full_text.strip() or "I gathered several data points but couldn't finish summarizing them.",
        "tool_used": [t["tool"] for t in tools_used] or None,
        "evidence": [{"tool": t["tool"], "result": t["result"]} for t in tools_used] or None,
    }


def ask_copilot(
    user_message: str,
    max_hops: int = 4,
    tier: str | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Blocking version of stream_copilot -- run the tool-calling loop until
    Claude stops requesting tools or we hit max_hops. Claude may legitimately
    want multiple tool calls (sequentially across hops, or several in one
    hop via parallel tool use) before answering, so a single fixed
    round-trip isn't enough."""
    model = _model_for_tier(tier)
    messages = _sanitize_history(history)
    messages.append({"role": "user", "content": user_message})
    tools_used: list[dict] = []

    for _ in range(max_hops):
        body = _claude_request(messages, model)
        content_blocks = body.get("content") or []
        if not content_blocks:
            raise CopilotError("Claude returned no content")

        tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]

        if not tool_use_blocks:
            text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()
            if not text:
                print(f"[copilot] Empty final text with no tool use either. "
                      f"stop_reason={body.get('stop_reason')!r}")
            return {
                "reply": text or "I couldn't generate a response.",
                "tool_used": [t["tool"] for t in tools_used] or None,
                "evidence": [t["result"] for t in tools_used] or None,
            }

        tool_results_for_followup = []
        for block in tool_use_blocks:
            tool_name = block.get("name")
            tool_args = block.get("input") or {}
            tool_fn = TOOL_FUNCTIONS.get(tool_name)
            if tool_fn is None:
                raise CopilotError(f"Model requested unknown tool: {tool_name}")

            tool_result = tool_fn(**tool_args)
            tools_used.append({"tool": tool_name, "args": tool_args, "result": tool_result})
            tool_results_for_followup.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": json.dumps(tool_result)}
            )

        messages.append({"role": "assistant", "content": content_blocks})
        messages.append({"role": "user", "content": tool_results_for_followup})

    # Hit max_hops still requesting tools -- force one more call with tool
    # use disabled so Claude has to synthesize from whatever evidence is
    # already gathered instead of the conversation just being cut off. See
    # the matching comment in stream_copilot for how this was found.
    text = ""
    final_messages = messages
    for attempt in range(2):
        try:
            body = _claude_request(final_messages, model, force_final=True)
            text = "".join(
                b.get("text", "") for b in (body.get("content") or []) if b.get("type") == "text"
            ).strip()
        except CopilotError as exc:
            print(f"[copilot] forced-final call failed (attempt {attempt}): {exc}")
            text = ""
        if len(text) >= MIN_PLAUSIBLE_ANSWER_LENGTH:
            break
        # Rare: even with thinking disabled, the model occasionally ends
        # its turn (stop_reason=end_turn, not truncated) having produced
        # only a thinking block and no text. Confirmed this is tied to the
        # specific accumulated conversation state, not per-call randomness
        # -- retrying with byte-identical input reliably reproduced the
        # SAME empty result. So the retry has to actually change the input:
        # appending an explicit nudge turn perturbs it enough to get a real
        # answer in practice.
        print(f"[copilot] forced-final produced no text (attempt {attempt}), retrying with a nudge" if attempt == 0 else
              "[copilot] forced-final still produced no text after nudge retry")
        final_messages = messages + [
            {"role": "assistant", "content": "(no text produced)"},
            {
                "role": "user",
                "content": (
                    f"Stop investigating and answer now, in plain text, using only what you've "
                    f"already found. The original question was: {user_message!r}"
                ),
            },
        ]
    return {
        "reply": text or "I gathered several data points but couldn't finish summarizing them.",
        "tool_used": [t["tool"] for t in tools_used] or None,
        "evidence": [t["result"] for t in tools_used] or None,
    }
