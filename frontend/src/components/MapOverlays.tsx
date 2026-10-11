import { LEGEND, LEGEND_RANGES } from "../aqi";
import { localDateTime, tzAbbrev } from "../time";

export function Legend({ compact }: { compact?: boolean }) {
  if (compact) {
    // Persistent single-row legend for narrow screens: colour + range + short label.
    return (
      <section aria-label="US AQI legend" className="pointer-events-auto rounded-lg border border-line bg-white/95 px-2 py-1.5 shadow-md backdrop-blur">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-soft">Modelled US AQI · ~45 km cells</div>
        <ul className="grid grid-cols-8 gap-0.5 text-center text-[9px] leading-tight">
          {LEGEND.map((b) => (
            <li key={b.key}>
              <span aria-hidden="true" className="block h-2.5 rounded-sm border border-black/10" style={{ background: b.color }} />
              <span className="block tabular-nums text-ink">{LEGEND_RANGES[b.key]}</span>
              <span className="block truncate text-muted" title={b.label}>
                {b.short}
              </span>
            </li>
          ))}
        </ul>
      </section>
    );
  }
  return (
    <section
      aria-label="US AQI legend"
      className="pointer-events-auto rounded-xl border border-line bg-white/95 p-3 text-[11px] shadow-lg backdrop-blur"
    >
      <h2 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Modelled US AQI</h2>
      <ul className={compact ? "grid grid-cols-2 gap-x-3 gap-y-1" : "space-y-1"}>
        {LEGEND.map((b) => (
          <li key={b.key} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block h-3 w-5 shrink-0 rounded-sm border border-black/10"
              style={{ background: b.color }}
            />
            <span className="tabular-nums text-muted">{LEGEND_RANGES[b.key]}</span>
            <span className="truncate text-ink">{b.label}</span>
          </li>
        ))}
        <li className="flex items-center gap-2 pt-1">
          <span aria-hidden="true" className="inline-block h-3 w-3 shrink-0 rounded-full border-2 border-ink bg-white" />
          <span className="text-ink">Observed station (raw value, no AQI colour)</span>
        </li>
      </ul>
      <p className="mt-2 max-w-[15rem] leading-snug text-muted">
        Cells are CAMS Global model samples (~45&nbsp;km). Dashed outline = cached/stale. Not official local measurements.
      </p>
    </section>
  );
}

interface SliderProps {
  times: number[];
  index: number;
  nowIndex: number;
  tz: string;
  onChange: (i: number) => void;
  onStep: (delta: number) => void;
}

export function TimeSlider({ times, index, nowIndex, tz, onChange, onStep }: SliderProps) {
  if (!times.length) return null;
  const t = times[index];
  const offsetH = index - nowIndex;
  return (
    <section
      aria-label="Forecast time"
      className="pointer-events-auto w-full rounded-xl border border-line bg-white/95 px-3 py-2 shadow-lg backdrop-blur"
    >
      <div className="flex items-center justify-between gap-2 text-xs">
        <label htmlFor="timeline" className="font-medium text-ink">
          Forecast hour{" "}
          <span className="font-semibold tabular-nums">
            {localDateTime(t, tz)} {tzAbbrev(t, tz)}
          </span>
        </label>
        <span className="tabular-nums text-muted">
          {offsetH === 0 ? "current hour" : offsetH > 0 ? `+${offsetH} h` : `${offsetH} h`}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <button
          type="button"
          className="rounded-md border border-line px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-40"
          onClick={() => onStep(-1)}
          disabled={index === 0}
          aria-label="Previous hour"
        >
          ‹
        </button>
        <input
          id="timeline"
          type="range"
          className="timeline h-2 w-full cursor-pointer"
          min={0}
          max={times.length - 1}
          step={1}
          value={index}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-valuetext={`${localDateTime(t, tz)} ${tzAbbrev(t, tz)}`}
        />
        <button
          type="button"
          className="rounded-md border border-line px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-40"
          onClick={() => onStep(1)}
          disabled={index === times.length - 1}
          aria-label="Next hour"
        >
          ›
        </button>
        <button
          type="button"
          className="rounded-md border border-line px-2 py-0.5 text-xs font-medium text-accent hover:bg-accent-soft"
          onClick={() => onChange(nowIndex)}
        >
          Now
        </button>
      </div>
    </section>
  );
}
