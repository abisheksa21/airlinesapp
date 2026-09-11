export type Lever = {
  component: string;
  current_value: number;
  network_median: number;
  weight: number;
  hypothetical_score_if_at_median: number;
  point_gain: number;
};

export type LeverResult = {
  carrier: string;
  current_score: number;
  current_rating: string;
  peer_count: number;
  levers: Lever[];
};

export type ScenarioCell = {
  turnaround_bucket: string;
  predecessor_bucket: string;
  pairs: number;
  avg_successor_dep_delay: number;
};

export type ScenarioResult = {
  carrier: string | null;
  tight_turnaround_minutes: number;
  target_turnaround_minutes: number;
  cells: ScenarioCell[];
};

export type RankingEntry = {
  carrier: string;
  current_score: number;
  current_rating: string;
  total_flights: number;
  top_lever_component: string;
  top_lever_current_value: number;
  top_lever_network_median: number;
  top_lever_point_gain: number;
};

export type RankingResult = {
  peer_count: number;
  carriers: RankingEntry[];
};

export type CalibrationBin = {
  probability_band: string;
  count: number;
  mean_predicted_probability: number;
  observed_risk_rate: number;
};

export type Metrics = {
  examples: number;
  positive_rate: number;
  brier_score: number;
  log_loss: number;
  precision_recall_auc: number;
  calibration_bins: CalibrationBin[];
};

export type Coefficient = {
  feature: string;
  standardized_coefficient: number;
  direction: "higher_risk" | "lower_risk";
};

export type CentralityEntry = { airport: string; value: number };

export type NetworkResilienceResult = {
  scope: { minimum_flights_per_route: number; airport_count: number; route_count: number };
  degree_centrality: { top_by_route_count: CentralityEntry[]; top_by_flight_volume: CentralityEntry[] };
  betweenness_centrality: { top_structural_bridges: CentralityEntry[] };
  methodology: { combination_policy: string; limitations: string[] };
};

export type CapacityCorrelationRow = {
  year: number;
  month: number;
  carrier: string;
  origin: string;
  dest: string;
  departures_scheduled: number;
  departures_performed: number;
  seats_available: number;
  passengers: number;
  load_factor: number | null;
  completion_rate: number | null;
  otp_flights: number;
  completed_flights: number;
  on_time_rate: number | null;
  avg_arrival_delay: number | null;
};

export type CapacityCorrelationResult = {
  status: string;
  source: string;
  grain: string;
  filters: { carrier: string | null; minimum_otp_flights: number };
  overview: {
    matched_route_months: number;
    average_load_factor: number | null;
    average_on_time_rate: number | null;
    average_arrival_delay: number | null;
    correlation_load_factor_on_time: number | null;
    correlation_passengers_on_time: number | null;
    correlation_seats_on_time: number | null;
    first_period: number | null;
    last_period: number | null;
  };
  rows: CapacityCorrelationRow[];
  methodology: {
    association: string;
    interpretation: string;
    join_policy: string;
    missing_data: string;
  };
};

export type CapacityTrendPoint = {
  month: string;
  route_months: number;
  otp_flights: number;
  completed_flights: number;
  passengers: number;
  seats_available: number;
  departures_performed: number;
  load_factor: number | null;
  on_time_rate: number | null;
  avg_arrival_delay: number | null;
};

export type CapacityTrendResult = {
  status: string;
  source: string;
  grain: string;
  filters: { carrier: string | null; minimum_otp_flights: number };
  months: CapacityTrendPoint[];
  methodology: {
    interpretation: string;
    join_policy: string;
  };
};

export type RiskResult = {
  entity_type: string;
  entity: string;
  as_of_period: string;
  risk_probability: number;
  risk_band: string;
  risk_threshold_definition: string;
  current_features: Record<string, number>;
  model_coefficients: Coefficient[];
  split: {
    train_end: string;
    validation_end: string;
    train_examples: number;
    validation_examples: number;
    test_examples: number;
  };
  validation_metrics: Metrics;
  test_metrics: Metrics;
  entities_in_training_panel: number;
};
