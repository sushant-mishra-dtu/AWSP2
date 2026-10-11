import type { StationsResponse } from "../types";

interface Props {
  enabled: boolean;
  onToggle: (v: boolean) => void;
  data: StationsResponse | null;
  loading: boolean;
  error: string | null;
}

function ageLabel(mins: number): string {
  if (mins < 60) return `${mins} min old`;
  const h = Math.floor(mins / 60);
  return h < 48 ? `${h} h ${mins % 60} min old` : `${Math.floor(h / 24)} days old`;
}

export default function StationsPanel({ enabled, onToggle, data, loading, error }: Props) {
  return (
    <section aria-labelledby="stations-h" className="rounded-xl border border-line bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 id="stations-h" className="text-base font-semibold text-ink">
          Observed stations <span className="text-xs font-normal text-muted">OpenAQ v3</span>
        </h2>
        <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-ink-soft">
          <input type="checkbox" className="h-4 w-4 accent-cyan-700" checked={enabled} onChange={(e) => onToggle(e.target.checked)} />
          Show layer
        </label>
      </div>
      <p className="mt-0.5 text-xs text-muted">
        Raw measurements from nearby monitors (within 25 km). Kept separate from the model and not converted to AQI.
      </p>
      {enabled && loading && <p className="mt-2 text-xs text-muted">Loading stations…</p>}
      {enabled && error && <p className="mt-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-800">{error}</p>}
      {enabled && data && data.status !== "ok" && (
        <p className="mt-2 rounded-md bg-slate-100 px-2 py-1.5 text-xs text-ink-soft" role="status">
          {data.reason}
        </p>
      )}
      {enabled && data?.status === "ok" && (
        <>
          <p className="mt-2 text-[11px] text-muted">
            Showing {data.counts?.shown} active station(s); {data.counts?.inactive_omitted} omitted (no report in {data.active_within_hours} h).
          </p>
          <ul className="mt-2 space-y-2">
            {data.stations.map((s) => (
              <li key={s.id} className="rounded-lg bg-canvas px-3 py-2 text-xs">
                <div className="flex justify-between gap-2">
                  <span className="font-semibold text-ink">{s.name ?? `Location ${s.id}`}</span>
                  <span className="shrink-0 tabular-nums text-muted">{s.distance_km} km</span>
                </div>
                <div className="text-muted">
                  {s.provider}
                  {s.owner && s.owner !== s.provider ? ` · ${s.owner}` : ""}
                  {s.is_monitor ? " · reference monitor" : ""}
                </div>
                {s.observations.length ? (
                  <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
                    {s.observations.slice(0, 6).map((o) => (
                      <li key={o.sensor_id} className="tabular-nums">
                        <b>{o.display_name}</b> {o.value} {o.units} <span className="text-muted">· {ageLabel(o.age_minutes)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="mt-1 text-muted">{s.latest_fetch_failed ? "Latest values could not be fetched." : "No recent values."}</div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
