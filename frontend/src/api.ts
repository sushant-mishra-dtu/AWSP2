import type { GeoResult, GridResponse, Health, PlanPrefs, PlanResponse, PointResponse, StationsResponse } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  status: number;
  kind?: string;
  constructor(message: string, status: number, kind?: string) {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

export async function request<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const ctl = new AbortController();
  const timeout = setTimeout(() => ctl.abort(new DOMException("timeout", "TimeoutError")), init?.timeoutMs ?? 25000);
  const outer = init?.signal;
  const onAbort = () => ctl.abort(outer?.reason);
  outer?.addEventListener("abort", onAbort);
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, signal: ctl.signal, headers: { Accept: "application/json", ...(init?.headers ?? {}) } });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON body */
    }
    if (!res.ok) {
      const err = (body as { error?: { message?: string; kind?: string }; detail?: unknown } | null) ?? null;
      const msg =
        err?.error?.message ??
        (typeof err?.detail === "string" ? err.detail : undefined) ??
        (Array.isArray(err?.detail) ? "Invalid request" : undefined) ??
        `Request failed (${res.status})`;
      throw new ApiError(msg, res.status, err?.error?.kind);
    }
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error)?.name === "AbortError" && outer?.aborted) throw e;
    throw new ApiError(ctl.signal.aborted ? "The request timed out." : "Network error — the API could not be reached.", 0, "network");
  } finally {
    clearTimeout(timeout);
    outer?.removeEventListener("abort", onAbort);
  }
}

export const api = {
  health: () => request<Health>("/api/health"),
  geocode: (q: string, signal?: AbortSignal) => request<{ results: GeoResult[] }>(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }),
  point: (lat: number, lon: number, tz?: string | null, signal?: AbortSignal) =>
    request<PointResponse>(`/api/point?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}${tz ? `&tz=${encodeURIComponent(tz)}` : ""}`, { signal }),
  grid: (b: { south: number; west: number; north: number; east: number }, signal?: AbortSignal) =>
    request<GridResponse>(
      `/api/grid?south=${b.south.toFixed(3)}&west=${b.west.toFixed(3)}&north=${b.north.toFixed(3)}&east=${b.east.toFixed(3)}`,
      { signal },
    ),
  stations: (lat: number, lon: number, signal?: AbortSignal) =>
    request<StationsResponse>(`/api/stations?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}&radius_km=25`, { signal }),
  plan: (body: { lat: number; lon: number; tz?: string | null; day: string } & Omit<PlanPrefs, "dayOffset">, signal?: AbortSignal) =>
    request<PlanResponse>("/api/plan", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      signal,
    }),
};
