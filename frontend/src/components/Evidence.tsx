import type { AqSource, PointResponse } from "../types";

export default function Evidence({ source, point }: { source: AqSource | null; point: PointResponse | null }) {
  const s = point?.air_quality.source ?? source;
  if (!s) return null;
  const rows: [string, string][] = [
    ["Provider", s.provider],
    ["Model", s.model],
    ["Data type", "Modelled forecast (not a local measurement)"],
    ["AQI", s.aqi_standard],
    ["AQI averaging", s.aqi_averaging],
    ["Spatial resolution", `${s.spatial_resolution} — nearby points share one model value`],
    ["Time step", s.native_time_step],
    ["Updates", s.update_frequency],
  ];
  if (point) {
    const c = point.air_quality.source.cache;
    rows.push(["Retrieved", `${c?.retrieved_at ?? "—"} (${c?.status === "hit" ? "cache" : c?.status ?? "—"}${c?.stale ? ", STALE" : ""})`]);
    rows.push(["Model grid point", `${point.location.model_point.lat}°, ${point.location.model_point.lon}°`]);
    rows.push(["Display timezone", point.location.timezone]);
    if (point.weather) rows.push(["Weather", `${point.weather.source.provider} — ${point.weather.source.role}`]);
  }
  return (
    <details className="rounded-xl border border-line bg-white p-4 shadow-sm">
      <summary className="cursor-pointer text-base font-semibold text-ink">Evidence &amp; limitations</summary>
      <dl className="mt-3 grid grid-cols-[8.5rem_1fr] gap-x-3 gap-y-1.5 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="font-medium text-muted">{k}</dt>
            <dd className="break-words text-ink-soft">{v}</dd>
          </div>
        ))}
      </dl>
      <h3 className="mt-4 text-xs font-semibold text-ink">Limitations</h3>
      <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-ink-soft">
        <li>CAMS Global is ~45 km resolution. It cannot show street-, school- or neighbourhood-level differences, and values can jump at cell edges.</li>
        <li>US AQI is calculated by Open-Meteo from modelled concentrations. It is not an official CPCB/NAQI or EPA reading.</li>
        <li>PM2.5/PM10 sub-indices use 24-hour rolling averages, so hourly AQI changes slowly; the planner ranks windows on hourly PM2.5.</li>
        <li>The PM2.5 pollution-time index is a comparative planning number, not inhaled dose or a health-risk estimate.</li>
        <li>Rescheduling changes when people are outdoors; it does not reduce ambient pollution.</li>
        <li>Weather is shown as context only and is not used to explain or modify pollution values.</li>
        <li>Forecasts can be wrong. Follow official advisories and school health policies.</li>
      </ul>
      <p className="mt-3 text-[11px] text-muted">{s.attribution}</p>
    </details>
  );
}
