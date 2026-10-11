// Time helpers. All instants are UTC epoch seconds; display always uses the
// selected location's IANA timezone (never the viewer's browser timezone).

const fmtCache = new Map<string, Intl.DateTimeFormat>();

function fmt(tz: string, opts: Intl.DateTimeFormatOptions, locale = "en-GB"): Intl.DateTimeFormat {
  const key = `${locale}|${tz}|${JSON.stringify(opts)}`;
  let f = fmtCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(locale, { timeZone: tz, ...opts });
    fmtCache.set(key, f);
  }
  return f;
}

export function localTime(epochS: number, tz: string): string {
  return fmt(tz, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(epochS * 1000);
}

export function localDate(epochS: number, tz: string): string {
  // en-CA gives YYYY-MM-DD
  return fmt(tz, { year: "numeric", month: "2-digit", day: "2-digit" }, "en-CA").format(epochS * 1000);
}

export function localDayLabel(epochS: number, tz: string): string {
  return fmt(tz, { weekday: "short", day: "numeric", month: "short" }).format(epochS * 1000);
}

export function localDateTime(epochS: number, tz: string): string {
  return fmt(tz, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(epochS * 1000);
}

export function tzAbbrev(epochS: number, tz: string): string {
  const parts = fmt(tz, { timeZoneName: "short" }).formatToParts(epochS * 1000);
  return parts.find((p) => p.type === "timeZoneName")?.value ?? tz;
}

export function addDays(ymd: string, n: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

export function isoToEpoch(iso: string): number {
  return Date.parse(iso) / 1000;
}

export function ageText(iso: string | null, nowEpoch: number): string {
  if (!iso) return "unknown";
  const mins = Math.round((nowEpoch - isoToEpoch(iso)) / 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h} h ${mins % 60} min ago`;
  return `${Math.floor(h / 24)} days ago`;
}

export function hm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function parseHm(v: string): number {
  const [h, m] = v.split(":").map(Number);
  return h * 60 + m;
}
