import { describe, expect, it } from "vitest";
import { classifyUsAqi, roundAqi } from "./aqi";
import { addDays, localDate, localTime } from "./time";

describe("classifyUsAqi", () => {
  const cases: [number, string, number][] = [
    [0, "good", 0],
    [50, "good", 50],
    [50.4, "good", 50],
    [50.5, "moderate", 51],
    [100, "moderate", 100],
    [101, "usg", 101],
    [150, "usg", 150],
    [151, "unhealthy", 151],
    [200, "unhealthy", 200],
    [201, "very_unhealthy", 201],
    [300, "very_unhealthy", 300],
    [301, "hazardous", 301],
    [500, "hazardous", 500],
    [500.5, "beyond", 501],
    [710, "beyond", 710],
  ];
  it.each(cases)("%s -> %s", (v, key, aqi) => {
    const c = classifyUsAqi(v);
    expect(c.key).toBe(key);
    expect(c.aqi).toBe(aqi);
  });

  it.each([null, undefined, -1, -0.2, NaN, Infinity, "100", true])("invalid %s -> unavailable", (v) => {
    const c = classifyUsAqi(v);
    expect(c.key).toBe("unavailable");
    expect(c.aqi).toBeNull();
  });

  it("labels Beyond AQI explicitly", () => {
    expect(classifyUsAqi(612).label).toBe("Beyond AQI");
  });

  it("rounds half up", () => {
    expect(roundAqi(51.5)).toBe(52);
    expect(roundAqi(50.5)).toBe(51);
  });
});

describe("time helpers", () => {
  it("formats in the location timezone, not the browser's", () => {
    const t = Date.UTC(2026, 9, 12, 0, 30) / 1000; // 00:30Z
    expect(localTime(t, "Asia/Kolkata")).toBe("06:00");
    expect(localDate(t, "Asia/Kolkata")).toBe("2026-10-12");
    expect(localDate(t, "America/New_York")).toBe("2026-10-11");
  });
  it("adds calendar days", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
  });
});
