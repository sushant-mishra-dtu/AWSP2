import { useState } from "react";
import type { Bulletin, CampusApi, Card } from "../../campusApi";
import { isoToEpoch, localDayLabel, tzAbbrev } from "../../time";
import { AqiBadge } from "../LocationPanel";

const STATUS: Record<Card["status"], { label: string; cls: string }> = {
  within_threshold: { label: "Within your threshold", cls: "bg-emerald-50 text-emerald-900 ring-emerald-200" },
  exceeds_with_alternative: { label: "Exceeds threshold · alternative available", cls: "bg-amber-50 text-amber-950 ring-amber-300" },
  exceeds_no_alternative: { label: "Exceeds threshold · no eligible alternative", cls: "bg-red-50 text-red-900 ring-red-200" },
  data_unavailable: { label: "Forecast unavailable", cls: "bg-slate-100 text-ink-soft ring-line" },
};

const DECISION_LABEL: Record<string, string> = {
  accept_alternative: "Accepted alternative time",
  shorten: "Shortened activity",
  postpone: "Marked postponed",
  cancel: "Marked cancelled",
  indoor_review: "Indoor alternative needs review",
  keep_original: "Kept original plan",
};

function fmtPct(p: number | null | undefined) {
  return p == null ? "" : `${p > 0 ? "+" : ""}${p.toFixed(1)}%`;
}

export default function ActionCard({ card, api, orgId, onChanged }: { card: Card; api: CampusApi; orgId: string; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const altOptions = card.candidates.filter((w) => w.start_utc !== card.planned.start_utc);
  const [alt, setAlt] = useState(
    [card.alternative, card.least_polluted].find((w) => w && w.start_utc !== card.planned.start_utc)?.start_utc ?? altOptions[0]?.start_utc ?? "",
  );
  const [reason, setReason] = useState("");
  const [showKeep, setShowKeep] = useState(false);
  const [bulletin, setBulletin] = useState<Bulletin | null>(null);
  const tz = card.org.timezone;
  const t0 = isoToEpoch(card.planned.start_utc);
  const st = STATUS[card.status];
  const chosen = card.alternative ?? card.least_polluted;

  async function act(body: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await api.action(orgId, card.occurrence_id, body);
      setShowKeep(false);
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function makeBulletin(lang: "en" | "hi") {
    setBusy(true);
    setErr(null);
    try {
      setBulletin(await api.bulletin(orgId, card.occurrence_id, lang));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const btn = "rounded-md border border-line bg-white px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-slate-50 disabled:opacity-50";
  return (
    <article className="rounded-xl border border-line bg-white p-4 shadow-sm" aria-label={`Action card ${card.activity.name} ${card.date}`}>
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            {card.activity.name}
            {card.activity.location_note && <span className="font-normal text-muted"> · {card.activity.location_note}</span>}
          </h3>
          <p className="text-xs text-muted">
            {localDayLabel(t0, tz)} · planned <b className="text-ink">{card.planned.label}</b> {tzAbbrev(t0, tz)} · {card.activity.duration_min} min ·
            ~{card.activity.participants} participants (coordinator estimate)
          </p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${st.cls}`}>{card.in_past ? "Started / past · " : ""}{st.label}</span>
      </header>

      {card.status !== "data_unavailable" && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-line bg-canvas p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">Planned time</div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              <AqiBadge value={card.planned.peak_aqi} />
              <span className="whitespace-nowrap text-xs text-ink-soft">peak forecast · threshold {card.threshold_aqi}</span>
            </div>
            <div className="mt-1 text-xs tabular-nums">
              PM2.5 index <b>{card.planned.pm25_index?.toFixed(1)}</b> µg·h/m³
            </div>
          </div>
          <div className={`rounded-lg border p-3 ${card.alternative ? "border-emerald-300 bg-emerald-50" : chosen ? "border-amber-300 bg-amber-50" : "border-line bg-canvas"}`}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              {card.alternative ? "Lower-pollution alternative" : chosen ? "Least-polluted · exceeds threshold" : "Alternative"}
            </div>
            {chosen ? (
              <>
                <div className="mt-1 flex items-center gap-2">
                  <b className="text-sm tabular-nums">{chosen.label}</b>
                  <AqiBadge value={chosen.peak_aqi} size="sm" />
                </div>
                <div className="mt-1 text-xs tabular-nums">
                  index <b>{chosen.pm25_index?.toFixed(1)}</b> µg·h/m³ {card.comparison && <span className="text-muted">({fmtPct(card.comparison.pct_change)} vs planned)</span>}
                </div>
                {!card.alternative && <div className="mt-1 text-[11px] font-semibold text-amber-900">Not a safe window.</div>}
              </>
            ) : (
              <div className="mt-1 text-xs text-muted">{card.exceeds ? "No complete alternative in your permitted windows." : "Not needed: planned time is within your threshold."}</div>
            )}
          </div>
        </div>
      )}

      <ul className="mt-3 list-disc space-y-0.5 pl-4 text-xs text-ink-soft">
        {card.explanation.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>

      {card.guidance.available && card.exceeds !== false && (
        <div className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-950 ring-1 ring-sky-200">
          <b>US-AQI school guidance (AirNow, US EPA) for “{card.planned_category.label}”:</b> {card.guidance.text}
          {card.guidance.note && <span className="block text-sky-900/80">{card.guidance.note}</span>}
          <span className="mt-1 block text-[11px] text-sky-900/80">
            {card.guidance.source.scope_note}{" "}
            <a className="underline" href={card.guidance.source.page_url} target="_blank" rel="noreferrer">
              Source ({card.guidance.source.document})
            </a>
          </span>
        </div>
      )}

      {err && <p className="mt-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-800" role="alert">{err}</p>}

      {card.decision && (
        <div className="mt-3 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-xs">
          <b>{DECISION_LABEL[card.decision.type] ?? card.decision.type}</b> by {card.decision.by} · {new Date(card.decision.at).toLocaleString()}
          {card.decision.details.accepted && <> · new time {card.decision.details.accepted.label}</>}
          {card.decision.details.shortened_to_min && <> · {card.decision.details.shortened_to_min} min</>}
          {card.decision.details.comparison?.pct_change != null && (
            <> · modelled PM2.5 index {fmtPct(card.decision.details.comparison.pct_change)} ({card.decision.details.comparison.basis})</>
          )}
          {card.decision.details.reason && <> · reason: “{card.decision.details.reason}”</>}
          {card.decision.type === "indoor_review" && <span className="mt-1 block text-amber-900">Indoor air quality: unverified — no indoor measurements.</span>}
          {card.decision.details.accepted_exceeds_threshold && <span className="mt-1 block text-amber-900">The accepted time still exceeds your threshold.</span>}
          <span className="mt-1 block text-muted">A recorded decision is not proof the change happened — record the outcome afterwards.</span>
        </div>
      )}
      {card.outcome && (
        <p className="mt-2 text-xs text-ink-soft">
          Outcome: <b>{card.outcome.outcome.replaceAll("_", " ")}</b> (recorded by {card.outcome.by})
        </p>
      )}

      {!card.in_past && card.status !== "data_unavailable" && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {altOptions.length > 0 && (
            <span className="flex items-center gap-1">
              <select aria-label="Alternative time" className="rounded-md border border-line bg-white px-1.5 py-1.5 text-xs" value={alt} onChange={(e) => setAlt(e.target.value)}>
                {altOptions.map((w) => (
                    <option key={w.start_utc} value={w.start_utc}>
                      {w.label} · AQI {w.peak_aqi}
                      {w.meets_threshold ? "" : " (exceeds)"}
                    </option>
                  ))}
              </select>
              <button type="button" className={`${btn} border-emerald-300 bg-emerald-600 text-white hover:bg-emerald-700`} disabled={busy || !alt} onClick={() => act({ type: "accept_alternative", start_utc: alt })}>
                Accept time
              </button>
            </span>
          )}
          {card.shorten_options.map((s) => (
            <button key={s.duration_min} type="button" className={btn} disabled={busy} onClick={() => act({ type: "shorten", duration_min: s.duration_min })} title={s.note}>
              Shorten to {s.duration_min} min ({fmtPct(s.pct_change)})
            </button>
          ))}
          <button type="button" className={btn} disabled={busy} onClick={() => act({ type: "postpone" })}>
            Postpone
          </button>
          <button type="button" className={btn} disabled={busy} onClick={() => act({ type: "cancel" })}>
            Cancel
          </button>
          <button type="button" className={btn} disabled={busy} onClick={() => act({ type: "indoor_review" })} title={card.indoor_note}>
            Indoor option: needs review
          </button>
          <button type="button" className={btn} disabled={busy} onClick={() => setShowKeep((v) => !v)}>
            Keep original…
          </button>
        </div>
      )}
      {showKeep && (
        <form
          className="mt-2 flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            act({ type: "keep_original", reason });
          }}
        >
          <input className="flex-1 rounded-md border border-line px-2 py-1 text-xs" placeholder="Reason for keeping the original plan (required)" value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} required />
          <button className={btn} disabled={busy}>
            Record
          </button>
        </form>
      )}
      {card.in_past && !card.outcome && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Record what actually happened:</span>
          {[
            ["held_as_planned", "Held as planned"],
            ["held_as_changed", "Held as changed"],
            ["not_held", "Not held"],
          ].map(([v, l]) => (
            <button key={v} type="button" className={btn} disabled={busy} onClick={() => act({ type: "complete", outcome: v })}>
              {l}
            </button>
          ))}
        </div>
      )}

      <p className="mt-3 text-[11px] text-muted">{card.indoor_note}</p>

      <details className="mt-2 text-[11px] text-ink-soft">
        <summary className="cursor-pointer font-medium text-accent">Evidence for this card</summary>
        <dl className="mt-1 grid grid-cols-[7.5rem_1fr] gap-x-2 gap-y-0.5">
          <dt className="text-muted">Standard</dt><dd>{card.aqi_standard}</dd>
          <dt className="text-muted">Source</dt><dd>{card.provenance.source} · {card.provenance.model}</dd>
          <dt className="text-muted">Data type</dt><dd>Modelled forecast (not a measurement)</dd>
          <dt className="text-muted">Valid (UTC)</dt><dd>{card.provenance.valid_from_utc} → {card.provenance.valid_to_utc}</dd>
          <dt className="text-muted">Retrieved</dt><dd>{card.provenance.retrieved_at} ({card.provenance.cache_status}{card.provenance.stale ? ", STALE" : ""})</dd>
          <dt className="text-muted">Resolution</dt><dd>{card.provenance.spatial_resolution} · {card.provenance.native_time_step}</dd>
          <dt className="text-muted">Data mode</dt>
          <dd>
            {card.provenance.mode}
            {card.provenance.mode === "replay" && <> · captured {card.provenance.replay_captured_at}{card.provenance.replay_synthetic ? " · SYNTHETIC scenario" : ""}</>}
          </dd>
        </dl>
        <ul className="mt-1 list-disc pl-4">{card.planner_explanations.map((x) => <li key={x}>{x}</li>)}</ul>
      </details>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-muted">Coordinator bulletin:</span>
        <button type="button" className={btn} disabled={busy} onClick={() => makeBulletin("en")}>English</button>
        <button type="button" className={btn} disabled={busy} onClick={() => makeBulletin("hi")}>हिन्दी</button>
      </div>
      {bulletin && (
        <div className="mt-2 space-y-2 text-xs">
          <div className="rounded-lg border border-line bg-canvas p-2.5">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">Deterministic bulletin (from the verified facts)</div>
            <pre className="whitespace-pre-wrap font-sans text-ink">{bulletin.deterministic}</pre>
            {bulletin.hindi_note && <p className="mt-1 text-[10px] text-muted">{bulletin.hindi_note}</p>}
          </div>
          {bulletin.ai ? (
            <div className="rounded-lg border border-violet-200 bg-violet-50 p-2.5">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-violet-900">AI-worded version · {bulletin.ai.provider}</div>
              <pre className="whitespace-pre-wrap font-sans text-ink">{bulletin.ai.text}</pre>
              <p className="mt-1 text-[10px] text-violet-900/80">{bulletin.ai.label}</p>
            </div>
          ) : (
            <p className="text-[11px] text-muted">
              AI wording: {bulletin.ai_status.replaceAll("_", " ")}
              {bulletin.ai_attempts.length > 0 && <> ({bulletin.ai_attempts.map((a) => `${a.provider}: ${a.status}`).join("; ")})</>}. The deterministic bulletin above is authoritative.
            </p>
          )}
        </div>
      )}
    </article>
  );
}
