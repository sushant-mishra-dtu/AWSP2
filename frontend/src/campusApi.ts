import { request } from "./api";
import type { Category, Envelope, PlanWindow } from "./types";

export interface RuntimeInfo extends Envelope {
  data_mode: "live" | "replay";
  store: string;
  auth: "cognito" | "local-dev-signin";
  notifier: string;
  evidence: string;
  bedrock: string;
  ai_wording: { primary: string | null; fallback: string | null; always: string };
  cognito: { region: string; user_pool_id: string; client_id: string } | null;
  local_mode_notice: string | null;
}

export interface Org {
  org_id: string;
  name: string;
  lat: number;
  lon: number;
  location_label: string;
  timezone: string;
  threshold_aqi: number;
  is_demo: boolean;
  created_at: string;
  join_code?: string;
  owner_name?: string;
  role?: "owner" | "member";
}

export interface Activity {
  activity_id: string;
  name: string;
  kind: string;
  days: number[];
  start: string;
  duration_min: number;
  participants: number;
  location_note: string;
  alternatives: { start: string; end: string }[];
}

export interface Decision {
  type: string;
  at: string;
  by: string;
  details: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface Card {
  occurrence_id: string;
  date: string;
  activity: Omit<Activity, "days">;
  org: { org_id: string; name: string; timezone: string; location_label: string; lat: number; lon: number };
  planned: PlanWindow;
  status: "within_threshold" | "exceeds_with_alternative" | "exceeds_no_alternative" | "data_unavailable";
  exceeds: boolean | null;
  in_past: boolean;
  threshold_aqi: number;
  aqi_standard: string;
  planned_category: Category;
  alternative: PlanWindow | null;
  least_polluted: PlanWindow | null;
  comparison: { pct_change: number; abs_change: number; basis: string } | null;
  shorten_options: { duration_min: number; pm25_index: number; peak_aqi: number; pct_change: number; note: string }[];
  candidates: PlanWindow[];
  allowed_ranges: { start_utc: string; end_utc: string; label: string }[];
  guidance: { available: boolean; text: string; note?: string | null; source: { title: string; publisher: string; document: string; page_url: string; scope_note: string } };
  indoor_note: string;
  provenance: {
    source: string; model: string; data_type: string; valid_from_utc: string; valid_to_utc: string; retrieved_at: string | null;
    cache_status: string; stale: boolean; spatial_resolution: string; native_time_step: string; mode: string;
    replay_captured_at: string | null; replay_synthetic: boolean;
  };
  explanation: string[];
  planner_explanations: string[];
  decision: Decision | null;
  outcome: { outcome: string; at: string; by: string; note: string } | null;
  last_alert: { fingerprint: string; kind: string; alert_id: string; at: string } | null;
}

export interface AlertRec {
  alert_id: string;
  kind: string;
  created_at: string;
  trigger: string;
  activity_name: string | null;
  planned_label?: string;
  date?: string;
  planned_peak_aqi?: number;
  planned_category?: string;
  threshold_aqi?: number;
  alternative?: { label: string; peak_aqi: number; eligible: boolean } | null;
  subject: string;
  message: string;
  is_demo: boolean;
  notification: { status: string; attempts: number; message_id: string | null; last_error: string | null; published_at: string | null };
  acknowledged: { by: string; at: string; method: string } | null;
}

export interface Subscription {
  sub_id: string;
  email_masked: string;
  status: string;
  requested_at: string;
  checked_at: string | null;
  check_error?: string | null;
}

export interface Report {
  report_id: string;
  category: string;
  category_label: string;
  lat: number;
  lon: number;
  observed_at: string;
  description: string;
  status: string;
  submitted_by: string;
  submitted_at: string;
  verification: string;
  disclaimer: string;
  can_moderate: boolean;
  photo: { size: number; uploaded_at: string; note: string } | null;
  review: { label: string; by: string; at: string; note: string } | null;
  assignment: { label: string; assignee: string; by: string; at: string } | null;
  actions: { by: string; at: string; note: string }[];
  resolution: { by: string; at: string; note: string; caveat: string } | null;
  history: { status: string; by: string; at: string; note?: string }[];
}

export interface HistoryRec {
  sk: string;
  event: string;
  actor: string;
  at: string;
  details: Record<string, unknown>;
  data_mode: string;
}

export interface Bulletin {
  lang: "en" | "hi";
  deterministic: string;
  hindi_note: string | null;
  ai: { text: string; provider: string; model_id: string; label: string } | null;
  ai_status: string;
  ai_attempts: { provider: string; model: string; status: string }[];
}

export interface Impact extends Envelope {
  scope: string;
  counters: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  comparisons: {
    org: string; activity: string; date: string; type: string; original: string; new: string; baseline_index: number;
    new_index: number; pct_change: number | null; duration_changed: boolean; forecast_retrieved_at: string; data_mode: string; completed: boolean;
  }[];
  comparison_total: { count: number; baseline_index_sum: number; new_index_sum: number; pct_change: number | null } | null;
  labels: Record<string, string>;
}

export interface AssessSummary {
  assessed: number;
  alerts_created: number;
  duplicates_skipped: number;
  notifications: Record<string, number>;
  retried: number;
  errors: string[];
  forecast?: Record<string, unknown>;
}

export function campusApi(token: () => string | null) {
  const h = (extra?: Record<string, string>) => ({ ...(token() ? { Authorization: `Bearer ${token()}` } : {}), ...(extra ?? {}) });
  const get = <T,>(p: string) => request<T>(p, { headers: h() });
  const send = <T,>(p: string, method: string, body?: unknown) =>
    request<T>(p, { method, headers: h({ "Content-Type": "application/json" }), body: body === undefined ? undefined : JSON.stringify(body), timeoutMs: 40000 });
  const o = (id: string) => `/api/orgs/${encodeURIComponent(id)}`;
  return {
    runtime: () => request<RuntimeInfo>("/api/runtime"),
    localLogin: (name: string) => send<{ token: string; user: { name: string } }>("/api/auth/local-login", "POST", { name }),
    me: () => get<{ user: { name: string; email: string | null; method: string }; orgs: Org[] }>("/api/me"),
    createOrg: (b: Record<string, unknown>) => send<Org>("/api/orgs", "POST", b),
    patchOrg: (id: string, b: Record<string, unknown>) => send<Org>(o(id), "PATCH", b),
    getOrg: (id: string) => get<Org>(o(id)),
    join: (code: string) => send<Org>("/api/orgs/join", "POST", { code }),
    activities: (id: string) => get<{ activities: Activity[] }>(`${o(id)}/activities`),
    addActivity: (id: string, b: Record<string, unknown>) => send<Activity>(`${o(id)}/activities`, "POST", b),
    removeActivity: (id: string, aid: string) => send<{ ok: boolean }>(`${o(id)}/activities/${aid}`, "DELETE"),
    cards: (id: string) => get<Envelope & { cards: Card[]; forecast: Record<string, unknown> }>(`${o(id)}/cards`),
    assess: (id: string) => send<AssessSummary>(`${o(id)}/assess`, "POST"),
    action: (id: string, occ: string, b: Record<string, unknown>) => send<Record<string, unknown>>(`${o(id)}/occurrences/${occ}/actions`, "POST", b),
    bulletin: (id: string, occ: string, lang: "en" | "hi") => send<Bulletin>(`${o(id)}/occurrences/${occ}/bulletin`, "POST", { lang }),
    alerts: (id: string) => get<{ alerts: AlertRec[]; notifier: string }>(`${o(id)}/alerts`),
    ack: (id: string, aid: string) => send<AlertRec>(`${o(id)}/alerts/${aid}/ack`, "POST"),
    subs: (id: string, refresh = false) => get<{ subscriptions: Subscription[]; notifier: string; can_send: boolean }>(`${o(id)}/subscriptions${refresh ? "?refresh=true" : ""}`),
    addSub: (id: string, email: string) => send<Subscription>(`${o(id)}/subscriptions`, "POST", { email }),
    removeSub: (id: string, sid: string) => send<{ ok: boolean }>(`${o(id)}/subscriptions/${sid}`, "DELETE"),
    testNotification: (id: string) => send<AlertRec>(`${o(id)}/notifications/test`, "POST"),
    history: (id: string) => get<{ history: HistoryRec[] }>(`${o(id)}/history`),
    reports: (id: string) => get<{ reports: Report[] }>(`${o(id)}/reports`),
    addReport: (id: string, b: Record<string, unknown>) => send<Report>(`${o(id)}/reports`, "POST", b),
    transition: (id: string, rid: string, b: Record<string, unknown>) => send<Report>(`${o(id)}/reports/${rid}/transition`, "POST", b),
    photoUpload: (id: string, rid: string, content_type: string, size: number) =>
      send<{ method: "POST" | "PUT"; url: string; fields?: Record<string, string>; headers?: Record<string, string> }>(`${o(id)}/reports/${rid}/photo-upload`, "POST", { content_type, size }),
    photoConfirm: (id: string, rid: string) => send<Report>(`${o(id)}/reports/${rid}/photo-confirm`, "POST"),
    photoUrl: (id: string, rid: string) => get<{ url: string }>(`${o(id)}/reports/${rid}/photo-url`),
    impact: (scope: string) => request<Impact>(`/api/impact?scope=${scope}`),
  };
}

export type CampusApi = ReturnType<typeof campusApi>;

/** Upload a photo to the target the API issued (S3 presigned POST on AWS, signed PUT locally). */
export async function uploadPhoto(target: { method: "POST" | "PUT"; url: string; fields?: Record<string, string>; headers?: Record<string, string> }, file: File) {
  let res: Response;
  if (target.method === "POST") {
    const fd = new FormData();
    Object.entries(target.fields ?? {}).forEach(([k, v]) => fd.append(k, v));
    fd.append("file", file);
    res = await fetch(target.url, { method: "POST", body: fd });
  } else {
    res = await fetch(target.url, { method: "PUT", body: file, headers: target.headers });
  }
  if (!res.ok) throw new Error(`Upload rejected (${res.status})`);
}
