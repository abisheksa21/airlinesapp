export type SiteMode = "public" | "researcher";

export type Summary = {
  total_flights: number;
  start_date: string;
  end_date: string;
  carrier_count: number;
  on_time_rate: number | null;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number | null;
  unique_routes: number;
  unique_airports: number;
};

export type CarrierMetric = {
  carrier: string;
  total_flights: number;
  on_time_rate: number | null;
  avg_arrival_delay_minutes: number | null;
  cancellation_rate: number | null;
};

export type AirportMetric = {
  airport: string;
  total_flights: number;
};

export type RouteMetric = {
  route: string;
  total_flights: number;
  on_time_rate: number | null;
};

export type NetworkNode = {
  airport: string;
  latitude: number;
  longitude: number;
  total_flights: number;
};

export type NetworkEdge = {
  origin: string;
  dest: string;
  total_flights: number;
  on_time_rate: number | null;
};

export type NetworkMap = {
  source: string;
  period: { start_date: string; end_date: string };
  coordinate_source: string;
  coverage: { routes_requested: number; routes_mapped: number; airports_mapped: number };
  nodes: NetworkNode[];
  edges: NetworkEdge[];
};

export type Evidence = {
  source?: string;
  period?: string;
  sample?: string | number;
  definition?: string;
  method?: string;
  caveat?: string;
};
