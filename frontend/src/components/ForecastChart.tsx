import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { classifyUsAqi } from "../aqi";
import type { PlanResponse, PointResponse } from "../types";
import { isoToEpoch, localDate, localDateTime, localTime, tzAbbrev } from "../time";

interface Props {
  point: PointResponse;
  selectedTime: number;
  onSelectTime: (t: number) => void;
  plan: PlanResponse | null;
}

interface Row {
  t: number;
  pm25: number | null;
  aqi: number | null;
}

export default function ForecastChart({ point, selectedTime, onSelectTime, plan }: Props) {
  const tz = point.location.timezone;
  const now = isoToEpoch(point.server_now_utc);
  const { rows, ticks, dayStarts } = useMemo(() => {
    const aq = point.air_quality;
    const today = localDate(now, tz);
    const rows: Row[] = [];
    aq.times.forEach((t, i) => {
      if (localDate(t + 3599, tz) < today) return;
      if (t > now + 48 * 3600) return;
      rows.push({ t, pm25: aq.series.pm2_5.values[i], aqi: aq.series.us_aqi.values[i] });
    });
    const ticks: number[] = [];
    const dayStarts: number[] = [];
    if (rows.length) {
      const t0 = rows[0].t - 3600;
      const t1 = rows[rows.length - 1].t + 3600;
      for (let t = Math.floor(t0 / 900) * 900; t <= t1; t += 900) {
        const hhmm = localTime(t, tz);
        if (hhmm === "00:00") dayStarts.push(t);
        if (["00:00", "06:00", "12:00", "18:00"].includes(hhmm)) ticks.push(t);
      }
    }
    // A final point so the last hourly step is drawn to its end.
    if (rows.length) rows.push({ ...rows[rows.length - 1], t: rows[rows.length - 1].t + 3600 });
    return { rows, ticks, dayStarts };
  }, [point, tz, now]);

  if (!rows.length) return <p className="text-sm text-muted">No forecast hours available for this location.</p>;
  const x0 = rows[0].t;
  const x1 = rows[rows.length - 1].t;
  const clamp = (v: number) => Math.min(x1, Math.max(x0, v));

  const best = plan?.best ?? plan?.least_polluted_available ?? null;
  const base = plan?.baseline ?? null;
  const allowed =
    plan && plan.windows.length
      ? { a: isoToEpoch(plan.windows[0].start_utc), b: isoToEpoch(plan.windows[plan.windows.length - 1].end_utc) }
      : null;

  return (
    <figure className="w-full">
      <figcaption className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded-sm bg-cyan-700/70" /> PM2.5 hourly (µg/m³, left)
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 bg-ink" /> US AQI (right; PM uses 24-h avg)
        </span>
        {plan && (
          <>
            <span className="flex items-center gap-1">
              <span className="stripes inline-block h-2 w-4 rounded-sm border border-slate-400" /> your slot
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-4 rounded-sm bg-emerald-500/40 ring-1 ring-emerald-700" />
              {plan.best ? "lowest-index eligible" : "least-polluted (exceeds threshold)"}
            </span>
          </>
        )}
      </figcaption>
      <div className="h-56 w-full" role="img" aria-label={`Forecast PM2.5 and US AQI chart for the next 48 hours in ${tz}`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 4, bottom: 0, left: -12 }}
            onClick={(s) => {
              const lbl = (s as { activeLabel?: number | string } | null)?.activeLabel;
              if (lbl != null) onSelectTime(Math.floor(Number(lbl) / 3600) * 3600);
            }}
          >
            <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
            {allowed && <ReferenceArea x1={clamp(allowed.a)} x2={clamp(allowed.b)} yAxisId="pm" fill="#0e7490" fillOpacity={0.05} ifOverflow="hidden" />}
            {dayStarts.map((d) => (
              <ReferenceLine key={d} x={d} yAxisId="pm" stroke="#94a3b8" strokeDasharray="2 3" />
            ))}
            {base && (
              <ReferenceArea
                x1={clamp(isoToEpoch(base.start_utc))}
                x2={clamp(isoToEpoch(base.end_utc))}
                yAxisId="pm"
                fill="#64748b"
                fillOpacity={0.22}
                stroke="#475569"
                strokeDasharray="3 2"
                ifOverflow="hidden"
              />
            )}
            {best && (
              <ReferenceArea
                x1={clamp(isoToEpoch(best.start_utc))}
                x2={clamp(isoToEpoch(best.end_utc))}
                yAxisId="pm"
                fill={plan?.best ? "#10b981" : "#f59e0b"}
                fillOpacity={0.3}
                stroke={plan?.best ? "#047857" : "#b45309"}
                ifOverflow="hidden"
              />
            )}
            <XAxis
              dataKey="t"
              type="number"
              domain={[x0, x1]}
              ticks={ticks}
              tickFormatter={(t: number) => {
                const s = localTime(t, tz);
                return s === "00:00" ? localDateTime(t, tz).split(",")[0] : s;
              }}
              tick={{ fontSize: 10, fill: "#64748b" }}
              stroke="#cbd5e1"
            />
            <YAxis yAxisId="pm" tick={{ fontSize: 10, fill: "#64748b" }} stroke="#cbd5e1" width={40} />
            <YAxis yAxisId="aqi" orientation="right" tick={{ fontSize: 10, fill: "#64748b" }} stroke="#cbd5e1" width={34} />
            <Area
              yAxisId="pm"
              type="stepAfter"
              dataKey="pm25"
              stroke="#0e7490"
              strokeWidth={1.5}
              fill="#0e7490"
              fillOpacity={0.18}
              isAnimationActive={false}
              connectNulls={false}
              name="PM2.5"
            />
            <Line yAxisId="aqi" type="stepAfter" dataKey="aqi" stroke="#0f172a" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} name="US AQI" />
            <ReferenceLine x={clamp(now)} yAxisId="pm" stroke="#0f172a" strokeWidth={1} label={{ value: "now", position: "insideTopLeft", fontSize: 10, fill: "#0f172a" }} />
            <ReferenceLine x={clamp(selectedTime + 1800)} yAxisId="pm" stroke="#0e7490" strokeWidth={2} />
            <Tooltip
              isAnimationActive={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Row;
                const c = classifyUsAqi(r.aqi);
                return (
                  <div className="rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs shadow-lg">
                    <div className="font-semibold">
                      {localDateTime(r.t, tz)}–{localTime(r.t + 3600, tz)} {tzAbbrev(r.t, tz)}
                    </div>
                    <div>PM2.5: {r.pm25 ?? "missing"} µg/m³</div>
                    <div>
                      US AQI: {c.aqi ?? "missing"} · {c.label}
                    </div>
                  </div>
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] text-muted">Click the chart to move the map's time slider. Steps show hourly forecast values.</p>
    </figure>
  );
}
