export type Mode = "live" | "replay";

export interface Envelope {
  mode: Mode;
  server_now_utc: string;
  replay?: { captured_at: string; synthetic: boolean; description?: string; sources?: string[] };
}

export interface Category {
  key: string;
  label: string;
  color: string;
  text_color: string;
  aqi: number | null;
  lower: number | null;
  upper: number | null;
}

export interface LegendItem {
  key: string;
  label: string;
  lower: number | null;
  upper: number | null;
  color: string;
  text_color: string;
}

export interface CacheMeta {
  status: "miss" | "hit" | "stale" | "replay" | "error";
  stale: boolean;
  retrieved_at: string | null;
  error: string | null;
}

export interface AqSource {
  provider: string;
  provider_url: string;
  model: string;
  domain: string;
  data_type: string;
  aqi_standard: string;
  aqi_averaging: string;
  spatial_resolution: string;
  spatial_resolution_deg: number;
  native_time_step: string;
  update_frequency: string;
  attribution: string;
  licence: string;
  cache?: CacheMeta;
}

export interface Health extends Envelope {
  status: string;
  openaq_configured: boolean;
  legend: LegendItem[];
  aq_source: AqSource;
  cell_size_deg: number;
}

export interface Series {
  units: string | null;
  values: (number | null)[];
}

export interface Reading {
  parameter: string;
  label: string;
  value: number | null;
  units: string | null;
  aqi_standard: string | null;
  valid_from_utc: string;
  valid_to_utc: string;
  lat: number;
  lon: number;
  source: string;
  data_type: string;
  retrieved_at: string | null;
  resolution: string;
}

export interface PointResponse extends Envelope {
  location: {
    requested: { lat: number; lon: number };
    model_point: { lat: number; lon: number };
    model_point_distance_km: number | null;
    timezone: string;
    replay_point: { lat: number; lon: number; label?: string } | null;
  };
  air_quality: {
    times: number[];
    interval_s: number;
    series: Record<string, Series>;
    current_index: number | null;
    source: AqSource;
  };
  current: {
    valid_from_utc: string;
    valid_to_utc: string;
    us_aqi: number | null;
    category: Category;
    dominant: { parameter: string; label: string; sub_index: number; averaging: string } | null;
    readings: Reading[];
  } | null;
  weather: {
    times: number[];
    series: Record<string, Series>;
    current: (Record<string, number | null> & { valid_from_utc: string; units: Record<string, string> }) | null;
    source: { provider: string; role: string; attribution: string; cache: CacheMeta };
  } | null;
  notes: string[];
}

export interface GridCell {
  id: string;
  lat: number;
  lon: number;
  bounds: [[number, number], [number, number]];
  status: "ok" | "unavailable";
  stale: boolean;
  reason?: string | null;
  retrieved_at: string | null;
  cache?: string | null;
  model_point: { lat: number; lon: number } | null;
  us_aqi: (number | null)[];
  pm2_5: (number | null)[];
}

export interface GridResponse extends Envelope {
  status: "ok" | "partial" | "error" | "zoom_in";
  stride?: number;
  cell_size_deg?: number;
  times: number[];
  cells: GridCell[];
  counts?: { cells: number; stale: number; unavailable: number };
  errors?: { provider: string; kind: string; message: string }[];
  message?: string;
}

export interface Observation {
  parameter: string;
  display_name: string;
  units: string | null;
  value: number;
  observed_at_utc: string;
  observed_at_local: string | null;
  age_minutes: number;
  sensor_id: number;
}

export interface Station {
  id: number;
  name: string | null;
  locality: string | null;
  lat: number;
  lon: number;
  distance_km: number;
  provider: string | null;
  owner: string | null;
  is_monitor: boolean | null;
  instruments: string[];
  licenses: { name: string | null; attribution: string | null }[];
  datetime_last_utc: string | null;
  latest_fetch_failed: boolean;
  observations: Observation[];
}

export interface StationsResponse extends Envelope {
  status: "ok" | "unavailable" | "no_active_stations";
  reason: string | null;
  stations: Station[];
  counts?: { locations_in_radius: number; inactive_omitted: number; shown: number };
  radius_km?: number;
  active_within_hours?: number;
  cache?: CacheMeta;
}

export interface GeoResult {
  name: string;
  lat: number;
  lon: number;
  country: string | null;
  country_code: string | null;
  admin1: string | null;
  timezone: string | null;
  population: number | null;
}

export interface PlanWindow {
  start_utc: string;
  end_utc: string;
  start_local: string;
  end_local: string;
  label: string;
  complete: boolean;
  missing_intervals_utc: string[];
  pm25_index: number | null;
  pm25_index_units: string;
  peak_aqi: number | null;
  peak_category: Category;
  meets_threshold: boolean;
  in_allowed_hours: boolean;
  starts_in_past: boolean;
  eligible: boolean;
}

export interface PlanResponse extends Envelope {
  status: "ok" | "no_eligible_window" | "no_complete_window" | "no_future_window";
  timezone: string;
  day: string;
  threshold_aqi: number;
  duration_min: number;
  counts: { candidates: number; in_past: number; incomplete: number; complete: number; eligible: number };
  best: PlanWindow | null;
  least_polluted_available: PlanWindow | null;
  alternatives: PlanWindow[];
  baseline: PlanWindow;
  comparison: {
    available: boolean;
    pct_change: number | null;
    abs_change: number | null;
    reason: string | null;
    chosen_is_eligible: boolean;
    same_window: boolean;
  };
  windows: PlanWindow[];
  explanations: string[];
  index_units: string;
  source: AqSource;
  notes: string[];
}

export interface PlanPrefs {
  duration_min: number;
  allowed_start: string;
  allowed_end: string;
  baseline_start: string;
  threshold_aqi: number;
  dayOffset: 0 | 1;
}

export interface SelectedLocation {
  lat: number;
  lon: number;
  name?: string;
  tz?: string | null;
}
