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
  confirmCustomerPasswordReset,
  cancelDeviceTransfer,
  createDeviceTransfer,
  deleteFeedingSchedule,
  createFeedingSchedule,
  createCommandDialog,
  createDashboardController,
  formatTime,
  issueDeviceCommand,
  parseActuationDuration,
  pairCustomerDevice,
  parseDeviceClaimPayload,
  passwordsMatch,
  populateDeviceSelect,
  refreshDashboard,
  renderAlerts,
  renderCommands,
  renderNextSchedule,
  renderScheduleManager,
  registerCustomer,
  requestJson,
  requestCustomerPasswordReset,
  schedulePayloadFromForm,
  setHealth,
  startDashboard,
  updateFeedingSchedule
} = await import("./app.js");

function response(payload, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: vi.fn().mockResolvedValue(payload) };
}

function installDom() {
  document.body.innerHTML = `
    <article id="temperatureCard"><span id="temperature"></span></article>
    <article id="coolingCard"><span id="coolingStatus"></span></article>
    <article id="pumpCard"><span id="pumpStatus"></span></article>
    <article id="heartbeatCard"><span id="lastSeen"></span></article><span id="systemHealth"></span>
    <article id="sceneTemperatureCard"><span id="sceneTemperature"></span></article>
    <article id="sceneCoolingCard"><span id="sceneCoolingStatus"></span></article>
    <article id="scenePumpCard"><span id="scenePumpStatus"></span></article>
    <article id="sceneHeartbeatCard"><span id="sceneLastSeen"></span></article>
    <p id="monitoringMessage" hidden></p><ul id="alertLog"></ul><canvas id="tempChart"></canvas>
    <div id="authModeSwitch"><button type="button" role="tab" data-auth-mode="signin">Sign in</button>
      <button type="button" role="tab" data-auth-mode="signup">Create account</button></div>
    <form id="loginForm"><input name="username"><input name="password"><button type="submit">Login</button>
      <button id="forgotPasswordButton" type="button">Forgot password</button></form>
    <form id="registrationForm" hidden><input name="email"><input name="password"><input name="password_confirm">
      <button type="submit">Register</button></form>
    <form id="passwordResetRequestForm" hidden><input name="email"><button type="submit">Reset</button></form>
    <form id="passwordResetConfirmForm" hidden><input name="token"><input name="password">
      <input name="password_confirm"><button type="submit">Confirm reset</button></form>
    <div id="demoAccess"><button id="demoLoginButton" type="button">Try demo</button></div>
    <div id="operatorSession" hidden><span id="operatorUsername"></span><label id="devicePicker"><select id="deviceSelect"></select></label>
      <button id="logoutButton" type="button">Logout</button></div>
    <div id="customerDevicePanel" hidden><p id="pairingIntroText"></p>
      <button id="scanDeviceQrButton" type="button">Scan</button><input id="deviceQrInput" type="file">
      <input id="claimLinkInput">
      <form id="devicePairingForm"><input name="device_uid"><input name="pairing_code"><button type="submit">Pair</button></form>
      <button id="transferDeviceButton" type="button" hidden>Transfer</button>
      <button id="cancelTransferButton" type="button" hidden>Cancel transfer</button>
      <button id="unpairDeviceButton" type="button" hidden>Unpair</button><p id="pairingMessage" hidden></p></div>
    <p id="demoModeBanner" hidden></p>
    <section class="aquarium-hero" data-playing="true">
      <aside id="conciergeShowcase" data-feeding="false">
        <video id="aquariumVideo"></video>
        <button id="aquariumPlayButton" type="button" aria-pressed="false"><svg><path></path></svg><span>Play aquarium scene</span></button>
        <div id="butlerCard" data-state="ready">
          <strong id="butlerStatus">Standing by</strong>
          <small id="butlerMessage">Ready</small>
        </div>
      </aside>
    </section>
    <p id="loginMessage" hidden></p><p id="controlState"></p><p id="commandMessage" hidden></p>
    <strong id="nextFeedTime"></strong><small id="nextFeedName"></small>
    <section id="schedule"><span id="scheduleCount"></span>
      <form id="scheduleForm">
        <input name="name" value="Daily feeding">
        <input name="time" type="time" value="09:00">
        <input name="timezone" value="UTC">
        <input name="grace_minutes" type="number" value="10">
        <input name="days_of_week" type="checkbox" value="0" checked>
        <input name="days_of_week" type="checkbox" value="2" checked>
        <input name="enabled" type="checkbox" checked>
        <button type="submit" disabled>Add schedule</button>
        <p id="scheduleMessage" hidden></p>
      </form>
      <div id="scheduleList"></div>
    </section>
    <input id="feedDuration" value="1000" data-duration-control disabled>
    <button type="button" data-command="FEED_NOW" data-duration-input="feedDuration" disabled>Feed</button>
    <input id="cleanDuration" value="1000" data-duration-control disabled>
    <button type="button" data-command="CLEAN_PUMP" data-duration-input="cleanDuration" disabled>Clean</button>
    <button type="button" data-command="SET_COOLING" data-mode="AUTO" disabled>Auto</button>
    <button type="button" data-scene-command="FEED_NOW" data-duration-input="feedDuration" disabled>Scene feed</button>
    <button type="button" data-scene-command="CLEAN_PUMP" data-duration-input="cleanDuration" disabled>Scene clean</button>
    <div id="commandHistory"></div>
    <dialog id="commandDialog" aria-labelledby="commandDialogTitle" aria-describedby="commandDialogDescription">
      <button id="commandDialogClose" type="button">Close</button>
      <h2 id="commandDialogTitle"></h2><p id="commandDialogDescription"></p>
      <span id="commandDialogDevice"></span><span id="commandDialogAction"></span>
      <span id="commandDialogDuration"></span><span id="commandDialogLastFeed"></span>
      <p id="commandDialogFeedback" hidden></p>
      <button id="commandDialogCancel" type="button">Cancel</button>
      <button id="commandDialogConfirm" type="button"><span>Confirm command</span></button>
    </dialog>`;
}

beforeEach(() => {
  installDom();
  delete window.BarcodeDetector;
  delete window.createImageBitmap;
  document.getElementById("aquariumVideo").play = vi.fn().mockResolvedValue(undefined);
  document.getElementById("aquariumVideo").pause = vi.fn();
  const dialog = document.getElementById("commandDialog");
  Object.defineProperty(dialog, "open", { configurable: true, writable: true, value: false });
  dialog.showModal = vi.fn(() => { dialog.open = true; });
  dialog.close = vi.fn(() => { dialog.open = false; });
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
    expect(list.querySelector("li").dataset.level).toBe("warning");
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

  it("validates and renders recurring feeding schedules", () => {
    const form = document.getElementById("scheduleForm");
    const payload = schedulePayloadFromForm(new FormData(form));
    expect(payload).toEqual({
      name: "Daily feeding",
      hour: 9,
      minute: 0,
      days_of_week: [0, 2],
      timezone: "UTC",
      grace_minutes: 10,
      enabled: true
    });
    for (const checkbox of form.querySelectorAll("[name='days_of_week']")) checkbox.checked = false;
    expect(() => schedulePayloadFromForm(new FormData(form))).toThrow("Choose at least one day");

    renderScheduleManager(document, [{
      id: 4,
      name: "<img src=x>",
      hour: 18,
      minute: 5,
      days_of_week: "0,1,2,3,4",
      timezone: "America/New_York",
      grace_minutes: 10,
      enabled: true
    }], { canManage: true });
    expect(document.getElementById("scheduleCount").textContent).toBe("1 schedule");
    expect(document.getElementById("scheduleList").textContent).toContain("Weekdays");
    expect(document.getElementById("scheduleList").querySelector("img")).toBeNull();
    expect(document.querySelector("[data-schedule-action='toggle']").disabled).toBe(false);
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
    expect(populateDeviceSelect(select, [], "feeder-009")).toBeNull();
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

  it("calls the customer registration, recovery, and pairing contracts", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response({ message: "Accepted" }, 202));
    expect(passwordsMatch("SecureFeeder42", "SecureFeeder42")).toBe("SecureFeeder42");
    expect(() => passwordsMatch("one", "two")).toThrow("Passwords do not match");

    await registerCustomer("person@example.com", "SecureFeeder42", { fetchImpl });
    await requestCustomerPasswordReset("person@example.com", { fetchImpl });
    await confirmCustomerPasswordReset("reset-token", "NewSecureFeeder84", { fetchImpl });
    await pairCustomerDevice("feeder-007", "PAIR-CODE", "customer-jwt", { fetchImpl });
    await createDeviceTransfer("feeder-007", "customer-jwt", { fetchImpl });
    await cancelDeviceTransfer("feeder-007", "customer-jwt", { fetchImpl });

    expect(fetchImpl.mock.calls.map((call) => call[0])).toEqual([
      expect.stringContaining("/auth/register"),
      expect.stringContaining("/auth/password-reset/request"),
      expect.stringContaining("/auth/password-reset/confirm"),
      expect.stringContaining("/devices/claim"),
      expect.stringContaining("/devices/feeder-007/transfer"),
      expect.stringContaining("/devices/feeder-007/transfer")
    ]);
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      email: "person@example.com",
      password: "SecureFeeder42"
    });
    expect(JSON.parse(fetchImpl.mock.calls[3][1].body)).toEqual({
      device_uid: "feeder-007",
      proof_of_possession: "PAIR-CODE"
    });
    expect(fetchImpl.mock.calls[3][1].headers.Authorization).toBe("Bearer customer-jwt");
    expect(fetchImpl.mock.calls[4][1].method).toBe("POST");
    expect(fetchImpl.mock.calls[5][1].method).toBe("DELETE");
  });

  it("parses current, legacy, and JSON feeder claim payloads", () => {
    expect(parseDeviceClaimPayload(
      "https://feeder.example.test/?device_uid=feeder-007&claim_code=ONE-TIME-CODE"
    )).toEqual({ deviceUid: "feeder-007", proofOfPossession: "ONE-TIME-CODE" });
    expect(parseDeviceClaimPayload(
      "?device_uid=feeder-008&pairing_code=LEGACY-CODE",
      "https://feeder.example.test/"
    )).toEqual({ deviceUid: "feeder-008", proofOfPossession: "LEGACY-CODE" });
    expect(parseDeviceClaimPayload(JSON.stringify({
      device_uid: "feeder-009",
      proof_of_possession: "JSON-CLAIM-CODE"
    }))).toEqual({ deviceUid: "feeder-009", proofOfPossession: "JSON-CLAIM-CODE" });
    expect(() => parseDeviceClaimPayload("https://example.test/no-claim")).toThrow("valid feeder ID");
  });

  it("fills claim fields from QR content and handles supported and unsupported scanners", async () => {
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl: vi.fn(),
      storage: sessionStorage,
      chartFactory: null
    });
    const claimUrl = "https://feeder.example.test/?device_uid=feeder-qr&claim_code=SCANNED-CODE";
    expect(controller.applyClaimPayload(claimUrl)).toEqual({
      deviceUid: "feeder-qr",
      proofOfPossession: "SCANNED-CODE"
    });
    expect(document.querySelector("[name='device_uid']").value).toBe("feeder-qr");
    expect(document.querySelector("[name='pairing_code']").value).toBe("SCANNED-CODE");

    expect(await controller.scanClaimQr({ name: "claim.png" })).toBeNull();
    expect(document.getElementById("pairingMessage").textContent).toContain("not supported");

    const bitmap = { close: vi.fn() };
    window.createImageBitmap = vi.fn().mockResolvedValue(bitmap);
    window.BarcodeDetector = class BarcodeDetector {
      async detect() {
        return [{ rawValue: claimUrl }];
      }
    };
    expect(await controller.scanClaimQr({ name: "claim.png" })).toEqual({
      deviceUid: "feeder-qr",
      proofOfPossession: "SCANNED-CODE"
    });
    expect(bitmap.close).toHaveBeenCalled();
  });

  it("calls the authenticated feeding schedule contracts", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ id: 7 }, 201))
      .mockResolvedValueOnce(response({ id: 7, enabled: false }))
      .mockResolvedValueOnce(response(null, 204));
    const schedule = {
      name: "Morning",
      hour: 8,
      minute: 30,
      days_of_week: [0, 1, 2, 3, 4],
      timezone: "America/New_York",
      grace_minutes: 10,
      enabled: true
    };
    await createFeedingSchedule("feeder/7", schedule, "jwt", { fetchImpl });
    await updateFeedingSchedule(7, { enabled: false }, "jwt", { fetchImpl });
    await deleteFeedingSchedule(7, "jwt", { fetchImpl });
    expect(fetchImpl.mock.calls.map((call) => [call[0], call[1].method])).toEqual([
      [expect.stringContaining("/devices/feeder%2F7/schedules"), "POST"],
      [expect.stringContaining("/schedules/7"), "PATCH"],
      [expect.stringContaining("/schedules/7"), "DELETE"]
    ]);
    expect(fetchImpl.mock.calls.every((call) => call[1].headers.Authorization === "Bearer jwt")).toBe(true);
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
    expect(document.getElementById("sceneTemperature").textContent).toBe("4.3");
    expect(document.getElementById("sceneCoolingStatus").textContent).toBe("ON");
    expect(document.getElementById("scenePumpStatus").textContent).toBe("FEEDING");
    expect(document.getElementById("temperatureCard").dataset.level).toBe("normal");
    expect(document.getElementById("sceneTemperatureCard").dataset.level).toBe("normal");
    expect(document.getElementById("coolingCard").dataset.active).toBe("true");
    expect(document.getElementById("pumpCard").dataset.state).toBe("feeding");
    expect(document.getElementById("heartbeatCard").dataset.online).toBe("true");
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
    expect(document.getElementById("temperatureCard").dataset.level).toBeUndefined();
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
      if (url.endsWith("/users/me")) return response({ username: "alice", role: "operator" });
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
      if (url.includes("/schedules")) return response([]);
      throw new Error(`Unexpected request ${method} ${url}`);
    });
  }

  it("plays and pauses the optional aquarium moment without changing device controls", async () => {
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl: vi.fn(),
      storage: sessionStorage,
      chartFactory: null
    });
    const video = document.getElementById("aquariumVideo");
    let paused = true;
    Object.defineProperty(video, "paused", { configurable: true, get: () => paused });
    video.play = vi.fn().mockImplementation(() => {
      paused = false;
      return Promise.resolve();
    });
    video.pause = vi.fn().mockImplementation(() => {
      paused = true;
    });

    await controller.initialize();
    document.getElementById("aquariumPlayButton").click();
    await vi.waitFor(() => expect(document.getElementById("aquariumPlayButton").textContent).toContain("Pause"));
    expect(document.getElementById("conciergeShowcase").dataset.playing).toBe("true");
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(true);

    document.getElementById("aquariumPlayButton").click();
    await vi.waitFor(() => expect(document.getElementById("aquariumPlayButton").textContent).toContain("Play"));
    expect(document.getElementById("conciergeShowcase").dataset.playing).toBe("false");
    expect(document.querySelector(".aquarium-hero").dataset.playing).toBe("false");
  });

  it("renders the next active feeding schedule without changing the API shape", () => {
    expect(renderNextSchedule(document, [])).toBeNull();
    expect(document.getElementById("nextFeedTime").textContent).toBe("Not scheduled");
    const schedule = renderNextSchedule(document, [{
      id: 4,
      name: "Evening meal",
      hour: 18,
      minute: 5,
      timezone: "America/New_York",
      enabled: true
    }]);
    expect(schedule.id).toBe(4);
    expect(document.getElementById("nextFeedTime").textContent).toBe("6:05 PM");
    expect(document.getElementById("nextFeedName").textContent).toContain("Evening meal");
  });

  it("builds an accessible command dialog that waits for explicit confirmation", async () => {
    const manager = createCommandDialog(document);
    const trigger = document.querySelector("[data-command='FEED_NOW']");
    trigger.disabled = false;
    trigger.focus();
    const decision = manager.confirm("Feed now?", {
      commandType: "FEED_NOW",
      deviceUid: "feeder-001",
      payload: { duration_ms: 1500 },
      lastFeedingAt: "2026-01-01T12:00:00Z"
    });
    expect(document.getElementById("commandDialog").open).toBe(true);
    expect(document.getElementById("commandDialogDevice").textContent).toBe("feeder-001");
    expect(document.getElementById("commandDialogDuration").textContent).toBe("1500 ms");
    document.getElementById("commandDialogConfirm").click();
    await expect(decision).resolves.toBe(true);
    expect(document.getElementById("commandDialogCancel").disabled).toBe(true);
    expect(document.getElementById("commandDialogFeedback").textContent).toContain("signed command");
    manager.complete();
    expect(document.getElementById("commandDialog").open).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });

  it("supports an empty customer account, pairing, and secure unpairing", async () => {
    let paired = false;
    const customerDevice = { id: 7, device_uid: "customer-feeder", name: "Home feeder" };
    const fetchImpl = vi.fn(async (url, options) => {
      const method = options.method || "GET";
      if (url.endsWith("/auth/token")) return response({ access_token: "customer-jwt" });
      if (url.endsWith("/users/me")) {
        return response({ username: "person@example.com", email: "person@example.com", role: "customer" });
      }
      if (url.endsWith("/devices") && method === "GET") return response(paired ? [customerDevice] : []);
      if (url.endsWith("/devices/claim") && method === "POST") {
        paired = true;
        return response(customerDevice);
      }
      if (url.endsWith("/devices/customer-feeder/transfer") && method === "POST") {
        return response({
          device_uid: "customer-feeder",
          claim_url: "https://feeder.test/?device_uid=customer-feeder&claim_code=TRANSFER-CODE",
          expires_at: "2026-01-01T13:00:00Z"
        });
      }
      if (url.endsWith("/devices/customer-feeder/transfer") && method === "DELETE") {
        return response({ message: "cancelled" });
      }
      if (url.includes("/pairing") && method === "DELETE") {
        paired = false;
        return response({ ...customerDevice, pairing_code: "NEW-PAIR-CODE" });
      }
      if (url.includes("/device-status")) {
        return response({
          online: true,
          temperature_c: 4.2,
          cooling_on: false,
          pump_state: "IDLE",
          last_seen: "2026-01-01T12:00:00Z",
          alert_level: "normal",
          alert_message: null
        });
      }
      if (url.includes("/telemetry") || url.includes("/alerts") || url.includes("/commands") || url.includes("/schedules")) {
        return response([]);
      }
      throw new Error(`Unexpected request ${method} ${url}`);
    });
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      chartFactory: null
    });

    await controller.initialize();
    expect(await controller.login("person@example.com", "SecureFeeder42")).toBe(true);
    expect(controller.state.deviceUid).toBeNull();
    expect(document.getElementById("customerDevicePanel").hidden).toBe(false);
    expect(document.getElementById("devicePicker").hidden).toBe(true);
    expect(document.getElementById("systemHealth").textContent).toBe("Pair a Feeder");

    expect(await controller.pairDevice("customer-feeder", "PAIR-CODE")).toBe(true);
    expect(controller.state.deviceUid).toBe("customer-feeder");
    expect(document.getElementById("devicePicker").hidden).toBe(false);
    expect(document.getElementById("unpairDeviceButton").hidden).toBe(false);
    expect(document.getElementById("transferDeviceButton").hidden).toBe(false);
    expect((await controller.createTransferOffer()).claim_url).toContain("TRANSFER-CODE");
    expect(await controller.cancelTransferOffer()).toBe(true);

    window.confirm = vi.fn().mockReturnValue(true);
    expect(await controller.unpairSelectedDevice()).toBe(true);
    expect(controller.state.deviceUid).toBeNull();
    expect(document.getElementById("pairingMessage").textContent).toContain("NEW-PAIR-CODE");
  });

  it("lets an account create, pause, and delete an automatic feeding schedule", async () => {
    let schedules = [];
    const baseApi = controllerApi();
    const fetchImpl = vi.fn(async (url, options) => {
      const method = options.method || "GET";
      if (url.includes("/devices/feeder-001/schedules") && method === "GET") return response(schedules);
      if (url.includes("/devices/feeder-001/schedules") && method === "POST") {
        const body = JSON.parse(options.body);
        schedules = [{ id: 1, device_id: 1, ...body, days_of_week: body.days_of_week.join(",") }];
        return response(schedules[0], 201);
      }
      if (url.includes("/schedules/1") && method === "PATCH") {
        schedules = [{ ...schedules[0], ...JSON.parse(options.body) }];
        return response(schedules[0]);
      }
      if (url.includes("/schedules/1") && method === "DELETE") {
        schedules = [];
        return response(null, 204);
      }
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

    const form = document.getElementById("scheduleForm");
    form.elements.namedItem("timezone").value = "America/New_York";
    expect(await controller.createSchedule(new FormData(form))).toBe(true);
    expect(controller.state.schedules).toHaveLength(1);
    expect(document.getElementById("scheduleList").textContent).toContain("Daily feeding");
    expect(await controller.toggleSchedule(1)).toBe(true);
    expect(controller.state.schedules[0].enabled).toBe(false);

    window.confirm = vi.fn().mockReturnValue(true);
    expect(await controller.removeSchedule(1)).toBe(true);
    expect(controller.state.schedules).toEqual([]);
    expect(document.getElementById("scheduleMessage").textContent).toContain("deleted");
  });

  it("keeps the command dialog open when the device rejects a command", async () => {
    const baseApi = controllerApi();
    const fetchImpl = vi.fn(async (url, options) => {
      if (url.includes("/commands") && options.method === "POST") {
        return response({ detail: "Device rejected the command" }, 409);
      }
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
    document.querySelector("[data-command='FEED_NOW']").click();
    await vi.waitFor(() => expect(document.getElementById("commandDialog").open).toBe(true));
    document.getElementById("commandDialogConfirm").click();

    await vi.waitFor(() => expect(document.getElementById("commandDialogFeedback").textContent)
      .toContain("Device rejected the command"));
    expect(document.getElementById("commandDialog").open).toBe(true);
    expect(document.getElementById("commandDialogCancel").disabled).toBe(false);
    expect(document.getElementById("commandDialogConfirm").disabled).toBe(true);

    document.getElementById("commandDialogCancel").click();
    expect(document.getElementById("commandDialog").open).toBe(false);
  });

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
    expect(document.querySelector("[data-scene-command='FEED_NOW']").disabled).toBe(false);

    const select = document.getElementById("deviceSelect");
    select.value = "feeder-002";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => expect(fetchImpl.mock.calls.some((call) => call[0].includes("device_uid=feeder-002"))).toBe(true));
    await vi.waitFor(() => expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(false));

    document.getElementById("feedDuration").value = "1500";
    document.querySelector("[data-command='FEED_NOW']").click();
    await vi.waitFor(() => expect(document.getElementById("commandMessage").textContent).toContain("accepted"));
    expect(document.getElementById("butlerCard").dataset.state).toBe("success");
    expect(document.getElementById("butlerStatus").textContent).toContain("Feeding command sent");
    expect(document.getElementById("conciergeShowcase").dataset.feeding).toBe("true");
    expect(confirmImpl).toHaveBeenCalled();
    expect(confirmImpl.mock.calls.at(-1)[0]).toContain("1500 ms");
    const commandPost = fetchImpl.mock.calls.find((call) =>
      call[0].includes("/commands") && call[1].method === "POST"
    );
    expect(JSON.parse(commandPost[1].body).payload).toEqual({ duration_ms: 1500 });

    document.querySelector("[data-scene-command='FEED_NOW']").click();
    await vi.waitFor(() => expect(confirmImpl).toHaveBeenCalledTimes(2));
    expect(confirmImpl.mock.calls.at(-1)[0]).toContain("1500 ms");
    await vi.waitFor(() => expect(document.querySelector("[data-scene-command='FEED_NOW']").disabled).toBe(false));

    document.getElementById("cleanDuration").value = "499";
    document.querySelector("[data-command='CLEAN_PUMP']").click();
    expect(document.getElementById("commandMessage").textContent).toContain("between 500 and 60000 ms");
    expect(confirmImpl).toHaveBeenCalledTimes(2);

    document.getElementById("logoutButton").click();
    expect(document.body.dataset.authenticated).toBe("false");
    expect(sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(true);
    expect(document.querySelector("[data-scene-command='FEED_NOW']").disabled).toBe(true);
    expect(document.getElementById("feedDuration").disabled).toBe(true);
    expect(document.getElementById("temperature").textContent).toBe("--");
    expect(document.getElementById("sceneTemperature").textContent).toBe("--");
    expect(document.getElementById("systemHealth").textContent).toBe("Sign In Required");
    expect(document.getElementById("monitoringMessage").textContent).toContain("Authenticate");
    expect(document.getElementById("butlerStatus").textContent).toBe("Standing by");
  });

  it("stops the feeding animation after the configured feeding duration", async () => {
    vi.useFakeTimers();
    try {
      const controller = createDashboardController({
        documentRef: document,
        fetchImpl: controllerApi(),
        storage: sessionStorage,
        confirmImpl: vi.fn().mockReturnValue(true),
        chartFactory: null
      });

      await controller.initialize();
      await controller.login("alice", "password");
      await controller.issueCommand("FEED_NOW", { duration_ms: 750 });

      expect(document.getElementById("conciergeShowcase").dataset.feeding).toBe("true");
      await vi.advanceTimersByTimeAsync(749);
      expect(document.getElementById("conciergeShowcase").dataset.feeding).toBe("true");
      await vi.advanceTimersByTimeAsync(1);
      expect(document.getElementById("conciergeShowcase").dataset.feeding).toBe("false");
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers one-click demo access and labels simulated controls", async () => {
    const fetchImpl = vi.fn(async (url, options) => {
      const method = options.method || "GET";
      if (url.endsWith("/auth/token")) {
        expect(options.body.toString()).toContain("username=demo");
        expect(options.body.toString()).toContain("password=smartfishdemo");
        return response({ access_token: "demo-jwt" });
      }
      if (url.endsWith("/users/me")) return response({ username: "demo", role: "demo" });
      if (url.endsWith("/devices") && method === "GET") {
        return response([{ id: -1, device_uid: "demo-feeder-001", name: "Public Demo Feeder" }]);
      }
      if (url.includes("/device-status")) {
        return response({
          online: true,
          temperature_c: 4.6,
          cooling_on: false,
          pump_state: "IDLE",
          last_seen: "2026-01-01T12:00:00Z",
          alert_level: "normal",
          alert_message: "Public demo online"
        });
      }
      if (url.includes("/telemetry") || url.includes("/alerts") || url.includes("/commands")) {
        return response([]);
      }
      throw new Error(`Unexpected request ${method} ${url}`);
    });
    const controller = createDashboardController({
      documentRef: document,
      fetchImpl,
      storage: sessionStorage,
      chartFactory: null
    });
    await controller.initialize();
    document.getElementById("demoLoginButton").click();
    await vi.waitFor(() => expect(document.body.dataset.accountRole).toBe("demo"));
    expect(controller.state.demo).toBe(true);
    expect(document.getElementById("demoModeBanner").hidden).toBe(false);
    expect(document.getElementById("demoAccess").hidden).toBe(true);
    expect(document.getElementById("controlState").textContent).toContain("never reach physical hardware");
    expect(document.querySelector("[data-command='FEED_NOW']").disabled).toBe(false);
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
