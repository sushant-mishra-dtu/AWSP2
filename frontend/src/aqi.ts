// US AQI classification — mirrors backend/app/aqi.py (both are unit-tested).
// Decimal inputs are rounded half-up before classification (50.5 -> 51).
// Negative, NaN, infinite, null or non-numeric input -> "Unavailable".

export interface AqiClass {
  key: string;
  label: string;
  short: string;
  color: string;
  textColor: string;
  aqi: number | null;
}

const BANDS: [string, string, string, number, number, string, string][] = [
  ["good", "Good", "Good", 0, 50, "#00e400", "#0b2e0b"],
  ["moderate", "Moderate", "Moderate", 51, 100, "#ffff00", "#3a3500"],
  ["usg", "Unhealthy for sensitive groups", "USG", 101, 150, "#ff7e00", "#2b1400"],
  ["unhealthy", "Unhealthy", "Unhealthy", 151, 200, "#ff0000", "#ffffff"],
  ["very_unhealthy", "Very unhealthy", "Very unhealthy", 201, 300, "#8f3f97", "#ffffff"],
  ["hazardous", "Hazardous", "Hazardous", 301, 500, "#7e0023", "#ffffff"],
];

export const BEYOND: AqiClass = { key: "beyond", label: "Beyond AQI", short: "Beyond AQI", color: "#3d0011", textColor: "#ffffff", aqi: null };
export const UNAVAILABLE: AqiClass = { key: "unavailable", label: "Unavailable", short: "n/a", color: "#9ca3af", textColor: "#111827", aqi: null };

export function roundAqi(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  return Math.floor(value + 0.5);
}

export function classifyUsAqi(value: unknown): AqiClass {
  const aqi = roundAqi(value);
  if (aqi === null) return UNAVAILABLE;
  for (const [key, label, short, lo, hi, color, textColor] of BANDS) {
    if (aqi >= lo && aqi <= hi) return { key, label, short, color, textColor, aqi };
  }
  return { ...BEYOND, aqi };
}

export const LEGEND: AqiClass[] = [
  ...BANDS.map(([key, label, short, , , color, textColor]) => ({ key, label, short, color, textColor, aqi: null })),
  BEYOND,
  UNAVAILABLE,
];

export const LEGEND_RANGES: Record<string, string> = {
  good: "0–50",
  moderate: "51–100",
  usg: "101–150",
  unhealthy: "151–200",
  very_unhealthy: "201–300",
  hazardous: "301–500",
  beyond: ">500",
  unavailable: "no data",
};
