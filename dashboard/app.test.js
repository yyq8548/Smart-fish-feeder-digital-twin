import { beforeEach, describe, expect, it, vi } from "vitest";

globalThis.VITEST = true;
const { TelemetryLineChart } = await import("./chart.js");
const {
  ApiError,
  DEFAULT_ACTUATION_DURATION_MS,
  MAX_ACTUATION_DURATION_MS,
  MIN_ACTUATION_DURATION_MS,
  TOKEN_STORAGE_KEY,
  authenticateOperator,
  clearOperatorSession,
  createDashboardController,
  formatTime,
  issueDeviceCommand,
  parseActuationDuration,
  populateDeviceSelect,
  refreshDashboard,
  renderAlerts,
  renderCommands,
  requestJson,
  setHealth,
  startDashboard
} = await import("./app.js");

function response(payload, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(payload) };
}

function installDom() {
  document.body.innerHTML = `
    <span id="temperature"></span><span id="coolingStatus"></span>
    <span id="pumpStatus"></span><span id="lastSeen"></span><span id="systemHealth"></span>
    <p id="monitoringMessage" hidden></p><ul id="alertLog"></ul><canvas id="tempChart"></canvas>
    <form id="loginForm"><input name="username"><input name="password"><button type="submit">Login</button></form>
    <div id="operatorSession" hidden><span id="operatorUsername"></span><select id="deviceSelect"></select>
      <button id="logoutButton" type="button">Logout</button></div>
    <p id="loginMessage" hidden></p><p id="controlState"></p><p id="commandMessage" hidden></p>
    <input id="feedDuration" value="1000" data-duration-control disabled>
    <button type="button" data-command="FEED_NOW" data-duration-input="feedDuration" disabled>Feed</button>
    <input id="cleanDuration" value="1000" data-duration-control disabled>
    <button type="button" data-command="CLEAN_PUMP" data-duration-input="cleanDuration" disabled>Clean</button>
    <button type="button" data-command="SET_COOLING" data-mode="AUTO" disabled>Auto</button>
    <div id="commandHistory"></div>`;
}

beforeEach(() => {
  installDom();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("rendering helpers", () => {
  it("formats timestamps and safely updates health", () => {
    expect(formatTime(null)).toBe("--");
    expect(formatTime("2026-01-01T12:00:00Z")).not.toBe("--");
    setHealth(document.getElementById("systemHealth"), "normal", "Ready");
    expect(document.getElementById("systemHealth").dataset.level).toBe("normal");
    expect(document.getElementById("systemHealth").textContent).toBe("Ready");
    expect(() => setHealth(null, "normal", "ignored")).not.toThrow();
  });

  it("renders empty and populated alerts without injecting markup", () => {
    const list = document.getElementById("alertLog");
    renderAlerts(list, []);
    expect(list.textContent).toContain("No alerts");
    renderAlerts(list, [{
      level: "warning",
      category: "TEMPERATURE",
      message: "<b>Warm</b>",
      created_at: "2026-01-01T12:00:00Z"
    }]);
    expect(list.textContent).toContain("WARNING TEMPERATURE: <b>Warm</b>");
    expect(list.querySelector("b")).toBeNull();
    expect(() => renderAlerts(null, [])).not.toThrow();
  });

  it("renders command lifecycle and expiry information", () => {
    const container = document.getElementById("commandHistory");
    renderCommands(container, []);
    expect(container.textContent).toContain("No commands");
    renderCommands(container, [{
      command_type: "FEED_NOW",
      status: "COMPLETED",
      result: "feeding_and_cleaning_completed",
      created_at: "2026-01-01T12:00:00Z",
      expires_at: "2026-01-01T12:05:00Z"
    }]);
    expect(container.textContent).toContain("FEED_NOW");
    expect(container.textContent).toContain("expires");
    expect(container.querySelector("[data-status='completed']")).not.toBeNull();
    expect(() => renderCommands(null, [])).not.toThrow();
  });

  it("populates and selects devices", () => {
    const select = document.getElementById("deviceSelect");
    const devices = [
      { id: 1, device_uid: "feeder-001", name: "Primary" },
      { id: 2, device_uid: "feeder-002", name: "Backup" }
    ];
    expect(populateDeviceSelect(select, devices, "feeder-002")).toBe("feeder-002");
    expect(select.selectedOptions[0].dataset.deviceId).toBe("2");
    expect(populateDeviceSelect(select, devices, "missing")).toBe("feeder-001");
    expect(populateDeviceSelect(null, devices, "feeder-009")).toBe("feeder-009");
  });

  it("accepts only whole-number actuation durations within the API range", () => {
    expect(DEFAULT_ACTUATION_DURATION_MS).toBe(1000);
    expect(parseActuationDuration(String(MIN_ACTUATION_DURATION_MS))).toBe(500);
    expect(parseActuationDuration(MAX_ACTUATION_DURATION_MS)).toBe(60000);
    for (const invalid of ["", "abc", "1000.5", 499, 60001]) {
      expect(() => parseActuationDuration(invalid)).toThrow(/Duration/);
    }
  });

  it("renders telemetry with the repository-owned canvas chart", () => {
    const context = Object.fromEntries([
      "setTransform", "clearRect", "beginPath", "moveTo", "lineTo", "stroke", "fillText", "arc", "fill"
    ].map((method) => [method, vi.fn()]));
    const canvas = {
      width: 0,
      height: 0,
      parentElement: { clientWidth: 640 },
      getBoundingClientRect: () => ({ width: 640, height: 300 }),
      getContext: () => context
    };
    const chart = new TelemetryLineChart(canvas, {
      data: { labels: ["12:00", "12:01"], datasets: [{ data: [4.0, 4.5] }] },
      options: { scales: { y: { suggestedMin: 2, suggestedMax: 7 } } }
    });
    expect(canvas.width).toBeGreaterThanOrEqual(640);
    expect(context.lineTo).toHaveBeenCalled();
    expect(context.arc).toHaveBeenCalledTimes(2);
    chart.destroy();
    expect(context.clearRect).toHaveBeenCalled();
  });
});

describe("authenticated API client", () => {
  it("sends bearer JSON requests and reports API details", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ id: 8 }));
    expect(await requestJson("/resource", {
      fetchImpl,
      method: "POST",
      token: "secret-token",
      jsonBody: { value: 1 }
    })).toEqual({ id: 8 });
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({ Authorization: "Bearer secret-token", "Content-Type": "application/json" }),
      body: JSON.stringify({ value: 1 })
    });

    fetchImpl.mockResolvedValueOnce(response({ detail: "Expired" }, 401));
    await expect(requestJson("/users/me", { fetchImpl, token: "old" })).rejects.toEqual(
      expect.objectContaining({ name: "ApiError", status: 401, message: "Expired" })
    );
  });

  it("handles a non-JSON error response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: vi.fn().mockRejectedValue(new Error("not json"))
    });
    await expect(requestJson("/health", { fetchImpl })).rejects.toEqual(
      new ApiError("Request failed with status 503", 503)
    );
  });

  it("authenticates with form data and keeps the token in session storage", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ access_token: "operator-jwt" }));
    expect(await authenticateOperator("alice", "password", { fetchImpl, storage: sessionStorage })).toBe("operator-jwt");
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe("operator-jwt");
    const request = fetchImpl.mock.calls[0][1];
    expect(request.headers["Content-Type"]).toBe("application/x-www-form-urlencoded");
    expect(request.body.toString()).toContain("username=alice");
    clearOperatorSession(sessionStorage);
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it("requires confirmation and posts a contract-compatible command", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ id: 31, status: "PENDING" }, 201));
    const confirmImpl = vi.fn().mockReturnValue(false);
    expect(await issueDeviceCommand({
      deviceUid: "feeder-001",
      commandType: "FEED_NOW",
      token: "jwt",
      fetchImpl,
      confirmImpl,
      idempotencyKey: "dashboard-test"
    })).toEqual({ cancelled: true, command: null });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(confirmImpl.mock.calls[0][0]).toContain("reverse-clean cycle follow automatically");
    expect(confirmImpl.mock.calls[0][0]).toContain("1000 ms");

    confirmImpl.mockReturnValue(true);
    const issued = await issueDeviceCommand({
      deviceUid: "feeder/unsafe",
      commandType: "SET_COOLING",
      payload: { mode: "FORCED_OFF" },
      token: "jwt",
      fetchImpl,
      confirmImpl,
      idempotencyKey: "dashboard-cooling-test"
    });
    expect(issued.command.id).toBe(31);
    expect(fetchImpl.mock.calls[0][0]).toContain("feeder%2Funsafe/commands");
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      idempotency_key: "dashboard-cooling-test",
      command_type: "SET_COOLING",
      payload: { mode: "FORCED_OFF" }
    });
  });
});

describe("monitoring states", () => {
  it("loads selected-device data with authentication and filters alerts", async () => {
    const replies = [
      { online: true, temperature_c: 4.25, cooling_on: true, pump_state: "FEEDING", last_seen: "2026-01-01T12:00:00Z", alert_level: "normal", alert_message: null },
      [{ temperature_c: 4.25, recorded_at: "2026-01-01T12:00:00Z" }],
      [
        { device_id: 2, level: "warning", category: "TEMPERATURE", message: "Warm", created_at: "2026-01-01T12:00:00Z" },
        { device_id: 1, level: "critical", category: "PUMP_FAILURE", message: "Other", created_at: "2026-01-01T12:00:00Z" }
      ]
    ];
    const fetchImpl = vi.fn().mockImplementation(() => Promise.resolve(response(replies.shift())));
    const chart = { data: { labels: [], datasets: [{ data: [] }] }, update: vi.fn() };
    const status = await refreshDashboard({
      documentRef: document,
      fetchImpl,
      chart,
      deviceUid: "feeder-002",
      deviceId: 2,
      token: "jwt"
    });
    expect(status.online).toBe(true);
    expect(document.getElementById("temperature").textContent).toBe("4.3");
    expect(document.getElementById("alertLog").textContent).toContain("Warm");
    expect(document.getElementById("alertLog").textContent).not.toContain("Other");
    expect(chart.update).toHaveBeenCalled();
    for (const call of fetchImpl.mock.calls) expect(call[1].headers.Authorization).toBe("Bearer jwt");
    expect(fetchImpl.mock.calls.map((call) => call[0]).join(" ")).toContain("device_uid=feeder-002");
  });

  it("shows a clear device-offline state", async () => {
    const replies = [
      { online: false, temperature_c: null, cooling_on: null, pump_state: null, last_seen: null, alert_level: "warning", alert_message: null },
      [],
      []
    ];
    const fetchImpl = vi.fn().mockImplementation(() => Promise.resolve(response(replies.shift())));
    const status = await refreshDashboard({ documentRef: document, fetchImpl, token: "jwt" });
    expect(status.online).toBe(false);
    expect(document.getElementById("systemHealth").textContent).toBe("Device Offline");
    expect(document.getElementById("monitoringMessage").textContent).toContain("Commands are disabled");
  });

  it("clears stale values when the API fails", async () => {
    document.getElementById("temperature").textContent = "4.0";
    const fetchImpl = vi.fn().mockResolvedValue(response({ detail: "Down" }, 503));
    const chart = { data: { labels: ["old"], datasets: [{ data: [4.0] }] }, update: vi.fn() };
    expect(await refreshDashboard({ documentRef: document, fetchImpl, chart, token: "jwt" })).toBeNull();
    expect(document.getElementById("temperature").textContent).toBe("--");
    expect(document.getElementById("systemHealth").textContent).toBe("API Offline");
    expect(document.getElementById("monitoringMessage").textContent).toContain("Down");
    expect(chart.data.labels).toEqual([]);
    expect(chart.data.datasets[0].data).toEqual([]);
  });
});

describe("operator controller", () => {
  function controllerApi() {
    let nextCommandId = 40;
    return vi.fn(async (url, options) => {
      const method = options.method || "GET";
      if (url.endsWith("/auth/token")) return response({ access_token: "jwt" });
      if (url.endsWith("/users/me")) return response({ username: "alice" });
      if (url.endsWith("/devices") && method === "GET") return response([
        { id: 1, device_uid: "feeder-001", name: "Primary" },
        { id: 2, device_uid: "feeder-002", name: "Backup" }
      ]);
      if (url.includes("/device-status")) return response({
        online: true,
        temperature_c: 4.0,
        cooling_on: false,
        pump_state: "IDLE",
        last_seen: "2026-01-01T12:00:00Z",
        alert_level: "normal",
        alert_message: null
      });
      if (url.includes("/telemetry")) return response([]);
      if (url.includes("/alerts")) return response([]);
      if (url.includes("/commands") && method === "POST") return response({
        id: nextCommandId++, command_type: "FEED_NOW", status: "PENDING", created_at: "2026-01-01T12:00:00Z"
      }, 201);
      if (url.includes("/commands")) return response([]);
      throw new Error(`Unexpected request ${method} ${url}`);
    });
  }

  it("binds login, device selection, confirmed commands, and logout", async () => {
    const fetchImpl = controllerApi();
    const confirmImpl = vi.fn().mockReturnValue(true);
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      confirmImpl,
      chartFactory: null
    });
    await controller.initialize();
    expect(document.getElementById("systemHealth").textContent).toBe("Sign In Required");
    expect(fetchImpl).not.toHaveBeenCalled();

    document.querySelector("[name='username']").value = "alice";
    document.querySelector("[name='password']").value = "password";
    document.getElementById("loginForm").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(document.body.dataset.authenticated).toBe("true"));
    expect(document.getElementById("loginForm").hidden).toBe(true);
    expect(document.getElementById("operatorSession").hidden).toBe(false);
    expect(document.getElementById("operatorUsername").textContent).toBe("alice");
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(false);

    const select = document.getElementById("deviceSelect");
    select.value = "feeder-002";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => expect(fetchImpl.mock.calls.some((call) => call[0].includes("device_uid=feeder-002"))).toBe(true));
    await vi.waitFor(() => expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(false));

    document.getElementById("feedDuration").value = "1500";
    document.querySelector("[data-command='FEED_NOW']").click();
    await vi.waitFor(() => expect(document.getElementById("commandMessage").textContent).toContain("accepted"));
    expect(confirmImpl).toHaveBeenCalled();
    expect(confirmImpl.mock.calls.at(-1)[0]).toContain("1500 ms");
    const commandPost = fetchImpl.mock.calls.find((call) =>
      call[0].includes("/commands") && call[1].method === "POST"
    );
    expect(JSON.parse(commandPost[1].body).payload).toEqual({ duration_ms: 1500 });

    document.getElementById("cleanDuration").value = "499";
    document.querySelector("[data-command='CLEAN_PUMP']").click();
    expect(document.getElementById("commandMessage").textContent).toContain("between 500 and 60000 ms");
    expect(confirmImpl).toHaveBeenCalledTimes(1);

    document.getElementById("logoutButton").click();
    expect(document.body.dataset.authenticated).toBe("false");
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(true);
    expect(document.getElementById("feedDuration").disabled).toBe(true);
    expect(document.getElementById("temperature").textContent).toBe("--");
    expect(document.getElementById("systemHealth").textContent).toBe("Sign In Required");
    expect(document.getElementById("monitoringMessage").textContent).toContain("Authenticate");
  });

  it("blocks actuation while offline and displays command API conflicts", async () => {
    const fetchImpl = controllerApi();
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      chartFactory: null,
      confirmImpl: vi.fn().mockReturnValue(true)
    });
    expect(await controller.issueCommand("FEED_NOW")).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();

    await controller.login("alice", "password");
    fetchImpl.mockImplementationOnce(() => Promise.resolve(response({ detail: "Device is offline" }, 409)));
    expect(await controller.issueCommand("CLEAN_PUMP")).toBeNull();
    expect(document.getElementById("commandMessage").textContent).toContain("Device is offline");
  });

  it("clears an invalid saved session", async () => {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, "expired");
    const fetchImpl = vi.fn().mockResolvedValue(response({ detail: "Invalid or expired access token" }, 401));
    const controller = createDashboardController({ documentRef: document, fetchImpl, storage: sessionStorage, chartFactory: null });
    expect(await controller.loadOperator()).toBe(false);
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(document.getElementById("loginMessage").textContent).toContain("saved session");
  });

  it("ignores a stale device response after the operator changes selection", async () => {
    const baseApi = controllerApi();
    const heldPrimaryRequests = [];
    let holdPrimary = false;
    const fetchImpl = vi.fn((url, options) => {
      if (holdPrimary && url.includes("device_uid=feeder-001")) {
        return new Promise((resolve) => heldPrimaryRequests.push({ resolve, url }));
      }
      if (url.includes("device-status?device_uid=feeder-002")) {
        return Promise.resolve(response({
          online: true,
          temperature_c: 5.5,
          cooling_on: true,
          pump_state: "IDLE",
          last_seen: "2026-01-01T12:00:01Z",
          alert_level: "normal",
          alert_message: null
        }));
      }
      if (url.includes("device_uid=feeder-002")) return Promise.resolve(response([]));
      return baseApi(url, options);
    });
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      chartFactory: null
    });
    await controller.initialize();
    await controller.login("alice", "password");

    holdPrimary = true;
    const staleRefresh = controller.refresh();
    expect(heldPrimaryRequests).toHaveLength(3);

    const select = document.getElementById("deviceSelect");
    select.value = "feeder-002";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => expect(document.getElementById("temperature").textContent).toBe("5.5"));

    for (const request of heldPrimaryRequests) {
      request.resolve(request.url.includes("device-status")
        ? response({
          online: true,
          temperature_c: 9.9,
          cooling_on: false,
          pump_state: "ERROR",
          last_seen: "2026-01-01T12:00:00Z",
          alert_level: "critical",
          alert_message: "Stale primary response"
        })
        : response([]));
    }
    await staleRefresh;
    expect(controller.state.deviceUid).toBe("feeder-002");
    expect(document.getElementById("temperature").textContent).toBe("5.5");
    expect(document.getElementById("systemHealth").textContent).not.toContain("Stale primary");
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(false);
  });

  it("reuses one in-flight monitoring refresh for the same device", async () => {
    const baseApi = controllerApi();
    const pending = [];
    let holdMonitoring = false;
    const fetchImpl = vi.fn((url, options) => {
      if (holdMonitoring && url.includes("device_uid=feeder-001")) {
        return new Promise((resolve) => pending.push({ resolve, url }));
      }
      return baseApi(url, options);
    });
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      chartFactory: null
    });
    await controller.login("alice", "password");

    holdMonitoring = true;
    const firstRefresh = controller.refresh();
    const secondRefresh = controller.refresh();
    expect(pending).toHaveLength(3);
    for (const request of pending) {
      request.resolve(request.url.includes("device-status")
        ? response({
          online: true,
          temperature_c: 6.1,
          cooling_on: true,
          pump_state: "IDLE",
          last_seen: "2026-01-01T12:00:03Z",
          alert_level: "normal",
          alert_message: null
        })
        : response([]));
    }
    await Promise.all([firstRefresh, secondRefresh]);
    expect(document.getElementById("temperature").textContent).toBe("6.1");
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(false);
  });

  it("keeps signed-out data empty when an older refresh finishes", async () => {
    const baseApi = controllerApi();
    const pending = [];
    let holdMonitoring = false;
    const fetchImpl = vi.fn((url, options) => {
      if (holdMonitoring && url.includes("device_uid=feeder-001")) {
        return new Promise((resolve) => pending.push({ resolve, url }));
      }
      return baseApi(url, options);
    });
    let chartInstance;
    class ChartMock {
      constructor() {
        this.data = { labels: [], datasets: [{ data: [] }] };
        this.update = vi.fn();
        chartInstance = this;
      }
    }
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      chartFactory: ChartMock
    });
    await controller.login("alice", "password");

    holdMonitoring = true;
    const staleRefresh = controller.refresh();
    expect(pending).toHaveLength(3);
    chartInstance.data.labels = ["old"];
    chartInstance.data.datasets[0].data = [4.2];
    controller.logout();

    for (const request of pending) {
      request.resolve(request.url.includes("device-status")
        ? response({
          online: true,
          temperature_c: 8.8,
          cooling_on: true,
          pump_state: "FEEDING",
          last_seen: "2026-01-01T12:00:02Z",
          alert_level: "critical",
          alert_message: "Late response"
        })
        : request.url.includes("telemetry")
          ? response([{ temperature_c: 8.8, recorded_at: "2026-01-01T12:00:02Z" }])
          : response([]));
    }
    await staleRefresh;
    expect(document.body.dataset.authenticated).toBe("false");
    expect(document.getElementById("temperature").textContent).toBe("--");
    expect(document.getElementById("systemHealth").textContent).toBe("Sign In Required");
    expect(chartInstance.data.labels).toEqual([]);
    expect(chartInstance.data.datasets[0].data).toEqual([]);
  });

  it("starts chart-backed polling", () => {
    globalThis.Chart = vi.fn(class ChartMock {
      constructor() {
        this.data = { labels: [], datasets: [{ data: [] }] };
        this.update = vi.fn();
      }
    });
    vi.spyOn(globalThis, "setInterval").mockReturnValue(42);
    expect(startDashboard(document)).toBe(42);
    expect(globalThis.Chart).toHaveBeenCalled();
  });
});
