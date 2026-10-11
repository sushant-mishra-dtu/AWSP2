import type { PlanPrefs, PlanResponse, PlanWindow } from "../types";
import { addDays, hm, isoToEpoch, localDate, localDayLabel, parseHm, tzAbbrev } from "../time";
import { AqiBadge } from "./LocationPanel";

interface Props {
  prefs: PlanPrefs;
  setPrefs: (p: PlanPrefs) => void;
  tz: string;
  nowEpoch: number;
  plan: PlanResponse | null;
  loading: boolean;
  error: string | null;
}

const DURATIONS = [30, 60, 120];
const THRESHOLDS: [number, string][] = [
  [50, "≤ 50 · Good"],
  [100, "≤ 100 · Moderate or better"],
  [150, "≤ 150 · up to USG"],
  [200, "≤ 200 · up to Unhealthy"],
  [300, "≤ 300 · up to Very unhealthy"],
];
const HALF_HOURS = Array.from({ length: 49 }, (_, i) => i * 30);
const QUARTERS = Array.from({ length: 96 }, (_, i) => i * 15);

function WindowCard({ title, w, tone, tz }: { title: string; w: PlanWindow | null; tone: "base" | "good" | "warn"; tz: string }) {
  const ring = tone === "good" ? "border-emerald-300 bg-emerald-50" : tone === "warn" ? "border-amber-300 bg-amber-50" : "border-line bg-canvas";
  return (
    <div className={`rounded-lg border p-3 ${ring}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</div>
      {w ? (
        <>
          <div className="mt-1 text-lg font-semibold tabular-nums text-ink">
            {w.label} <span className="text-xs font-normal text-muted">{tzAbbrev(isoToEpoch(w.start_utc), tz)}</span>
          </div>
          {w.complete ? (
            <>
              <div className="mt-1 text-sm tabular-nums">
                <b>{w.pm25_index?.toFixed(1)}</b> <span className="text-xs text-muted">{w.pm25_index_units} PM2.5 index</span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5 text-xs text-ink-soft">
                peak <AqiBadge value={w.peak_aqi} size="sm" />
              </div>
            </>
          ) : (
            <div className="mt-1 text-sm text-amber-900">Missing forecast intervals — cannot be scored.</div>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1 text-[10px]">
            {!w.in_allowed_hours && <span className="rounded bg-slate-200 px-1.5 py-0.5">outside permitted hours</span>}
            {w.starts_in_past && <span className="rounded bg-slate-200 px-1.5 py-0.5">already started</span>}
            {w.complete && !w.meets_threshold && <span className="rounded bg-amber-200 px-1.5 py-0.5 text-amber-950">above threshold</span>}
            {w.complete && w.meets_threshold && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-900">meets threshold</span>}
          </div>
        </>
      ) : (
        <div className="mt-1 text-sm text-muted">None available</div>
      )}
    </div>
  );
}

export default function Planner({ prefs, setPrefs, tz, nowEpoch, plan, loading, error }: Props) {
  const today = localDate(nowEpoch, tz);
  const days: [0 | 1, string][] = [
    [0, `Today · ${localDayLabel(nowEpoch, tz)}`],
    [1, `Tomorrow · ${localDayLabel(nowEpoch + 86400, tz)}`],
  ];
  const day = addDays(today, prefs.dayOffset);
  const startMin = parseHm(prefs.allowed_start);
  const endMin = parseHm(prefs.allowed_end);
  const baseMin = parseHm(prefs.baseline_start);
  const formError =
    endMin <= startMin
      ? "Permitted end must be after the start."
      : endMin - startMin < prefs.duration_min
        ? "The activity is longer than the permitted hours."
        : baseMin + prefs.duration_min > 1440
          ? "Your planned slot must finish by midnight."
          : null;
  const set = (patch: Partial<PlanPrefs>) => setPrefs({ ...prefs, ...patch });

  const chosen = plan?.best ?? plan?.least_polluted_available ?? null;
  const c = plan?.comparison;

  return (
    <section aria-labelledby="planner-h" className="rounded-xl border border-line bg-white p-4 shadow-sm">
      <h2 id="planner-h" className="text-base font-semibold text-ink">
        Activity planner
      </h2>
      <p className="mt-0.5 text-xs text-muted">
        Compare your planned slot with the lowest-pollution window in the hours you allow. Preferences are stored only in this browser.
      </p>

      <form className="mt-3 grid grid-cols-2 gap-3 text-sm" onSubmit={(e) => e.preventDefault()}>
        <fieldset className="col-span-2">
          <legend className="mb-1 text-xs font-medium text-ink-soft">Day ({day})</legend>
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-canvas p-1">
            {days.map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={prefs.dayOffset === v}
                onClick={() => set({ dayOffset: v })}
                className={`rounded-md px-2 py-1.5 text-xs font-medium ${prefs.dayOffset === v ? "bg-white text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="col-span-2">
          <legend className="mb-1 text-xs font-medium text-ink-soft">Activity duration</legend>
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-canvas p-1">
            {DURATIONS.map((d) => (
              <button
                key={d}
                type="button"
                aria-pressed={prefs.duration_min === d}
                onClick={() => set({ duration_min: d })}
                className={`rounded-md px-2 py-1.5 text-xs font-medium ${prefs.duration_min === d ? "bg-white text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink"}`}
              >
                {d} min
              </button>
            ))}
          </div>
        </fieldset>

        <label className="text-xs font-medium text-ink-soft">
          Permitted from
          <select className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 text-sm" value={prefs.allowed_start} onChange={(e) => set({ allowed_start: e.target.value })}>
            {HALF_HOURS.slice(0, -1).map((m) => (
              <option key={m} value={hm(m)}>
                {hm(m)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-ink-soft">
          Permitted until
          <select className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 text-sm" value={prefs.allowed_end} onChange={(e) => set({ allowed_end: e.target.value })}>
            {HALF_HOURS.slice(1).map((m) => (
              <option key={m} value={hm(m)}>
                {hm(m)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-ink-soft">
          Your planned start
          <select className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 text-sm" value={prefs.baseline_start} onChange={(e) => set({ baseline_start: e.target.value })}>
            {QUARTERS.map((m) => (
              <option key={m} value={hm(m)}>
                {hm(m)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-ink-soft">
          Planning threshold (peak AQI)
          <select className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 text-sm" value={prefs.threshold_aqi} onChange={(e) => set({ threshold_aqi: Number(e.target.value) })}>
            {THRESHOLDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </form>

      {formError && (
        <p className="mt-3 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-900" role="alert">
          {formError}
        </p>
      )}
      {error && !formError && (
        <p className="mt-3 rounded-md bg-red-50 px-2 py-1.5 text-xs text-red-800" role="alert">
          Could not compute windows: {error}
        </p>
      )}

      {plan && !formError && (
        <div className={`mt-4 ${loading ? "opacity-60" : ""}`} aria-live="polite" aria-busy={loading}>
          {plan.status === "ok" ? (
            <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-900 ring-1 ring-emerald-200">
              {plan.counts.eligible} of {plan.counts.complete} complete windows meet your threshold (peak AQI ≤ {plan.threshold_aqi}).
            </div>
          ) : plan.status === "no_eligible_window" ? (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-950 ring-1 ring-amber-300" role="status">
              No window meets your threshold of AQI ≤ {plan.threshold_aqi}. The least-polluted option below is <u>not</u> a safe window — consider an indoor alternative.
            </div>
          ) : (
            <div className="rounded-lg bg-slate-100 px-3 py-2 text-xs text-ink-soft">{plan.explanations[0]}</div>
          )}

          <div className="mt-3 grid grid-cols-2 gap-2">
            <WindowCard title="Your planned slot" w={plan.baseline} tone="base" tz={plan.timezone} />
            <WindowCard
              title={plan.best ? "Lowest-index eligible" : "Least-polluted · exceeds threshold"}
              w={chosen}
              tone={plan.best ? "good" : "warn"}
              tz={plan.timezone}
            />
          </div>

          {c && (
            <div className="mt-3 rounded-lg border border-line px-3 py-2">
              {c.available && c.pct_change !== null ? (
                c.same_window ? (
                  <p className="text-sm text-ink">Your planned slot is already the lowest-index window.</p>
                ) : (
                  <p className="text-sm text-ink">
                    <span
                      className={`text-2xl font-semibold tabular-nums ${
                        !c.chosen_is_eligible ? "text-ink-soft" : c.pct_change < 0 ? "text-emerald-700" : "text-amber-700"
                      }`}
                    >
                      {c.pct_change > 0 ? "+" : ""}
                      {c.pct_change.toFixed(1)}%
                    </span>{" "}
                    PM2.5 pollution-time index vs your slot
                    <span className="block text-xs text-muted">
                      ({c.abs_change! > 0 ? "+" : ""}
                      {c.abs_change?.toFixed(1)} {plan.index_units}, same location, duration, source and forecast retrieval)
                    </span>
                    {!c.chosen_is_eligible && (
                      <span className="mt-1 block text-xs font-medium text-amber-900">
                        Lower than your slot, but both windows exceed your threshold — this is not a safe window.
                      </span>
                    )}
                  </p>
                )
              ) : (
                <p className="text-xs text-muted">No percentage comparison: {c.reason}</p>
              )}
            </div>
          )}

          {plan.alternatives.length > 0 && (
            <div className="mt-3">
              <h3 className="text-xs font-semibold text-ink-soft">Next eligible options</h3>
              <ul className="mt-1 divide-y divide-line text-xs">
                {plan.alternatives.map((w) => (
                  <li key={w.start_utc} className="flex items-center justify-between py-1.5">
                    <span className="tabular-nums">{w.label}</span>
                    <span className="tabular-nums text-muted">{w.pm25_index?.toFixed(1)} {w.pm25_index_units}</span>
                    <AqiBadge value={w.peak_aqi} size="sm" />
                  </li>
                ))}
              </ul>
            </div>
          )}

          <details className="mt-3 text-xs">
            <summary className="cursor-pointer font-medium text-accent">Why this result? (calculation explained)</summary>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-ink-soft">
              {plan.explanations.map((x) => (
                <li key={x}>{x}</li>
              ))}
              <li>
                Candidates: {plan.counts.candidates} windows at 15-minute steps ({plan.counts.in_past} already started, {plan.counts.incomplete} with missing data, {plan.counts.complete} complete).
              </li>
              <li>
                Index = Σ(hourly PM2.5 × hours of overlap). Partial hours are weighted by overlap. Ranked by index, then peak AQI, then earliest start.
              </li>
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
