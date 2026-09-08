export const COMPONENT_LABELS: Record<string, string> = {
  reliability: "On-time performance",
  delay_severity: "Average delay",
  severe_delay_exposure: "Very late flights",
  cancellation_resilience: "Cancelled flights",
  diversion_resilience: "Diverted flights",
};

export const FEATURE_LABELS: Record<string, string> = {
  severe_delay_rate: "Very late flight rate",
  cancellation_rate: "Cancellation rate",
  average_departure_delay: "Average departure delay",
  late_aircraft_delay_share: "Late previous aircraft",
  ground_delay_share: "Ground-time delays",
  log_flight_volume: "Number of flights",
  trend_severe_delay_rate: "Recent change in very late flights",
  seasonal_index: "Usual pattern for this month",
};

export const TURNAROUND_ROWS = ["Tight", "Normal", "Loose"];

export type DecisionTab = "levers" | "scenario" | "ranking" | "risk" | "bank" | "portfolio" | "resilience" | "capacity";

export const TAB_HELP: Record<DecisionTab, {
  label: string;
  question: string;
  choose: string;
  result: string;
  kind: string;
}> = {
  levers: {
    label: "Find a weak area",
    question: "Which part of one airline's score should we look at first?",
    choose: "One airline",
    result: "A score, plus the area with the biggest gap to the rest of the network.",
    kind: "Look back",
  },
  scenario: {
    label: "See what happened",
    question: "When one flight is late, how late is the next flight usually?",
    choose: "One airline",
    result: "A simple table of what happened after different kinds of delays.",
    kind: "Look back",
  },
  ranking: {
    label: "Where to start",
    question: "Which airlines have the clearest improvement opportunity?",
    choose: "Nothing — the whole network is compared",
    result: "A ranked shortlist, showing both the possible score change and the number of flights affected.",
    kind: "Look back",
  },
  risk: {
    label: "Look ahead",
    question: "Which airline or airport may have an unusually difficult month next?",
    choose: "An airline or airport",
    result: "A probability and a simple risk label, plus the main signals behind it.",
    kind: "Estimate",
  },
  bank: {
    label: "Try moving flights",
    question: "Could moving a few flights spread out the busiest departure period?",
    choose: "An airport, time window, and maximum shift",
    result: "A before-and-after schedule showing whether the busiest 15-minute period gets smaller.",
    kind: "Try a change",
  },
  portfolio: {
    label: "Pick focus areas",
    question: "If attention is limited, which airlines or airports should we focus on?",
    choose: "Airlines or airports, a focus limit, and what matters most",
    result: "A shortlist that fits the limit, with the other important measures still shown.",
    kind: "Choose",
  },
  resilience: {
    label: "Find important airports",
    question: "Which airports are busiest, or connect important parts of the network?",
    choose: "How small a route to include",
    result: "Three lists: busiest by routes, busiest by flights, and important connecting airports.",
    kind: "Look back",
  },
  capacity: {
    label: "See passengers and seats",
    question: "Do passenger demand and available seats move with on-time performance?",
    choose: "An airline, or all airlines",
    result: "A first comparison of T-100 traffic measures beside on-time results.",
    kind: "New data",
  },
};

export const METRIC_LABELS: Record<string, string> = {
  severe_delay_exposure: "Very late flights",
  reliability: "On-time reliability",
  delay_severity: "Typical delay length",
  cancellation_resilience: "Cancellations",
  diversion_resilience: "Diversions",
  total_flights_millions: "Number of flights",
};

export const COST_MODEL_LABELS: Record<string, string> = {
  unit: "Same attention per target",
  flight_volume_millions: "More attention for larger targets",
  sqrt_flight_volume: "A middle ground",
};

export const TAB_METHOD_ANCHORS: Record<string, string> = {
  levers: "health-score-levers",
  scenario: "turnaround-scenarios",
  ranking: "network-opportunity-ranking",
  risk: "predictive-risk-screen",
  bank: "departure-bank-smoothing",
  portfolio: "network-protection-portfolio",
  resilience: "network-resilience-ranking",
  capacity: "t-100-and-on-time-correlation",
};
export const PREDECESSOR_COLS = ["On time or early", "Late (1-60 min)", "Very late (60+ min)"];
