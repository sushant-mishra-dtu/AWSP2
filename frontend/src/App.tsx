import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import Evidence from "./components/Evidence";
import ForecastChart from "./components/ForecastChart";
import LocationPanel from "./components/LocationPanel";
import { Legend, TimeSlider } from "./components/MapOverlays";
import MapView, { type Bounds } from "./components/MapView";
import Planner from "./components/Planner";
import SearchBox, { DEMO_PLACES } from "./components/SearchBox";
import StationsPanel from "./components/StationsPanel";
import CampusWorkspace from "./components/campus/CampusWorkspace";
import ImpactPanel from "./components/campus/ImpactPanel";
import { campusApi, type RuntimeInfo } from "./campusApi";
import { useDebounced, useLocalState, useMediaQuery } from "./hooks";
import type { GridResponse, Health, PlanPrefs, PlanResponse, PointResponse, SelectedLocation, StationsResponse } from "./types";
import { addDays, isoToEpoch, localDate, parseHm } from "./time";

const DEFAULT_PREFS: PlanPrefs = {
  duration_min: 60,
  allowed_start: "07:00",
  allowed_end: "17:00",
  baseline_start: "07:30",
  threshold_aqi: 100,
  dayOffset: 1,
};
const DEFAULT_LOC: SelectedLocation = DEMO_PLACES[0];
const CELL = 0.4;

function isPrefs(v: unknown): v is PlanPrefs {
  const p = v as PlanPrefs;
  return !!p && typeof p.duration_min === "number" && typeof p.allowed_start === "string" && typeof p.baseline_start === "string" && typeof p.threshold_aqi === "number" && (p.dayOffset === 0 || p.dayOffset === 1);
}
function isLoc(v: unknown): v is SelectedLocation {
  const l = v as SelectedLocation;
  return !!l && typeof l.lat === "number" && typeof l.lon === "number" && Math.abs(l.lat) <= 90 && Math.abs(l.lon) <= 180;
}
function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Unexpected error";
}

export default function App() {
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [selected, setSelected] = useLocalState<SelectedLocation>("airwindow.location.v1", DEFAULT_LOC, isLoc);
  const [prefs, setPrefs] = useLocalState<PlanPrefs>("airwindow.prefs.v1", DEFAULT_PREFS, isPrefs);
  const [flyTo, setFlyTo] = useState<{ lat: number; lon: number; zoom?: number; seq: number } | null>(null);
  const [locating, setLocating] = useState(false);

  const [point, setPoint] = useState<PointResponse | null>(null);
  const [pointLoading, setPointLoading] = useState(false);
  const [pointError, setPointError] = useState<string | null>(null);
  const [pointSeq, setPointSeq] = useState(0);

  const [grid, setGrid] = useState<GridResponse | null>(null);
  const [gridLoading, setGridLoading] = useState(false);
  const [gridError, setGridError] = useState<string | null>(null);
  const gridKey = useRef("");
  const gridCtl = useRef<AbortController | null>(null);
  const [zoom, setZoom] = useState(9);
  const [showCells, setShowCells] = useState(true);
  const [legendOpen, setLegendOpen] = useState(true);

  const [showStations, setShowStations] = useState(false);
  const [view, setView] = useLocalState<"explore" | "campus" | "impact">("airwindow.view.v1", "explore", (v): v is "explore" | "campus" | "impact" => v === "explore" || v === "campus" || v === "impact");
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [markers, setMarkers] = useState<{ lat: number; lon: number; label: string; kind: "campus" | "report" }[]>([]);
  useEffect(() => {
    campusApi(() => null).runtime().then(setRuntime).catch(() => setRuntime(null));
  }, []);
  const focusMap = useCallback((lat: number, lon: number) => setFlyTo({ lat, lon, zoom: 10, seq: Date.now() }), []);
  const [stations, setStations] = useState<StationsResponse | null>(null);
  const [stationsLoading, setStationsLoading] = useState(false);
  const [stationsError, setStationsError] = useState<string | null>(null);

  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  // ---------------------------------------------------------------- health / clock
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .health()
        .then((h) => {
          if (!alive) return;
          setHealth(h);
          setHealthError(null);
        })
        .catch((e) => alive && setHealthError(errMsg(e)));
    load();
    const id = setInterval(load, 10 * 60 * 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const nowEpoch = health ? isoToEpoch(health.server_now_utc) : Math.floor(Date.now() / 1000);
  const h0 = Math.floor(nowEpoch / 3600) * 3600;
  const timeline = useMemo(() => Array.from({ length: 49 }, (_, k) => h0 - 3600 + k * 3600), [h0]);
  const nowIndex = 1;
  const [timeIndex, setTimeIndex] = useState(nowIndex);
  const selectedTime = timeline[Math.min(timeIndex, timeline.length - 1)];
  const tz = point?.location.timezone ?? selected.tz ?? "UTC";

  // ---------------------------------------------------------------- selected point
  useEffect(() => {
    const ctl = new AbortController();
    setPointLoading(true);
    setPointError(null);
    setPoint((prev) => (prev && prev.location.requested.lat === selected.lat && prev.location.requested.lon === selected.lon ? prev : null));
    api
      .point(selected.lat, selected.lon, selected.tz, ctl.signal)
      .then((p) => setPoint(p))
      .catch((e) => {
        if (ctl.signal.aborted) return;
        setPointError(errMsg(e));
      })
      .finally(() => !ctl.signal.aborted && setPointLoading(false));
    return () => ctl.abort();
  }, [selected.lat, selected.lon, selected.tz, pointSeq]);

  const select = useCallback(
    (loc: SelectedLocation, fly?: boolean) => {
      setSelected(loc);
      setPlan(null);
      if (fly) setFlyTo({ lat: loc.lat, lon: loc.lon, zoom: 9, seq: Date.now() });
    },
    [setSelected],
  );

  // ---------------------------------------------------------------- grid (bounded, debounced in MapView)
  const onBounds = useCallback((b: Bounds) => {
    const key = [Math.floor(b.south / CELL), Math.floor(b.west / CELL), Math.ceil(b.north / CELL), Math.ceil(b.east / CELL)].join(",");
    if (key === gridKey.current) return;
    gridKey.current = key;
    gridCtl.current?.abort();
    const ctl = new AbortController();
    gridCtl.current = ctl;
    setGridLoading(true);
    api
      .grid(b, ctl.signal)
      .then((g) => {
        setGrid(g);
        setGridError(null);
      })
      .catch((e) => {
        if (ctl.signal.aborted) return;
        gridKey.current = "";
        setGridError(errMsg(e));
      })
      .finally(() => !ctl.signal.aborted && setGridLoading(false));
  }, []);
  const gridIdx = grid ? grid.times.indexOf(selectedTime) : -1;

  // ---------------------------------------------------------------- stations
  useEffect(() => {
    if (!showStations) return;
    const ctl = new AbortController();
    setStationsLoading(true);
    setStationsError(null);
    api
      .stations(selected.lat, selected.lon, ctl.signal)
      .then(setStations)
      .catch((e) => !ctl.signal.aborted && setStationsError(errMsg(e)))
      .finally(() => !ctl.signal.aborted && setStationsLoading(false));
    return () => ctl.abort();
  }, [showStations, selected.lat, selected.lon]);

  // ---------------------------------------------------------------- plan
  const planReq = useMemo(() => {
    if (!point) return null;
    const ptz = point.location.timezone;
    const day = addDays(localDate(isoToEpoch(point.server_now_utc), ptz), prefs.dayOffset);
    const s = parseHm(prefs.allowed_start);
    const e = parseHm(prefs.allowed_end);
    const b = parseHm(prefs.baseline_start);
    if (e <= s || e - s < prefs.duration_min || b + prefs.duration_min > 1440) return null;
    const { dayOffset: _d, ...rest } = prefs;
    void _d;
    return { lat: selected.lat, lon: selected.lon, tz: ptz, day, ...rest };
  }, [point, prefs, selected.lat, selected.lon]);
  const debouncedReq = useDebounced(planReq, 350);
  const reqKey = JSON.stringify(debouncedReq);

  useEffect(() => {
    if (!debouncedReq) return;
    const ctl = new AbortController();
    setPlanLoading(true);
    setPlanError(null);
    api
      .plan(debouncedReq, ctl.signal)
      .then(setPlan)
      .catch((e) => {
        if (ctl.signal.aborted) return;
        setPlanError(errMsg(e));
      })
      .finally(() => !ctl.signal.aborted && setPlanLoading(false));
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqKey]);

  // Keep the chart consistent with the plan: if the plan used a newer
  // forecast retrieval than the chart, refresh the chart.
  useEffect(() => {
    const a = plan?.source.cache?.retrieved_at;
    const b = point?.air_quality.source.cache?.retrieved_at;
    if (a && b && a !== b && plan?.source.cache?.status === "miss") setPointSeq((s) => s + 1);
  }, [plan, point]);

  // ---------------------------------------------------------------- geolocation
  function locate() {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        select({ lat: pos.coords.latitude, lon: pos.coords.longitude, name: "My location", tz: null }, true);
      },
      () => setLocating(false),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  }

  // ---------------------------------------------------------------- render
  const mode = health?.mode;
  const header = (
    <header className="flex items-center justify-between gap-3 border-b border-line bg-white px-4 py-3">
      <div className="flex items-center gap-2.5">
        <svg viewBox="0 0 32 32" className="h-8 w-8 shrink-0" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#0f172a" />
          <rect x="7" y="7" width="8" height="8" rx="1.5" fill="#00e400" />
          <rect x="17" y="7" width="8" height="8" rx="1.5" fill="#ffff00" />
          <rect x="7" y="17" width="8" height="8" rx="1.5" fill="#ff7e00" />
          <rect x="17" y="17" width="8" height="8" rx="1.5" fill="#ff0000" />
        </svg>
        <div>
          <h1 className="text-[17px] font-bold leading-tight tracking-tight text-ink">AirWindow</h1>
          <p className="text-[11px] leading-tight text-muted">Find a lower-pollution time for outdoor activities</p>
        </div>
      </div>
      {healthError ? (
        <span className="rounded-full bg-red-100 px-2.5 py-1 text-[11px] font-semibold text-red-800">API unreachable</span>
      ) : mode === "replay" ? (
        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-900" title={health?.replay?.description}>
          REPLAY · captured {health?.replay?.captured_at?.replace("T", " ").replace("Z", " UTC")}
          {health?.replay?.synthetic ? " · SYNTHETIC" : ""}
        </span>
      ) : runtime?.local_mode_notice ? (
        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-300" title={runtime.local_mode_notice}>
          LIVE DATA · LOCAL MODE
        </span>
      ) : mode === "live" ? (
        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-800 ring-1 ring-emerald-200">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> LIVE DATA
        </span>
      ) : null}
    </header>
  );

  const panels = (
    <div className="space-y-3 p-3 lg:p-4">
      <LocationPanel
        selected={selected}
        point={point}
        loading={pointLoading}
        error={pointError}
        selectedTime={selectedTime}
        onRetry={() => setPointSeq((s) => s + 1)}
      />
      {point && (
        <section className="rounded-xl border border-line bg-white p-4 shadow-sm" aria-labelledby="fc-h">
          <h2 id="fc-h" className="mb-2 text-base font-semibold text-ink">
            Next 48 hours <span className="text-xs font-normal text-muted">modelled forecast · {tz}</span>
          </h2>
          <ForecastChart
            point={point}
            selectedTime={selectedTime}
            plan={plan}
            onSelectTime={(t) => {
              const i = timeline.indexOf(t);
              if (i >= 0) setTimeIndex(i);
            }}
          />
        </section>
      )}
      {point && (
        <Planner prefs={prefs} setPrefs={setPrefs} tz={tz} nowEpoch={isoToEpoch(point.server_now_utc)} plan={plan} loading={planLoading} error={planError} />
      )}
      <StationsPanel enabled={showStations} onToggle={setShowStations} data={stations} loading={stationsLoading} error={stationsError} />
      <Evidence source={health?.aq_source ?? null} point={point} />
      <footer className="px-1 pb-4 text-[11px] leading-relaxed text-muted">
        Air quality: Open-Meteo (CC BY 4.0) using Copernicus Atmosphere Monitoring Service (CAMS) forecasts. Observations: OpenAQ and original
        station operators. Map © OpenStreetMap contributors. Not medical advice; follow official advisories. Built for WeMakeDevs × AWS
        Environmental Hacks.
      </footer>
    </div>
  );

  const zoomNote =
    grid?.status === "zoom_in"
      ? "Zoom in to load model sample cells for this area."
      : zoom >= 11
        ? "Street-level zoom: this whole view lies inside one ~45 km model cell. The model cannot show differences between streets or schools."
        : null;

  const map = (
    <div className="relative h-full w-full">
      <MapView
        initialCenter={[selected.lat, selected.lon]}
        initialZoom={9}
        cells={grid?.cells ?? []}
        times={grid?.times ?? timeline}
        timeIndex={gridIdx}
        tz={tz}
        showCells={showCells}
        stations={stations?.stations ?? []}
        showStations={showStations}
        selected={selected}
        flyTo={flyTo}
        onBounds={onBounds}
        onZoom={setZoom}
        wheelZoom={isDesktop}
        extraMarkers={view === "campus" ? markers : []}
        onSelect={(lat, lon) => select({ lat, lon, tz: null })}
      />
      <div className="pointer-events-none absolute inset-x-2 top-2 z-[500] flex flex-wrap items-start gap-2 pr-12">
        <div className="pointer-events-auto flex overflow-hidden rounded-lg border border-line bg-white/95 text-xs shadow-md backdrop-blur">
          <button type="button" aria-pressed={showCells} onClick={() => setShowCells((v) => !v)} className={`px-2.5 py-1.5 font-medium ${showCells ? "bg-ink text-white" : "text-ink-soft"}`}>
            Model cells
          </button>
          <button type="button" aria-pressed={showStations} onClick={() => setShowStations((v) => !v)} className={`border-l border-line px-2.5 py-1.5 font-medium ${showStations ? "bg-ink text-white" : "text-ink-soft"}`}>
            Stations
          </button>
        </div>
        {gridLoading && <span className="rounded-lg bg-white/95 px-2.5 py-1.5 text-xs text-ink-soft shadow-md">Loading model cells…</span>}
        {!gridLoading && grid && grid.status !== "zoom_in" && (
          <span className="rounded-lg bg-white/95 px-2.5 py-1.5 text-xs text-ink-soft shadow-md">
            {grid.counts?.cells} cells{grid.stride && grid.stride > 1 ? ` · every ${grid.stride}${grid.stride === 2 ? "nd" : grid.stride === 3 ? "rd" : "th"} cell shown` : ""}
            {grid.counts?.stale ? ` · ${grid.counts.stale} stale` : ""}
            {grid.counts?.unavailable ? ` · ${grid.counts.unavailable} unavailable` : ""}
          </span>
        )}
        {gridError && (
          <span className="pointer-events-auto rounded-lg bg-red-50 px-2.5 py-1.5 text-xs text-red-800 shadow-md" role="alert">
            Model layer unavailable: {gridError}
          </span>
        )}
        {grid?.errors?.length ? (
          <span className="rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900 shadow-md">Provider: {grid.errors[0].message}</span>
        ) : null}
        {showStations && stations && stations.status !== "ok" && (
          <span className="rounded-lg bg-white/95 px-2.5 py-1.5 text-xs text-ink-soft shadow-md">Stations: {stations.reason}</span>
        )}
      </div>
      {zoomNote && (
        <div className="pointer-events-none absolute inset-x-2 top-12 z-[500] flex justify-center">
          <p className="max-w-md rounded-lg bg-ink/90 px-3 py-2 text-center text-xs text-white shadow-lg">{zoomNote}</p>
        </div>
      )}
      <div className={`pointer-events-none absolute inset-x-2 bottom-8 z-[500] flex gap-2 ${isDesktop ? "flex-row items-end" : "flex-col items-stretch"}`}>
        <div className="pointer-events-auto">
          {isDesktop && legendOpen ? (
            <div className="relative">
              <Legend />
              <button type="button" onClick={() => setLegendOpen(false)} className="absolute right-2 top-2 text-xs text-muted hover:text-ink" aria-label="Collapse legend">
                –
              </button>
            </div>
          ) : (
            <div className="relative max-w-[26rem]">
              <Legend compact />
              {isDesktop && (
                <button type="button" onClick={() => setLegendOpen(true)} className="absolute right-1.5 top-1 text-[10px] font-medium text-accent" aria-label="Expand legend">
                  expand
                </button>
              )}
            </div>
          )}
        </div>
        <div className={isDesktop ? "max-w-lg flex-1" : "w-full"}>
          <TimeSlider times={timeline} index={timeIndex} nowIndex={nowIndex} tz={tz} onChange={setTimeIndex} onStep={(d) => setTimeIndex((i) => Math.min(timeline.length - 1, Math.max(0, i + d)))} />
        </div>
      </div>
    </div>
  );

  const tabs = (
    <nav className="grid grid-cols-3 gap-1 border-b border-line bg-white px-4 pb-2 text-xs" aria-label="Sections">
      {([["explore", "Explore map"], ["campus", "My campus"], ["impact", "Impact"]] as const).map(([v, l]) => (
        <button key={v} aria-pressed={view === v} onClick={() => setView(v)}
          className={`rounded-md px-2 py-1.5 font-semibold ${view === v ? "bg-ink text-white" : "text-ink-soft hover:bg-slate-100"}`}>
          {l}
        </button>
      ))}
    </nav>
  );
  const content =
    view === "campus" ? (
      <CampusWorkspace runtime={runtime} selected={selected} selectedTz={point?.location.timezone ?? selected.tz ?? null} onMarkers={setMarkers} onFocus={focusMap} />
    ) : view === "impact" ? (
      <ImpactPanel />
    ) : (
      panels
    );

  const search = (
    <div className="border-b border-line bg-white px-4 py-3">
      <SearchBox
        locating={locating}
        onLocate={locate}
        onPick={(r) => select({ lat: r.lat, lon: r.lon, name: r.name, tz: r.tz }, true)}
      />
    </div>
  );

  if (isDesktop) {
    return (
      <div className="flex h-dvh">
        <aside className="flex w-[440px] shrink-0 flex-col border-r border-line bg-canvas">
          {header}
          {search}
          {tabs}
          <div className="flex-1 overflow-y-auto">{content}</div>
        </aside>
        <main className="relative flex-1">{map}</main>
      </div>
    );
  }
  return (
    <div className="min-h-dvh bg-canvas">
      {header}
      {search}
      {tabs}
      <main className="relative h-[58vh] min-h-[360px]">{map}</main>
      {content}
    </div>
  );
}
