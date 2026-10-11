import { useCallback, useEffect, useState } from "react";
import { uploadPhoto, type CampusApi, type Org, type Report } from "../../campusApi";
import type { SelectedLocation } from "../../types";

const CATS: [string, string][] = [
  ["open_burning", "Visible open waste burning"],
  ["construction_dust", "Construction dust"],
  ["vehicle_idling", "Vehicle idling near the campus gate"],
  ["other", "Other visible pollution concern"],
];
const TASKS: [string, string][] = [
  ["investigate_burning", "Ask campus staff to investigate the reported burning"],
  ["check_dust_control", "Check dust-control practices"],
  ["no_idling_reminder", "Place a no-idling reminder at the campus gate"],
  ["follow_up_inspection", "Record a follow-up inspection"],
  ["other", "Other campus task"],
];
const FLOW = ["submitted", "reviewed", "assigned", "action_recorded", "resolution_reviewed"];
const FLOW_LABEL = ["Submitted", "Reviewed", "Assigned", "Action recorded", "Resolution reviewed"];
const box = "rounded-xl border border-line bg-white p-4 shadow-sm";
const input = "w-full rounded-lg border border-line bg-white px-2 py-1.5 text-sm";
const btn = "rounded-md border border-line bg-white px-2.5 py-1 text-xs font-semibold hover:bg-slate-50 disabled:opacity-50";

function localIsoNow(): string {
  const d = new Date();
  const off = -d.getTimezoneOffset();
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return new Date(d.getTime() + off * 60000).toISOString().slice(0, 16) + (off >= 0 ? "+" : "-") + pad(off / 60) + ":" + pad(off % 60);
}

export default function ReportsPanel({ api, org, selected, onMarkers }: {
  api: CampusApi; org: Org; selected: SelectedLocation; onMarkers: (m: { lat: number; lon: number; label: string; kind: "report" }[]) => void;
}) {
  const [reports, setReports] = useState<Report[]>([]);
  const [cat, setCat] = useState("open_burning");
  const [observed, setObserved] = useState(localIsoNow().slice(0, 16));
  const [desc, setDesc] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api.reports(org.org_id).then((r) => {
      setReports(r.reports);
      onMarkers(r.reports.map((x) => ({ lat: x.lat, lon: x.lon, label: `${x.category_label} (unverified report)`, kind: "report" as const })));
    }).catch((e) => setErr(e.message));
  }, [api, org.org_id, onMarkers]);
  useEffect(load, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      if (file && (file.size > 5 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp"].includes(file.type))) throw new Error("Photo must be JPEG, PNG or WebP and at most 5 MB.");
      const tzPart = localIsoNow().slice(16);
      const r = await api.addReport(org.org_id, { category: cat, lat: selected.lat, lon: selected.lon, observed_at: `${observed}:00${tzPart}`, description: desc });
      if (file) {
        const target = await api.photoUpload(org.org_id, r.report_id, file.type, file.size);
        await uploadPhoto(target, file);
        await api.photoConfirm(org.org_id, r.report_id);
      }
      setDesc("");
      setFile(null);
      load();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <form className={box} onSubmit={submit}>
        <h3 className="text-sm font-semibold">Report a visible pollution concern near campus</h3>
        <p className="mt-0.5 text-[11px] text-muted">Reports stay unverified until the campus coordinator reviews them. They are never published or sent to authorities, and are not linked to any measured or forecast AQI.</p>
        <label className="mt-2 block text-xs font-medium text-ink-soft">Category
          <select className={input} value={cat} onChange={(e) => setCat(e.target.value)}>{CATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <div className="mt-2 rounded-lg bg-canvas px-2.5 py-1.5 text-xs">Location: <b>{selected.lat.toFixed(4)}°, {selected.lon.toFixed(4)}°</b> <span className="text-muted">(click the map to set)</span></div>
        <label className="mt-2 block text-xs font-medium text-ink-soft">Time observed (your local time)<input type="datetime-local" className={input} value={observed} onChange={(e) => setObserved(e.target.value)} required /></label>
        <label className="mt-2 block text-xs font-medium text-ink-soft">Short description<textarea className={input} rows={2} maxLength={500} minLength={5} value={desc} onChange={(e) => setDesc(e.target.value)} required placeholder="What did you see? Avoid naming individuals." /></label>
        <label className="mt-2 block text-xs font-medium text-ink-soft">Optional photo (JPEG/PNG/WebP, ≤ 5 MB, stored privately)
          <input type="file" accept="image/jpeg,image/png,image/webp" className="mt-1 block text-xs" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <button className="mt-3 rounded-lg bg-ink px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" disabled={busy}>{busy ? "Submitting…" : "Submit report"}</button>
        {err && <p className="mt-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-800" role="alert">{err}</p>}
      </form>
      {reports.map((r) => <ReportItem key={r.report_id + r.status} r={r} api={api} org={org} onChanged={load} />)}
      {reports.length === 0 && <p className="text-xs text-muted">No reports yet.</p>}
    </div>
  );
}

function ReportItem({ r, api, org, onChanged }: { r: Report; api: CampusApi; org: Org; onChanged: () => void }) {
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState("plausible_follow_up");
  const [task, setTask] = useState(r.category === "open_burning" ? "investigate_burning" : r.category === "construction_dust" ? "check_dust_control" : r.category === "vehicle_idling" ? "no_idling_reminder" : "follow_up_inspection");
  const [assignee, setAssignee] = useState("Campus facilities staff");
  const [photo, setPhoto] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const step = (b: Record<string, unknown>) => api.transition(org.org_id, r.report_id, { ...b, note }).then(() => { setNote(""); onChanged(); }).catch((e) => setErr(e.message));
  const idx = FLOW.indexOf(r.status);
  return (
    <article className={box}>
      <div className="flex flex-wrap items-center justify-between gap-1 text-xs">
        <b>{r.category_label}</b>
        <span className={`rounded px-1.5 py-0.5 font-semibold ${r.status === "submitted" ? "bg-amber-100 text-amber-900" : "bg-slate-200 text-ink-soft"}`}>{r.verification}</span>
      </div>
      <p className="mt-1 text-xs text-ink">{r.description}</p>
      <p className="mt-1 text-[11px] text-muted">Observed {new Date(r.observed_at).toLocaleString()} · {r.lat.toFixed(4)}, {r.lon.toFixed(4)} · by {r.submitted_by}</p>
      <ol className="mt-2 flex flex-wrap gap-1 text-[10px]" aria-label="Report progress">
        {FLOW_LABEL.map((l, i) => <li key={l} className={`rounded-full px-2 py-0.5 ${i <= idx ? "bg-ink text-white" : "bg-slate-100 text-muted"}`}>{l}</li>)}
      </ol>
      {r.photo && (
        <div className="mt-2 text-[11px]">
          {photo ? <img src={photo} alt="Report photo (unverified)" className="max-h-48 rounded-lg border border-line" /> :
            <button className={btn} onClick={() => api.photoUrl(org.org_id, r.report_id).then((x) => setPhoto(x.url)).catch((e) => setErr(e.message))}>View private photo</button>}
          <span className="ml-1 text-muted">{r.photo.note}</span>
        </div>
      )}
      {r.review && <p className="mt-1 text-[11px]">Review: <b>{r.review.label}</b> by {r.review.by}</p>}
      {r.assignment && <p className="mt-1 text-[11px]">Task: <b>{r.assignment.label}</b> → {r.assignment.assignee}</p>}
      {r.actions.map((a) => <p key={a.at} className="mt-1 text-[11px]">Action recorded by {a.by}: {a.note}</p>)}
      {r.resolution && <p className="mt-1 text-[11px]">Resolution reviewed by {r.resolution.by}. <i>{r.resolution.caveat}</i></p>}
      {r.can_moderate && r.status !== "resolution_reviewed" && (
        <div className="mt-2 space-y-1.5 rounded-lg bg-canvas p-2 text-xs">
          <input className={input} placeholder="Note (optional for review/assign, required for actions)" value={note} onChange={(e) => setNote(e.target.value)} />
          {r.status === "submitted" && (
            <div className="flex gap-1.5">
              <select className={input} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                <option value="plausible_follow_up">Plausible — follow up on campus</option>
                <option value="insufficient_information">Insufficient information</option>
                <option value="not_actionable">Not actionable by the campus</option>
              </select>
              <button className={btn} onClick={() => step({ step: "review", outcome })}>Review</button>
            </div>
          )}
          {(r.status === "reviewed" || r.status === "assigned") && (
            <div className="flex gap-1.5">
              <select className={input} value={task} onChange={(e) => setTask(e.target.value)}>{TASKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
              <input className={input} value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assignee (role, not a person's name)" />
              <button className={btn} onClick={() => step({ step: "assign", task, assignee })}>Assign</button>
            </div>
          )}
          {(r.status === "assigned" || r.status === "action_recorded") && <button className={btn} onClick={() => step({ step: "record_action" })}>Record follow-up action</button>}
          {r.status === "action_recorded" && <button className={`${btn} ml-1.5`} onClick={() => step({ step: "review_resolution" })}>Review resolution</button>}
        </div>
      )}
      {err && <p className="mt-1 text-xs text-red-800">{err}</p>}
      <p className="mt-2 text-[10px] text-muted">{r.disclaimer}</p>
    </article>
  );
}
