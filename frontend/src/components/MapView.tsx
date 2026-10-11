import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { CircleMarker, MapContainer, Marker, Rectangle, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import { classifyUsAqi } from "../aqi";
import type { GridCell, SelectedLocation, Station } from "../types";
import { localDateTime } from "../time";

export interface Bounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

interface Props {
  initialCenter: [number, number];
  initialZoom: number;
  cells: GridCell[];
  timeIndex: number;
  times: number[];
  tz: string;
  showCells: boolean;
  stations: Station[];
  showStations: boolean;
  selected: SelectedLocation | null;
  flyTo: { lat: number; lon: number; zoom?: number; seq: number } | null;
  onBounds: (b: Bounds, zoom: number) => void;
  onSelect: (lat: number, lon: number) => void;
  onZoom: (z: number) => void;
  wheelZoom: boolean;
  extraMarkers?: { lat: number; lon: number; label: string; kind: "campus" | "report" }[];
}

const campusIcon = L.divIcon({
  className: "pin-icon",
  iconSize: [26, 26],
  iconAnchor: [13, 13],
  html: `<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect x="2" y="2" width="22" height="22" rx="6" fill="#0e7490" stroke="#fff" stroke-width="2"/><path d="M7 18V11l6-4 6 4v7h-4v-4h-4v4z" fill="#fff"/></svg>`,
});
const reportIcon = L.divIcon({
  className: "pin-icon",
  iconSize: [22, 22],
  iconAnchor: [11, 11],
  html: `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><path d="M11 2 21 19H1z" fill="#ffffff" stroke="#0f172a" stroke-width="2"/><text x="11" y="17" font-size="10" text-anchor="middle" font-family="sans-serif" font-weight="700" fill="#0f172a">!</text></svg>`,
});

const pinIcon = L.divIcon({
  className: "pin-icon",
  iconSize: [28, 36],
  iconAnchor: [14, 34],
  html: `<svg width="28" height="36" viewBox="0 0 28 36" aria-hidden="true"><path d="M14 35s11-11.2 11-20A11 11 0 0 0 3 15c0 8.8 11 20 11 20z" fill="#0f172a" stroke="#fff" stroke-width="2"/><circle cx="14" cy="15" r="4.5" fill="#fff"/></svg>`,
});

const labelIconCache = new Map<string, L.DivIcon>();
function labelIcon(text: string, bg: string, fg: string, stale: boolean): L.DivIcon {
  const key = `${text}|${bg}|${fg}|${stale}`;
  let icon = labelIconCache.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "cell-label",
      iconSize: [0, 0],
      html: `<span style="background:${bg};color:${fg};${stale ? "outline:1px dashed #0f172a;" : ""}">${text}</span>`,
    });
    labelIconCache.set(key, icon);
  }
  return icon;
}

function Events({ onBounds, onSelect, onZoom }: Pick<Props, "onBounds" | "onSelect" | "onZoom">) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const map = useMapEvents({
    moveend: () => schedule(),
    zoomend: () => {
      onZoom(map.getZoom());
      schedule();
    },
    click: (e) => onSelect(e.latlng.lat, e.latlng.lng),
  });
  function schedule() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const b = map.getBounds();
      onBounds({ south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() }, map.getZoom());
    }, 450);
  }
  useEffect(() => {
    schedule();
    onZoom(map.getZoom());
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

function FlyTo({ flyTo }: { flyTo: Props["flyTo"] }) {
  const map = useMap();
  useEffect(() => {
    if (!flyTo) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const z = flyTo.zoom ?? Math.max(map.getZoom(), 9);
    if (reduce) map.setView([flyTo.lat, flyTo.lon], z);
    else map.flyTo([flyTo.lat, flyTo.lon], z, { duration: 0.8 });
  }, [flyTo, map]);
  return null;
}

function WheelZoom({ enabled }: { enabled: boolean }) {
  // In the stacked (mobile/tablet) layout the page scrolls past the map, so the
  // mouse wheel must scroll the page rather than zoom the map.
  const map = useMap();
  useEffect(() => {
    if (enabled) map.scrollWheelZoom.enable();
    else map.scrollWheelZoom.disable();
  }, [enabled, map]);
  return null;
}

function InvalidateOnResize() {
  const map = useMap();
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  return null;
}

export default function MapView(p: Props) {
  const t = p.times[p.timeIndex];
  const cellViews = useMemo(
    () =>
      p.cells.map((c) => {
        const v = c.status === "ok" ? c.us_aqi[p.timeIndex] : null;
        const pm = c.status === "ok" ? c.pm2_5[p.timeIndex] : null;
        return { c, v, pm, cls: classifyUsAqi(v) };
      }),
    [p.cells, p.timeIndex],
  );

  return (
    <MapContainer
      center={p.initialCenter}
      zoom={p.initialZoom}
      minZoom={2}
      maxZoom={18}
      worldCopyJump
      zoomControl={false}
      className="h-full w-full"
      aria-label="Map of modelled air quality sample cells"
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        className="basemap"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Air quality: Open-Meteo / CAMS'
      />
      <ZoomControl position="topright" />
      <Events onBounds={p.onBounds} onSelect={p.onSelect} onZoom={p.onZoom} />
      <FlyTo flyTo={p.flyTo} />
      <InvalidateOnResize />
      <WheelZoom enabled={p.wheelZoom} />

      {p.showCells &&
        cellViews.map(({ c, pm, cls }) => (
          <Rectangle
            key={c.id}
            bounds={c.bounds}
            pathOptions={{
              color: c.stale ? "#0f172a" : "#ffffff",
              weight: c.stale ? 1.5 : 1,
              dashArray: c.stale ? "4 4" : undefined,
              fillColor: cls.color,
              fillOpacity: c.status === "ok" ? 0.42 : 0.25,
            }}
          >
            <Tooltip sticky className="cell-tip">
              <div className="font-semibold">
                {c.status === "ok" ? (
                  <>
                    US AQI {cls.aqi ?? "—"} · {cls.label}
                  </>
                ) : (
                  <>Unavailable</>
                )}
              </div>
              {c.status === "ok" ? (
                <div className="text-slate-600">
                  PM2.5 {pm ?? "—"} µg/m³ · {t ? localDateTime(t, p.tz) : ""}
                  <br />
                  Model sample cell {c.lat.toFixed(1)}°, {c.lon.toFixed(1)}° (~45 km, modelled)
                  {c.stale && (
                    <>
                      <br />
                      <b>Stale:</b> cached {c.retrieved_at}
                    </>
                  )}
                </div>
              ) : (
                <div className="text-slate-600">{c.reason ?? "No data"} — no value is shown.</div>
              )}
            </Tooltip>
          </Rectangle>
        ))}

      {p.showCells &&
        cellViews.map(({ c, cls }) =>
          c.status === "ok" ? (
            <Marker
              key={`l-${c.id}`}
              position={[c.lat, c.lon]}
              icon={labelIcon(
                cls.aqi === null ? "n/a" : cls.key === "beyond" ? `Beyond AQI · ${cls.aqi}` : String(cls.aqi),
                cls.color,
                cls.textColor,
                c.stale,
              )}
              interactive={false}
              keyboard={false}
            />
          ) : null,
        )}

      {p.showStations &&
        p.stations.map((s) => {
          const pm = s.observations.find((o) => o.parameter === "pm25");
          return (
            <CircleMarker
              key={`s-${s.id}`}
              center={[s.lat, s.lon]}
              radius={7}
              pathOptions={{ color: "#0f172a", weight: 2, fillColor: "#ffffff", fillOpacity: 1 }}
            >
              <Tooltip className="cell-tip">
                <div className="font-semibold">{s.name ?? "Station"} · observed</div>
                <div className="text-slate-600">
                  {pm ? (
                    <>
                      PM2.5 {pm.value} {pm.units} · {pm.age_minutes} min old
                    </>
                  ) : (
                    "No PM2.5 sensor reported"
                  )}
                  <br />
                  {s.provider} · {s.distance_km} km away · raw value, not AQI
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}

      {(p.extraMarkers ?? []).map((mk, i) => (
        <Marker key={`x-${i}-${mk.lat}-${mk.lon}`} position={[mk.lat, mk.lon]} icon={mk.kind === "campus" ? campusIcon : reportIcon} keyboard={false}>
          <Tooltip className="cell-tip">{mk.kind === "campus" ? `Campus: ${mk.label}` : mk.label}</Tooltip>
        </Marker>
      ))}
      {p.selected && <Marker position={[p.selected.lat, p.selected.lon]} icon={pinIcon} keyboard={false} />}
    </MapContainer>
  );
}
