import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api";
import { useDebounced } from "../hooks";
import type { GeoResult } from "../types";

interface Props {
  onPick: (r: { lat: number; lon: number; name: string; tz: string | null }) => void;
  onLocate: () => void;
  locating: boolean;
}

export const DEMO_PLACES = [
  { name: "Connaught Place, New Delhi", lat: 28.6315, lon: 77.2167, tz: "Asia/Kolkata" },
  { name: "R.K. Puram, New Delhi", lat: 28.566, lon: 77.1767, tz: "Asia/Kolkata" },
  { name: "Noida Sector 18", lat: 28.5355, lon: 77.391, tz: "Asia/Kolkata" },
];

export default function SearchBox({ onPick, onLocate, locating }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GeoResult[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "empty">("idle");
  const dq = useDebounced(q.trim(), 300);
  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (dq.length < 2) {
      setResults([]);
      setStatus("idle");
      return;
    }
    const ctl = new AbortController();
    setStatus("loading");
    api
      .geocode(dq, ctl.signal)
      .then((r) => {
        setResults(r.results);
        setStatus(r.results.length ? "idle" : "empty");
        setActive(-1);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") setStatus("error");
      });
    return () => ctl.abort();
  }, [dq]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function pick(r: GeoResult) {
    onPick({ lat: r.lat, lon: r.lon, name: [r.name, r.admin1, r.country].filter(Boolean).join(", "), tz: r.timezone });
    setQ(r.name);
    setOpen(false);
  }

  return (
    <div ref={boxRef} className="relative">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <svg aria-hidden="true" viewBox="0 0 20 20" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted">
            <path fill="currentColor" d="M8.5 3a5.5 5.5 0 0 1 4.38 8.83l3.65 3.64-1.06 1.06-3.64-3.65A5.5 5.5 0 1 1 8.5 3Zm0 1.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" />
          </svg>
          <input
            type="search"
            role="combobox"
            aria-expanded={open && results.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-label="Search for a city or place"
            placeholder="Search a city, school area or place…"
            className="w-full rounded-lg border border-line bg-white py-2 pl-9 pr-3 text-sm shadow-sm placeholder:text-slate-400 focus:border-accent"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(results.length - 1, a + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(0, a - 1));
              } else if (e.key === "Enter") {
                const r = results[active >= 0 ? active : 0];
                if (r) pick(r);
              } else if (e.key === "Escape") setOpen(false);
            }}
          />
        </div>
        <button
          type="button"
          onClick={onLocate}
          disabled={locating}
          className="shrink-0 rounded-lg border border-line bg-white px-3 text-sm font-medium text-ink shadow-sm hover:bg-slate-50 disabled:opacity-50"
          aria-label="Use my current location"
          title="Use my location (stays in your browser; only coordinates are sent to fetch the forecast)"
        >
          {locating ? "…" : "◎"}
        </button>
      </div>
      {open && (results.length > 0 || status !== "idle") && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-[1000] mt-1 max-h-72 w-full overflow-auto rounded-lg border border-line bg-white py-1 text-sm shadow-xl"
        >
          {status === "loading" && <li className="px-3 py-2 text-muted">Searching…</li>}
          {status === "error" && <li className="px-3 py-2 text-red-700">Search failed. Try again or click the map.</li>}
          {status === "empty" && <li className="px-3 py-2 text-muted">No matches. You can also click anywhere on the map.</li>}
          {results.map((r, i) => (
            <li
              key={`${r.name}-${r.lat}-${r.lon}`}
              role="option"
              aria-selected={i === active}
              className={`cursor-pointer px-3 py-2 ${i === active ? "bg-accent-soft" : "hover:bg-slate-50"}`}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(r);
              }}
            >
              <div className="font-medium text-ink">{r.name}</div>
              <div className="text-xs text-muted">{[r.admin1, r.country].filter(Boolean).join(", ")}</div>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-muted">Delhi demo:</span>
        {DEMO_PLACES.map((p) => (
          <button
            key={p.name}
            type="button"
            className="rounded-full border border-line bg-white px-2.5 py-0.5 text-ink-soft hover:border-accent hover:text-accent"
            onClick={() => onPick(p)}
          >
            {p.name.split(",")[0]}
          </button>
        ))}
      </div>
    </div>
  );
}
