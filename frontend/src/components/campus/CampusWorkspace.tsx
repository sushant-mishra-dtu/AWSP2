import { useCallback, useEffect, useMemo, useState } from "react";
import { cognitoAuth, loadSession, saveSession, type Session } from "../../auth";
import { campusApi, type AlertRec, type AssessSummary, type Activity, type Card, type HistoryRec, type Org, type RuntimeInfo, type Subscription } from "../../campusApi";
import type { SelectedLocation } from "../../types";
import ActionCard from "./ActionCard";
import ReportsPanel from "./ReportsPanel";

interface Props {
  runtime: RuntimeInfo | null;
  selected: SelectedLocation;
  selectedTz: string | null;
  onMarkers: (m: { lat: number; lon: number; label: string; kind: "campus" | "report" }[]) => void;
  onFocus: (lat: number, lon: number) => void;
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const QUARTERS = Array.from({ length: 97 }, (_, i) => `${String(Math.floor((i * 15) / 60)).padStart(2, "0")}:${String((i * 15) % 60).padStart(2, "0")}`);
const NOTIF_LABEL: Record<string, [string, string]> = {
  publish_accepted: ["Publish accepted by SNS", "bg-emerald-100 text-emerald-900"],
  failed: ["Publish failed", "bg-red-100 text-red-900"],
  no_confirmed_subscribers: ["Not sent: no confirmed subscriber", "bg-amber-100 text-amber-900"],
  suppressed_cooldown: ["Not sent: cooldown", "bg-slate-200 text-ink-soft"],
  not_sent_local_mode: ["Prepared, not sent (local mode)", "bg-slate-200 text-ink-soft"],
  prepared: ["Prepared", "bg-slate-200 text-ink-soft"],
};
const SUB_LABEL: Record<string, [string, string]> = {
  confirmed: ["Confirmed", "bg-emerald-100 text-emerald-900"],
  pending_confirmation: ["Pending — check inbox and click the AWS confirmation link", "bg-amber-100 text-amber-900"],
  unavailable_local_mode: ["Not active: local mode has no SNS", "bg-slate-200 text-ink-soft"],
  not_found: ["Not found (unsubscribed or expired)", "bg-red-100 text-red-900"],
};

const box = "rounded-xl border border-line bg-white p-4 shadow-sm";
const input = "w-full rounded-lg border border-line bg-white px-2 py-1.5 text-sm";
const btn = "rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink hover:bg-slate-50 disabled:opacity-50";
const primary = "rounded-lg bg-ink px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50";

function Err({ msg }: { msg: string | null }) {
  return msg ? <p className="mt-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-800" role="alert">{msg}</p> : null;
}

export default function CampusWorkspace({ runtime, selected, selectedTz, onMarkers, onFocus }: Props) {
  const [session, setSession] = useState<Session | null>(() => loadSession());
  const api = useMemo(() => campusApi(() => session?.token ?? null), [session]);
  const [orgs, setOrgs] = useState<Org[] | null>(null);
  const [orgId, setOrgId] = useState<string | null>(() => localStorage.getItem("airwindow.org.v1"));
  const [tab, setTab] = useState<"actions" | "setup" | "reports" | "history">("actions");
  const [err, setErr] = useState<string | null>(null);

  const signOut = useCallback(() => {
    saveSession(null);
    setSession(null);
    setOrgs(null);
  }, []);

  // Refresh Cognito ID tokens before expiry.
  useEffect(() => {
    if (!session || session.method !== "cognito" || !runtime?.cognito) return;
    if (session.expiresAt - Date.now() > 5 * 60_000) return;
    cognitoAuth.refresh(runtime.cognito, session).then((s) => { saveSession(s); setSession(s); }).catch(signOut);
  }, [session, runtime, signOut]);

  const loadOrgs = useCallback(() => {
    if (!session) return;
    api.me().then((m) => {
      setOrgs(m.orgs);
      setOrgId((cur) => (cur && m.orgs.some((o) => o.org_id === cur) ? cur : m.orgs[0]?.org_id ?? null));
    }).catch((e) => {
      if (e.status === 401) signOut();
      else setErr(e.message);
    });
  }, [api, session, signOut]);
  useEffect(loadOrgs, [loadOrgs]);
  useEffect(() => {
    if (orgId) localStorage.setItem("airwindow.org.v1", orgId);
  }, [orgId]);

  const org = orgs?.find((o) => o.org_id === orgId) ?? null;
  useEffect(() => {
    onMarkers(org ? [{ lat: org.lat, lon: org.lon, label: org.name, kind: "campus" }] : []);
  }, [org, onMarkers]);

  if (!runtime) return <p className="p-4 text-sm text-muted">Loading…</p>;
  return (
    <div className="space-y-3 p-3 lg:p-4">
      {runtime.local_mode_notice && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-950 ring-1 ring-amber-300" role="note">
          {runtime.local_mode_notice}
        </p>
      )}
      {runtime.data_mode === "replay" && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-950 ring-1 ring-amber-300">
          DEMO DATA: replay captured {runtime.replay?.captured_at}
          {runtime.replay?.synthetic ? " — SYNTHETIC scenario, not real data" : " (real captured provider responses)"}. Records created now are marked as demo records.
        </p>
      )}
      {!session ? (
        <SignIn runtime={runtime} onSession={(s) => { saveSession(s); setSession(s); }} />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="text-ink-soft">
              Signed in as <b>{session.name}</b> ({session.method === "cognito" ? "Amazon Cognito" : "local development sign-in"})
            </span>
            <button className="text-accent underline" onClick={signOut}>Sign out</button>
          </div>
          <Err msg={err} />
          {orgs && orgs.length > 0 && (
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-ink-soft" htmlFor="org-sel">Campus</label>
              <select id="org-sel" className={input} value={orgId ?? ""} onChange={(e) => setOrgId(e.target.value)}>
                {orgs.map((o) => (
                  <option key={o.org_id} value={o.org_id}>
                    {o.name}{o.is_demo ? " (demo)" : ""}{o.role === "member" ? " — member" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          {orgs && orgs.length === 0 && <RegisterOrg api={api} selected={selected} selectedTz={selectedTz} onCreated={(o) => { setOrgId(o.org_id); loadOrgs(); }} />}
          {orgs && orgs.length === 0 && <JoinOrg api={api} onJoined={(o) => { setOrgId(o.org_id); loadOrgs(); }} />}
          {org && (
            <>
              <nav className="grid grid-cols-4 gap-1 rounded-lg bg-white p-1 text-xs ring-1 ring-line" aria-label="Campus sections">
                {(org.role === "member" ? (["reports"] as const) : (["actions", "setup", "reports", "history"] as const)).map((t) => (
                  <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}
                    className={`rounded-md px-2 py-1.5 font-semibold capitalize ${tab === t ? "bg-ink text-white" : "text-ink-soft hover:bg-slate-50"}`}>
                    {t}
                  </button>
                ))}
              </nav>
              {org.role === "member" || tab === "reports" ? (
                <ReportsPanel api={api} org={org} selected={selected} onMarkers={(m) => onMarkers([{ lat: org.lat, lon: org.lon, label: org.name, kind: "campus" }, ...m])} />
              ) : tab === "actions" ? (
                <ActionsTab api={api} org={org} onFocus={onFocus} />
              ) : tab === "setup" ? (
                <SetupTab api={api} org={org} onOrgChanged={loadOrgs} />
              ) : (
                <HistoryTab api={api} org={org} />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

function SignIn({ runtime, onSession }: { runtime: RuntimeInfo; onSession: (s: Session) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mode, setMode] = useState<"in" | "up" | "confirm">("in");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const api = campusApi(() => null);
  async function run(f: () => Promise<void>) {
    setBusy(true);
    setErr(null);
    try { await f(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  if (runtime.auth === "local-dev-signin") {
    return (
      <form className={box} onSubmit={(e) => { e.preventDefault(); run(async () => {
        const r = await api.localLogin(name);
        onSession({ token: r.token, expiresAt: Date.now() + 11 * 3600_000, name: r.user.name, method: "local" });
      }); }}>
        <h2 className="text-base font-semibold">Coordinator sign-in</h2>
        <p className="mt-1 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-950">
          Local development sign-in: no password and not Amazon Cognito. On AWS this is replaced by Cognito.
        </p>
        <label className="mt-3 block text-xs font-medium text-ink-soft">Your name<input className={input} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} placeholder="e.g. Coordinator A" /></label>
        <button className={`${primary} mt-3`} disabled={busy}>Sign in locally</button>
        <Err msg={err} />
      </form>
    );
  }
  const cfg = runtime.cognito!;
  return (
    <form className={box} onSubmit={(e) => { e.preventDefault(); run(async () => {
      if (mode === "in") onSession(await cognitoAuth.signIn(cfg, email, password));
      else if (mode === "up") { await cognitoAuth.signUp(cfg, email, password, name); setMode("confirm"); }
      else { await cognitoAuth.confirm(cfg, email, code); onSession(await cognitoAuth.signIn(cfg, email, password)); }
    }); }}>
      <h2 className="text-base font-semibold">Coordinator sign-in <span className="text-xs font-normal text-muted">Amazon Cognito</span></h2>
      {mode === "up" && <label className="mt-2 block text-xs font-medium text-ink-soft">Name<input className={input} value={name} onChange={(e) => setName(e.target.value)} required /></label>}
      <label className="mt-2 block text-xs font-medium text-ink-soft">Email<input className={input} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      {mode !== "confirm" && <label className="mt-2 block text-xs font-medium text-ink-soft">Password<input className={input} type="password" autoComplete={mode === "up" ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></label>}
      {mode === "confirm" && <label className="mt-2 block text-xs font-medium text-ink-soft">Verification code (sent to your email)<input className={input} value={code} onChange={(e) => setCode(e.target.value)} required /></label>}
      <div className="mt-3 flex items-center gap-3">
        <button className={primary} disabled={busy}>{mode === "in" ? "Sign in" : mode === "up" ? "Create account" : "Confirm"}</button>
        {mode === "in" ? <button type="button" className="text-xs text-accent underline" onClick={() => setMode("up")}>Create an account</button>
          : <button type="button" className="text-xs text-accent underline" onClick={() => setMode("in")}>Back to sign in</button>}
      </div>
      <Err msg={err} />
    </form>
  );
}

function RegisterOrg({ api, selected, selectedTz, onCreated }: { api: ReturnType<typeof campusApi>; selected: SelectedLocation; selectedTz: string | null; onCreated: (o: Org) => void }) {
  const [name, setName] = useState("");
  const [tz, setTz] = useState(selectedTz ?? "");
  const [threshold, setThreshold] = useState(150);
  const [isDemo, setIsDemo] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (selectedTz) setTz(selectedTz); }, [selectedTz]);
  return (
    <form className={box} onSubmit={(e) => { e.preventDefault(); setErr(null);
      api.createOrg({ name, lat: selected.lat, lon: selected.lon, location_label: selected.name ?? "", timezone: tz || undefined, threshold_aqi: threshold, is_demo: isDemo })
        .then(onCreated).catch((x) => setErr(x.message)); }}>
      <h2 className="text-base font-semibold">Register your campus</h2>
      <p className="mt-0.5 text-xs text-muted">Only aggregate participant counts are collected. No student names or medical information.</p>
      <label className="mt-3 block text-xs font-medium text-ink-soft">School / college name<input className={input} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></label>
      <div className="mt-2 rounded-lg bg-canvas px-2.5 py-2 text-xs">
        Campus location: <b>{selected.name ?? `${selected.lat.toFixed(4)}°, ${selected.lon.toFixed(4)}°`}</b>
        <span className="block text-muted">Search or click the map to change it. Forecasts are ~45 km model cells, not campus-level.</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <label className="text-xs font-medium text-ink-soft">Timezone (IANA)<input className={input} value={tz} onChange={(e) => setTz(e.target.value)} placeholder="auto-detect" /></label>
        <label className="text-xs font-medium text-ink-soft">Planning threshold (peak US AQI)
          <select className={input} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
            {[50, 100, 150, 200, 300].map((v) => <option key={v} value={v}>≤ {v}</option>)}
          </select>
        </label>
      </div>
      <label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={isDemo} onChange={(e) => setIsDemo(e.target.checked)} /> This is a demo/test record (kept out of genuine-usage impact counts)</label>
      <button className={`${primary} mt-3`}>Register campus</button>
      <Err msg={err} />
    </form>
  );
}

function JoinOrg({ api, onJoined }: { api: ReturnType<typeof campusApi>; onJoined: (o: Org) => void }) {
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <form className={box} onSubmit={(e) => { e.preventDefault(); api.join(code).then(onJoined).catch((x) => setErr(x.message)); }}>
      <h2 className="text-sm font-semibold">Or join a campus to submit reports</h2>
      <div className="mt-2 flex gap-2"><input className={input} value={code} onChange={(e) => setCode(e.target.value)} placeholder="Join code from your coordinator" /><button className={btn}>Join</button></div>
      <Err msg={err} />
    </form>
  );
}

function ActionsTab({ api, org, onFocus }: { api: ReturnType<typeof campusApi>; org: Org; onFocus: (lat: number, lon: number) => void }) {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [alerts, setAlerts] = useState<AlertRec[]>([]);
  const [summary, setSummary] = useState<AssessSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    setErr(null);
    api.cards(org.org_id).then((r) => setCards(r.cards)).catch((e) => setErr(e.message));
    api.alerts(org.org_id).then((r) => setAlerts(r.alerts)).catch(() => undefined);
  }, [api, org.org_id]);
  useEffect(() => { load(); onFocus(org.lat, org.lon); }, [load, onFocus, org.lat, org.lon]);
  const upcoming = (cards ?? []).filter((c) => !c.in_past);
  const past = (cards ?? []).filter((c) => c.in_past);
  return (
    <div className="space-y-3">
      <section className={box}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">{org.name}</h2>
            <p className="text-xs text-muted">{org.location_label || `${org.lat}, ${org.lon}`} · {org.timezone} · threshold US AQI ≤ {org.threshold_aqi}{org.is_demo ? " · DEMO RECORD" : ""}</p>
          </div>
          <button className={primary} disabled={busy} onClick={() => { setBusy(true); setErr(null);
            api.assess(org.org_id).then((s) => { setSummary(s); load(); }).catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>
            {busy ? "Checking…" : "Check upcoming activities now"}
          </button>
        </div>
        {summary && (
          <p className="mt-2 rounded-md bg-canvas px-2 py-1.5 text-xs text-ink-soft" role="status">
            Same path as the scheduled job: {summary.assessed} occurrence(s) assessed · {summary.alerts_created} new warning(s) ·{" "}
            {summary.duplicates_skipped} duplicate(s) skipped
            {Object.entries(summary.notifications).map(([k, v]) => ` · ${v} ${NOTIF_LABEL[k]?.[0] ?? k}`).join("")}
            {summary.errors.length > 0 && <span className="block text-red-800">{summary.errors.join("; ")}</span>}
          </p>
        )}
        <Err msg={err} />
      </section>

      {alerts.filter((a) => a.kind !== "test_notification").length > 0 && (
        <section className={box} aria-labelledby="warn-h">
          <h3 id="warn-h" className="text-sm font-semibold">Warnings</h3>
          <ul className="mt-2 space-y-2">
            {alerts.filter((a) => a.kind !== "test_notification").map((a) => {
              const [lbl, cls] = NOTIF_LABEL[a.notification.status] ?? [a.notification.status, "bg-slate-200"];
              return (
                <li key={a.alert_id} className="rounded-lg border border-line p-2.5 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-1">
                    <b>{a.kind === "threshold_exceeded" ? "⚠ Threshold exceeded" : a.kind === "recommendation_changed" ? "↻ Recommendation changed" : "✓ Now within threshold"} · {a.activity_name} {a.date} {a.planned_label}</b>
                    <span className="text-muted">{new Date(a.created_at).toLocaleString()} · {a.trigger}</span>
                  </div>
                  <div className="mt-1">Peak US AQI {a.planned_peak_aqi} ({a.planned_category}) vs threshold {a.threshold_aqi}
                    {a.alternative && <> · {a.alternative.eligible ? "alternative" : "least-polluted (exceeds)"} {a.alternative.label} (AQI {a.alternative.peak_aqi})</>}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span className={`rounded px-1.5 py-0.5 font-semibold ${cls}`}>{lbl}</span>
                    {a.notification.message_id && <span className="text-muted">SNS MessageId {a.notification.message_id.slice(0, 8)}…</span>}
                    {a.acknowledged ? <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-semibold text-emerald-900">Acknowledged by {a.acknowledged.by}</span>
                      : <button className={btn} onClick={() => api.ack(org.org_id, a.alert_id).then(load)}>Acknowledge</button>}
                  </div>
                  <details className="mt-1"><summary className="cursor-pointer text-accent">Message</summary><pre className="mt-1 whitespace-pre-wrap font-sans text-[11px] text-ink-soft">{a.message}</pre></details>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-[11px] text-muted">“Publish accepted” means SNS accepted the message for delivery to confirmed subscribers; it does not show that anyone read it. Acknowledgement is recorded only in the app.</p>
        </section>
      )}

      {cards === null ? <p className="text-sm text-muted">Loading action cards…</p> : cards.length === 0 ? (
        <p className={`${box} text-sm text-muted`}>No activities in the next 48 hours. Add your timetable under “setup”.</p>
      ) : (
        <>
          <h3 className="px-1 text-sm font-semibold text-ink">Upcoming (next 48 h)</h3>
          {upcoming.map((c) => <ActionCard key={c.occurrence_id + (c.decision?.at ?? "")} card={c} api={api} orgId={org.org_id} onChanged={load} />)}
          {past.length > 0 && <h3 className="px-1 pt-2 text-sm font-semibold text-ink">Earlier today — record outcomes</h3>}
          {past.map((c) => <ActionCard key={c.occurrence_id + (c.outcome?.at ?? "")} card={c} api={api} orgId={org.org_id} onChanged={load} />)}
        </>
      )}
    </div>
  );
}

function SetupTab({ api, org, onOrgChanged }: { api: ReturnType<typeof campusApi>; org: Org; onOrgChanged: () => void }) {
  const [acts, setActs] = useState<Activity[]>([]);
  const [subs, setSubs] = useState<{ subscriptions: Subscription[]; can_send: boolean; notifier: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "Morning PE", kind: "pe", days: [0, 1, 2, 3, 4, 5], start: "07:30", duration_min: 60, participants: 40, location_note: "Main field",
    alternatives: [{ start: "13:30", end: "16:00" }] as { start: string; end: string }[] });
  const [email, setEmail] = useState("");
  const load = useCallback(() => {
    api.activities(org.org_id).then((r) => setActs(r.activities)).catch((e) => setErr(e.message));
    api.subs(org.org_id, true).then(setSubs).catch(() => undefined);
  }, [api, org.org_id]);
  useEffect(load, [load]);
  const f = (p: Partial<typeof form>) => setForm({ ...form, ...p });
  return (
    <div className="space-y-3">
      <section className={box}>
        <h3 className="text-sm font-semibold">Campus settings</h3>
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
          <label className="font-medium text-ink-soft">Planning threshold (peak US AQI)
            <select className={input} value={org.threshold_aqi} onChange={(e) => api.patchOrg(org.org_id, { threshold_aqi: Number(e.target.value) }).then(onOrgChanged).catch((x) => setErr(x.message))}>
              {[50, 100, 150, 200, 300].map((v) => <option key={v} value={v}>≤ {v}</option>)}
            </select>
          </label>
          <div className="text-ink-soft">Timezone<div className="mt-1 font-semibold text-ink">{org.timezone}</div></div>
        </div>
        <p className="mt-2 text-xs text-ink-soft">Join code for staff to submit reports: <b className="font-mono">{org.join_code}</b></p>
      </section>

      <section className={box}>
        <h3 className="text-sm font-semibold">Outdoor activity timetable</h3>
        <ul className="mt-2 divide-y divide-line text-xs">
          {acts.map((a) => (
            <li key={a.activity_id} className="flex items-center justify-between gap-2 py-1.5">
              <span><b>{a.name}</b> · {a.days.map((d) => DAYS[d]).join(" ")} · {a.start} · {a.duration_min} min · ~{a.participants} (est.)
                {a.alternatives.length > 0 && <> · alternatives {a.alternatives.map((r) => `${r.start}–${r.end}`).join(", ")}</>}</span>
              <button className="text-red-700 underline" onClick={() => api.removeActivity(org.org_id, a.activity_id).then(load)}>Remove</button>
            </li>
          ))}
          {acts.length === 0 && <li className="py-1.5 text-muted">No activities yet.</li>}
        </ul>
        <form className="mt-3 grid grid-cols-2 gap-2 text-xs" onSubmit={(e) => { e.preventDefault(); setErr(null);
          api.addActivity(org.org_id, form).then(() => { setMsg("Activity saved."); load(); }).catch((x) => setErr(x.message)); }}>
          <label className="font-medium text-ink-soft">Name<input className={input} value={form.name} onChange={(e) => f({ name: e.target.value })} required /></label>
          <label className="font-medium text-ink-soft">Kind
            <select className={input} value={form.kind} onChange={(e) => f({ kind: e.target.value })}>
              {["recess", "pe", "sports", "assembly", "event", "other"].map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </label>
          <fieldset className="col-span-2"><legend className="font-medium text-ink-soft">Days</legend>
            <div className="mt-1 flex flex-wrap gap-1">{DAYS.map((d, i) => (
              <label key={d} className={`cursor-pointer rounded-md px-2 py-1 ring-1 ${form.days.includes(i) ? "bg-ink text-white ring-ink" : "ring-line"}`}>
                <input type="checkbox" className="sr-only" checked={form.days.includes(i)} onChange={(e) => f({ days: e.target.checked ? [...form.days, i] : form.days.filter((x) => x !== i) })} />{d}
              </label>))}</div>
          </fieldset>
          <label className="font-medium text-ink-soft">Planned start<select className={input} value={form.start} onChange={(e) => f({ start: e.target.value })}>{QUARTERS.slice(0, 96).map((q) => <option key={q}>{q}</option>)}</select></label>
          <label className="font-medium text-ink-soft">Duration
            <select className={input} value={form.duration_min} onChange={(e) => f({ duration_min: Number(e.target.value) })}>{[30, 45, 60, 90, 120].map((d) => <option key={d} value={d}>{d} min</option>)}</select>
          </label>
          <label className="font-medium text-ink-soft">Participants (estimate)<input type="number" min={0} max={5000} className={input} value={form.participants} onChange={(e) => f({ participants: Number(e.target.value) })} /></label>
          <label className="font-medium text-ink-soft">Location on campus<input className={input} value={form.location_note} onChange={(e) => f({ location_note: e.target.value })} /></label>
          <fieldset className="col-span-2"><legend className="font-medium text-ink-soft">Permitted alternative windows (same day)</legend>
            {form.alternatives.map((r, i) => (
              <div key={i} className="mt-1 flex items-center gap-1">
                <select className={input} value={r.start} onChange={(e) => f({ alternatives: form.alternatives.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)) })}>{QUARTERS.map((q) => <option key={q}>{q}</option>)}</select>
                <span>–</span>
                <select className={input} value={r.end} onChange={(e) => f({ alternatives: form.alternatives.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)) })}>{QUARTERS.map((q) => <option key={q}>{q}</option>)}</select>
                <button type="button" className="px-1 text-red-700" aria-label="Remove window" onClick={() => f({ alternatives: form.alternatives.filter((_, j) => j !== i) })}>✕</button>
              </div>
            ))}
            {form.alternatives.length < 4 && <button type="button" className="mt-1 text-accent underline" onClick={() => f({ alternatives: [...form.alternatives, { start: "09:00", end: "11:00" }] })}>+ add window</button>}
          </fieldset>
          <div className="col-span-2"><button className={primary}>Save activity</button></div>
        </form>
        {msg && <p className="mt-2 text-xs text-emerald-800">{msg}</p>}
        <Err msg={err} />
      </section>

      <section className={box}>
        <h3 className="text-sm font-semibold">Email warnings (opt-in, Amazon SNS)</h3>
        {subs && !subs.can_send && <p className="mt-1 rounded-md bg-slate-100 px-2 py-1 text-xs text-ink-soft">Local mode: no SNS topic is configured, so no email can be sent. Subscriptions are shown as not active.</p>}
        <ul className="mt-2 space-y-1 text-xs">
          {subs?.subscriptions.map((s) => {
            const [l, c] = SUB_LABEL[s.status] ?? [s.status, "bg-slate-200"];
            return (
              <li key={s.sub_id} className="flex items-center justify-between gap-2">
                <span>{s.email_masked} <span className={`ml-1 rounded px-1.5 py-0.5 font-semibold ${c}`}>{l}</span></span>
                <button className="text-red-700 underline" onClick={() => api.removeSub(org.org_id, s.sub_id).then(load)}>Remove</button>
              </li>
            );
          })}
        </ul>
        <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); setErr(null); api.addSub(org.org_id, email).then(() => { setEmail(""); load(); }).catch((x) => setErr(x.message)); }}>
          <input type="email" className={input} placeholder="coordinator@school.example" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <button className={btn}>Subscribe</button>
        </form>
        <div className="mt-2 flex flex-wrap gap-2">
          <button className={btn} onClick={() => api.subs(org.org_id, true).then(setSubs)}>Refresh confirmation status</button>
          <button className={btn} onClick={() => api.testNotification(org.org_id).then((a) => setMsg(`Test notification: ${NOTIF_LABEL[a.notification.status]?.[0] ?? a.notification.status}${a.notification.message_id ? ` (MessageId ${a.notification.message_id})` : ""}`)).catch((x) => setErr(x.message))}>Send test notification</button>
        </div>
        <p className="mt-2 text-[11px] text-muted">AWS sends a confirmation email; nothing is delivered until the recipient clicks the link. A published message is not proof it was read.</p>
      </section>
    </div>
  );
}

function HistoryTab({ api, org }: { api: ReturnType<typeof campusApi>; org: Org }) {
  const [items, setItems] = useState<HistoryRec[] | null>(null);
  useEffect(() => { api.history(org.org_id).then((r) => setItems(r.history)).catch(() => setItems([])); }, [api, org.org_id]);
  return (
    <section className={box}>
      <h3 className="text-sm font-semibold">Action history (append-only audit log)</h3>
      <ol className="mt-2 space-y-1.5 text-xs">
        {items?.map((h) => (
          <li key={h.sk} className="border-l-2 border-line pl-2">
            <span className="text-muted">{new Date(h.at).toLocaleString()}</span> · <b>{h.event.replaceAll("_", " ")}</b> · {h.actor}
            {h.data_mode === "replay" && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-900">replay</span>}
            <span className="block truncate text-muted" title={JSON.stringify(h.details)}>{JSON.stringify(h.details)}</span>
          </li>
        ))}
        {items?.length === 0 && <li className="text-muted">No history yet.</li>}
      </ol>
    </section>
  );
}
