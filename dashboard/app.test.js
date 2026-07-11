import { beforeEach, describe, expect, it, vi } from "vitest";

globalThis.VITEST = true;
const { formatTime, refreshDashboard, renderAlerts, startDashboard } = await import("./app.js");

beforeEach(() => {
  document.body.innerHTML = `<span id="temperature"></span><span id="coolingStatus"></span>
    <span id="pumpStatus"></span><span id="lastSeen"></span><span id="systemHealth"></span><ul id="alertLog"></ul>`;
});

describe("dashboard states", () => {
  it("renders an empty alert state", () => {
    renderAlerts(document.getElementById("alertLog"), []);
    expect(document.getElementById("alertLog").textContent).toContain("No alerts yet");
  });

  it("formats missing timestamps", () => {
    expect(formatTime(null)).toBe("--");
  });

  it("renders the offline state when an API request fails", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false });
    await refreshDashboard({ documentRef: document, fetchImpl });
    expect(document.getElementById("systemHealth").textContent).toBe("API Offline");
  });

  it("renders an empty device status", async () => {
    const responses = [
      { online: false, temperature_c: null, cooling_on: null, pump_state: null, last_seen: null, alert_level: "unknown", alert_message: "No telemetry" },
      [], []
    ];
    const fetchImpl = vi.fn().mockImplementation(() => Promise.resolve({ ok: true, json: () => Promise.resolve(responses.shift()) }));
    await refreshDashboard({ documentRef: document, fetchImpl });
    expect(document.getElementById("temperature").textContent).toBe("--");
    expect(document.getElementById("alertLog").textContent).toContain("No alerts yet");
  });

  it("renders live data and updates a chart", async () => {
    const responses = [
      { online: true, temperature_c: 4.25, cooling_on: true, pump_state: "FEEDING", last_seen: "2026-01-01T12:00:00Z", alert_level: "normal", alert_message: null },
      [{ temperature_c: 4.25, created_at: "2026-01-01T12:00:00Z" }],
      [{ level: "warning", category: "TEMPERATURE", message: "Warm", created_at: "2026-01-01T12:00:00Z" }]
    ];
    const fetchImpl = vi.fn().mockImplementation(() => Promise.resolve({ ok: true, json: () => Promise.resolve(responses.shift()) }));
    const chart = { data: { labels: [], datasets: [{ data: [] }] }, update: vi.fn() };
    await refreshDashboard({ documentRef: document, fetchImpl, chart });
    expect(document.getElementById("temperature").textContent).toBe("4.3");
    expect(document.getElementById("alertLog").textContent).toContain("WARNING TEMPERATURE: Warm");
    expect(chart.update).toHaveBeenCalled();
  });

  it("starts polling with an available chart", () => {
    document.body.insertAdjacentHTML("beforeend", '<canvas id="tempChart"></canvas>');
    globalThis.Chart = vi.fn(class ChartMock {
      constructor() {
        this.data = { labels: [], datasets: [{ data: [] }] };
        this.update = vi.fn();
      }
    });
    vi.spyOn(globalThis, "setInterval").mockReturnValue(42);
    expect(startDashboard(document)).toBe(42);
  });
});
