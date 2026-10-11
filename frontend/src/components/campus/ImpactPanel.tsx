import { useEffect, useState } from "react";
import { campusApi, type Impact } from "../../campusApi";

const api = campusApi(() => null);

function Stat({ label, value, note }: { label: string; value: number | string; note?: string }) {
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2">
      <div className="text-xl font-semibold tabular-nums text-ink">{value}</div>
      <div className="text-[11px] font-medium leading-tight text-ink-soft">{label}</div>
      {note && <div className="mt-0.5 text-[10px] leading-tight text-muted">{note}</div>}
    </div>
  );
}

export default function ImpactPanel() {
  const [scope, setScope] = useState<"genuine" | "demo" | "all">("genuine");
  const [data, setData] = useState<Impact | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setErr(null); api.impact(scope).then(setData).catch((e) => setErr(e.message)); }, [scope]);
  const c = data?.counters;
  return (
    <div className="space-y-3 p-3 lg:p-4">
      <section className="rounded-xl border border-line bg-white p-4 shadow-sm">
        <h2 className="text-base font-semibold">Impact — what was recorded, honestly</h2>
        <p className="mt-0.5 text-xs text-muted">Counts of records, not health outcomes. Demo records (replay/synthetic data or flagged by a coordinator) are kept separate.</p>
        <div className="mt-2 grid grid-cols-3 gap-1 rounded-lg bg-canvas p-1 text-xs">
          {(["genuine", "demo", "all"] as const).map((s) => (
            <button key={s} aria-pressed={scope === s} onClick={() => setScope(s)} className={`rounded-md px-2 py-1.5 font-semibold capitalize ${scope === s ? "bg-white shadow-sm ring-1 ring-line" : "text-muted"}`}>
              {s === "genuine" ? "Genuine usage" : s === "demo" ? "Demo records" : "All"}
            </button>
          ))}
        </div>
      </section>
      {err && <p className="text-xs text-red-800">{err}</p>}
      {c && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Stat label="Organisations registered" value={c.organisations} />
            <Stat label="Activity occurrences assessed" value={c.occurrences_assessed} note={`${c.assessments_run} assessment runs`} />
            <Stat label="Recommendations proposed" value={c.recommendations_proposed} />
            <Stat label="Recommendations accepted" value={c.accepted} note="Decision recorded; not proof it happened" />
            <Stat label="Declined (kept original)" value={c.declined_kept_original} />
            <Stat label="Activities marked completed" value={c.completed} note={`${c.not_held} marked not held`} />
            <Stat label="Participant-sessions in completed activities" value={c.participant_sessions_completed} note="Coordinator estimates; not unique people" />
            <Stat label="Warnings created" value={c.alerts} note={`${c.alerts_acknowledged} acknowledged in app`} />
            <Stat label="Email publish accepted by SNS" value={c.notifications.publish_accepted} note={`${c.notifications.failed} failed · ${c.notifications.no_confirmed_subscribers} no confirmed subscriber · ${c.notifications.not_sent_local_mode} local, not sent`} />
            <Stat label="Reports reviewed" value={`${c.reports_reviewed}/${c.reports_submitted}`} />
            <Stat label="Report follow-up actions recorded" value={c.report_followup_actions} note={`${c.reports_resolution_reviewed} resolutions reviewed`} />
            <Stat label="Test notifications accepted" value={c.test_notifications.publish_accepted} />
          </div>
          <section className="rounded-xl border border-line bg-white p-4 shadow-sm">
            <h3 className="text-sm font-semibold">Accepted changes: modelled PM2.5 pollution-time index</h3>
            <p className="mt-0.5 text-[11px] text-muted">{data!.labels.comparisons}</p>
            {data!.comparison_total && (
              <p className="mt-2 text-sm">
                Across {data!.comparison_total.count} accepted change(s): {data!.comparison_total.baseline_index_sum} → {data!.comparison_total.new_index_sum} µg·h/m³
                {data!.comparison_total.pct_change != null && <b> ({data!.comparison_total.pct_change > 0 ? "+" : ""}{data!.comparison_total.pct_change}%)</b>}
              </p>
            )}
            <table className="mt-2 w-full text-left text-[11px]">
              <thead className="text-muted"><tr><th>Activity</th><th>Original → new</th><th className="text-right">Index</th><th className="text-right">Change</th></tr></thead>
              <tbody>
                {data!.comparisons.map((x, i) => (
                  <tr key={i} className="border-t border-line">
                    <td>{x.activity} · {x.date}{x.data_mode === "replay" ? " (replay)" : ""}</td>
                    <td>{x.original} → {x.new}{x.duration_changed ? " *" : ""}</td>
                    <td className="text-right tabular-nums">{x.baseline_index?.toFixed(1)} → {x.new_index?.toFixed(1)}</td>
                    <td className="text-right tabular-nums">{x.pct_change == null ? "n/a" : `${x.pct_change > 0 ? "+" : ""}${x.pct_change}%`}</td>
                  </tr>
                ))}
                {data!.comparisons.length === 0 && <tr><td colSpan={4} className="py-1 text-muted">No accepted changes yet.</td></tr>}
              </tbody>
            </table>
            <p className="mt-1 text-[10px] text-muted">* Shortened: the change reflects both less time outdoors and the forecast concentration.</p>
          </section>
          <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-muted">
            {Object.entries(data!.labels).map(([k, v]) => <li key={k}>{v}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}
