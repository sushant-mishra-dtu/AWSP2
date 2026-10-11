import { classifyUsAqi } from "../aqi";
import type { PointResponse, SelectedLocation } from "../types";
import { ageText, isoToEpoch, localDateTime, localTime, tzAbbrev } from "../time";

const POLLUTANTS: [string, string][] = [
  ["pm2_5", "PM2.5"],
  ["pm10", "PM10"],
  ["nitrogen_dioxide", "NO₂"],
  ["ozone", "O₃"],
  ["sulphur_dioxide", "SO₂"],
  ["carbon_monoxide", "CO"],
];

function compass(deg: number | null | undefined): string {
  if (deg == null) return "";
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return dirs[Math.round(deg / 45) % 8];
}

interface Props {
  selected: SelectedLocation;
  point: PointResponse | null;
  loading: boolean;
  error: string | null;
  selectedTime: number;
  onRetry: () => void;
}

export function AqiBadge({ value, size = "md" }: { value: number | null | undefined; size?: "sm" | "md" | "lg" }) {
  const c = classifyUsAqi(value);
  const pad = size === "lg" ? "px-3 py-2" : size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md font-semibold ${pad}`} style={{ background: c.color, color: c.textColor }}>
      {size === "lg" ? (
        <>
          <span className="text-3xl leading-none tabular-nums">{c.aqi ?? "—"}</span>
          <span className="text-sm leading-tight">{c.label}</span>
        </>
      ) : (
        <>
          <span className="tabular-nums">{c.aqi ?? "—"}</span>
          <span className="font-medium">{c.short}</span>
        </>
      )}
    </span>
  );
}

export default function LocationPanel({ selected, point, loading, error, selectedTime, onRetry }: Props) {
  const title = selected.name ?? `${selected.lat.toFixed(4)}°, ${selected.lon.toFixed(4)}°`;

  if (error && !point) {
    return (
      <section className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm" role="alert">
        <h2 className="font-semibold text-red-900">{title}</h2>
        <p className="mt-1 text-red-800">Pollution data is unavailable: {error}</p>
        <p className="mt-1 text-red-800/80">No simulated or placeholder values are shown.</p>
        <button type="button" onClick={onRetry} className="mt-2 rounded-md bg-red-700 px-3 py-1 text-xs font-semibold text-white hover:bg-red-800">
          Retry
        </button>
      </section>
    );
  }
  if (!point) {
    return (
      <section className="animate-pulse rounded-xl border border-line bg-white p-4" aria-busy="true">
        <div className="h-4 w-2/3 rounded bg-slate-200" />
        <div className="mt-3 h-12 w-1/2 rounded bg-slate-200" />
        <div className="mt-3 h-16 rounded bg-slate-100" />
        <span className="sr-only">Loading pollution data</span>
      </section>
    );
  }

  const tz = point.location.timezone;
  const aq = point.air_quality;
  const idx = aq.times.indexOf(selectedTime);
  const i = idx >= 0 ? idx : (aq.current_index ?? -1);
  const t = aq.times[i];
  const aqi = i >= 0 ? aq.series.us_aqi.values[i] : null;
  const cls = classifyUsAqi(aqi);
  const cache = aq.source.cache;
  const nowEpoch = isoToEpoch(point.server_now_utc);
  const mp = point.location.model_point;
  const wxIdx = point.weather ? point.weather.times.indexOf(t) : -1;
  const wx = (k: string) => (point.weather && wxIdx >= 0 ? point.weather.series[k]?.values[wxIdx] : null);

  // Highest sub-index at the selected hour.
  const subs: [string, string, string][] = [
    ["us_aqi_pm2_5", "PM2.5", "24-h rolling avg"],
    ["us_aqi_pm10", "PM10", "24-h rolling avg"],
    ["us_aqi_nitrogen_dioxide", "NO₂", "1-h"],
    ["us_aqi_ozone", "O₃", "max 1-h/8-h"],
    ["us_aqi_sulphur_dioxide", "SO₂", "max 1-h/24-h"],
    ["us_aqi_carbon_monoxide", "CO", "8-h avg"],
  ];
  let dom: { label: string; v: number; avg: string } | null = null;
  for (const [k, label, avg] of subs) {
    const v = i >= 0 ? aq.series[k]?.values[i] : null;
    if (v != null && (!dom || v > dom.v)) dom = { label, v, avg };
  }

  return (
    <section className={`rounded-xl border border-line bg-white p-4 shadow-sm ${loading ? "opacity-60" : ""}`} aria-live="polite">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-ink" title={title}>
            {title}
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            {selected.lat.toFixed(4)}°, {selected.lon.toFixed(4)}° · {tz} ({t ? tzAbbrev(t, tz) : ""})
          </p>
        </div>
        {cache?.stale && (
          <span className="shrink-0 rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">STALE</span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <AqiBadge value={aqi} size="lg" />
        <div className="text-xs leading-snug text-ink-soft">
          <div className="font-medium text-ink">Modelled US AQI (provider-calculated)</div>
          {t != null && (
            <div>
              {localDateTime(t, tz)}–{localTime(t + 3600, tz)} {tzAbbrev(t, tz)}
            </div>
          )}
          {dom && (
            <div>
              Highest sub-index: <b>{dom.label}</b> ({dom.avg})
            </div>
          )}
        </div>
      </div>
      {cls.key === "beyond" && (
        <p className="mt-2 rounded-md bg-slate-100 px-2 py-1 text-xs text-ink-soft">
          The provider value exceeds the 0–500 US AQI scale; it is shown as “Beyond AQI”, not capped.
        </p>
      )}

      <dl className="mt-3 grid grid-cols-3 gap-2">
        {POLLUTANTS.map(([k, label]) => {
          const s = aq.series[k];
          const v = i >= 0 ? s?.values[i] : null;
          return (
            <div key={k} className="rounded-lg bg-canvas px-2 py-1.5">
              <dt className="text-[11px] font-medium text-muted">{label}</dt>
              <dd className="text-sm font-semibold tabular-nums text-ink">
                {v == null ? "—" : v >= 100 ? Math.round(v) : v.toFixed(1)}
                <span className="ml-0.5 text-[10px] font-normal text-muted">{s?.units ?? ""}</span>
              </dd>
            </div>
          );
        })}
      </dl>

      {point.weather ? (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft" aria-label="Weather context">
          <span className="font-medium text-muted">Weather context:</span>
          <span>{wx("temperature_2m") ?? "—"} °C</span>
          <span>RH {wx("relative_humidity_2m") ?? "—"}%</span>
          <span>
            Wind {wx("wind_speed_10m") ?? "—"} km/h {compass(wx("wind_direction_10m"))}
          </span>
          <span>Precip. {wx("precipitation") ?? "—"} mm</span>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">Weather context unavailable.</p>
      )}

      <div className="mt-3 rounded-lg border border-dashed border-line px-2.5 py-2 text-[11px] leading-relaxed text-ink-soft">
        <div>
          <b>Data quality:</b> model forecast · resolution {aq.source.spatial_resolution} · native step 3-hourly ·
          model grid point {mp.lat?.toFixed(2)}°, {mp.lon?.toFixed(2)}°
          {point.location.model_point_distance_km != null && <> ({point.location.model_point_distance_km} km from your point)</>}
        </div>
        <div>
          Retrieved {cache?.retrieved_at ? ageText(cache.retrieved_at, nowEpoch) : "—"}
          {cache?.status === "hit" && " (from cache)"}
          {cache?.status === "replay" && " (replay capture)"}
          {point.location.replay_point && <> · replay point: {point.location.replay_point.label}</>}
        </div>
      </div>
      {point.notes.map((n) => (
        <p key={n} className="mt-2 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-900">
          {n}
        </p>
      ))}
    </section>
  );
}
