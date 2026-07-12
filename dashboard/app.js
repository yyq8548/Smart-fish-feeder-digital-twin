import "./chart.js";

const API_BASE = globalThis.FISH_FEEDER_API_URL ||
  (globalThis.location?.port === "8080" ? "/api" : "http://127.0.0.1:8000");

export const TOKEN_STORAGE_KEY = "fish-feeder-operator-token";
export const MIN_ACTUATION_DURATION_MS = 500;
export const MAX_ACTUATION_DURATION_MS = 60_000;
export const DEFAULT_ACTUATION_DURATION_MS = 1_000;
const DEFAULT_DEVICE_UID = "feeder-001";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function defaultStorage() {
  return globalThis.sessionStorage ?? null;
}

export function formatTime(value) {
  if (!value) return "--";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function setHealth(element, level, message) {
  if (!element) return;
  element.textContent = message || level;
  element.dataset.level = level;
}

function setNotice(element, message, level = "info") {
  if (!element) return;
  element.textContent = message;
  element.dataset.level = level;
  element.hidden = !message;
}

export function renderAlerts(element, alerts) {
  if (!element) return;
  element.replaceChildren();
  if (alerts.length === 0) {
    const item = document.createElement("li");
    item.textContent = "No alerts for this device.";
    element.appendChild(item);
    return;
  }
  for (const alert of alerts) {
    const item = document.createElement("li");
    const level = alert.level ?? alert.alert_level ?? "unknown";
    const message = alert.message ?? alert.alert_message ?? "No details";
    const category = alert.category ? ` ${alert.category}:` : ":";
    item.textContent = `[${formatTime(alert.created_at)}] ${level.toUpperCase()}${category} ${message}`;
    element.appendChild(item);
  }
}

export function renderCommands(element, commands) {
  if (!element) return;
  element.replaceChildren();
  if (commands.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No commands have been issued for this device.";
    element.appendChild(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "command-list";
  for (const command of commands) {
    const item = document.createElement("li");
    const heading = document.createElement("div");
    const type = document.createElement("strong");
    const status = document.createElement("span");
    const details = document.createElement("p");
    type.textContent = command.command_type;
    status.className = "command-status";
    status.dataset.status = String(command.status).toLowerCase();
    status.textContent = command.status;
    heading.append(type, status);
    const expiry = command.expires_at ? ` · expires ${formatTime(command.expires_at)}` : "";
    details.textContent = `${formatTime(command.created_at)}${expiry} · ${command.result || "Awaiting terminal result"}`;
    item.append(heading, details);
    list.appendChild(item);
  }
  element.appendChild(list);
}

export function populateDeviceSelect(element, devices, preferredUid = DEFAULT_DEVICE_UID) {
  if (!element) return preferredUid;
  element.replaceChildren();
  for (const device of devices) {
    const option = document.createElement("option");
    option.value = device.device_uid;
    option.dataset.deviceId = String(device.id);
    option.textContent = `${device.name} (${device.device_uid})`;
    element.appendChild(option);
  }
  const selected = devices.find((device) => device.device_uid === preferredUid) ?? devices[0];
  if (selected) element.value = selected.device_uid;
  return selected?.device_uid ?? preferredUid;
}

export async function requestJson(
  path,
  { fetchImpl = fetch, method = "GET", token = null, jsonBody = null, formBody = null } = {}
) {
  const headers = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (jsonBody !== null) headers["Content-Type"] = "application/json";
  if (formBody !== null) headers["Content-Type"] = "application/x-www-form-urlencoded";
  const response = await fetchImpl(`${API_BASE}${path}`, {
    method,
    headers,
    body: jsonBody === null ? formBody : JSON.stringify(jsonBody)
  });
  let payload = null;
  try {
    payload = response.status === 204 ? null : await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new ApiError(payload?.detail || `Request failed with status ${response.status}`, response.status);
  }
  return payload;
}

export async function authenticateOperator(
  username,
  password,
  { fetchImpl = fetch, storage = defaultStorage() } = {}
) {
  const form = new URLSearchParams({ username, password });
  const response = await requestJson("/auth/token", { fetchImpl, method: "POST", formBody: form });
  storage?.setItem(TOKEN_STORAGE_KEY, response.access_token);
  return response.access_token;
}

export function clearOperatorSession(storage = defaultStorage()) {
  storage?.removeItem(TOKEN_STORAGE_KEY);
}

export function parseActuationDuration(value) {
  const normalized = String(value).trim();
  if (!/^\d+$/.test(normalized)) {
    throw new Error("Duration must be a whole number of milliseconds.");
  }
  const duration = Number(normalized);
  if (
    !Number.isSafeInteger(duration) ||
    duration < MIN_ACTUATION_DURATION_MS ||
    duration > MAX_ACTUATION_DURATION_MS
  ) {
    throw new Error(`Duration must be between ${MIN_ACTUATION_DURATION_MS} and ${MAX_ACTUATION_DURATION_MS} ms.`);
  }
  return duration;
}

function normalizeCommandPayload(commandType, payload) {
  if (commandType !== "FEED_NOW" && commandType !== "CLEAN_PUMP") return payload;
  const duration = payload.duration_ms ?? DEFAULT_ACTUATION_DURATION_MS;
  return { ...payload, duration_ms: parseActuationDuration(duration) };
}

function commandConfirmation(commandType, deviceUid, payload) {
  if (commandType === "FEED_NOW") {
    return `Feed now on ${deviceUid} with a ${payload.duration_ms} ms forward-pump phase? The wait and reverse-clean cycle follow automatically.`;
  }
  if (commandType === "CLEAN_PUMP") {
    return `Run the reverse-pump cleaning cycle on ${deviceUid} for ${payload.duration_ms} ms?`;
  }
  const mode = payload.mode.replaceAll("_", " ").toLowerCase();
  return `Set cooling on ${deviceUid} to ${mode}?`;
}

function newIdempotencyKey(commandType) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `dashboard-${commandType.toLowerCase()}-${suffix}`;
}

export async function issueDeviceCommand({
  deviceUid,
  commandType,
  payload = {},
  token,
  fetchImpl = fetch,
  confirmImpl = globalThis.confirm,
  idempotencyKey = newIdempotencyKey(commandType)
}) {
  const normalizedPayload = normalizeCommandPayload(commandType, payload);
  if (!confirmImpl(commandConfirmation(commandType, deviceUid, normalizedPayload))) {
    return { cancelled: true, command: null };
  }
  const command = await requestJson(`/devices/${encodeURIComponent(deviceUid)}/commands`, {
    fetchImpl,
    method: "POST",
    token,
    jsonBody: { idempotency_key: idempotencyKey, command_type: commandType, payload: normalizedPayload }
  });
  return { cancelled: false, command };
}

function resetTelemetry(documentRef) {
  for (const id of ["temperature", "coolingStatus", "pumpStatus", "lastSeen"]) {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = "--";
  }
}

function clearChart(chart) {
  if (!chart) return;
  chart.data.labels = [];
  chart.data.datasets[0].data = [];
  chart.update();
}

export async function refreshDashboard({
  documentRef = document,
  fetchImpl = fetch,
  chart = null,
  deviceUid = DEFAULT_DEVICE_UID,
  deviceId = null,
  token = null,
  shouldApply = () => true
} = {}) {
  const health = documentRef.getElementById("systemHealth");
  const monitoringMessage = documentRef.getElementById("monitoringMessage");
  const encodedUid = encodeURIComponent(deviceUid);
  try {
    const [status, telemetry, alerts] = await Promise.all([
      requestJson(`/device-status?device_uid=${encodedUid}`, { fetchImpl, token }),
      requestJson(`/telemetry?limit=30&device_uid=${encodedUid}`, { fetchImpl, token }),
      requestJson(`/alerts?limit=20&device_uid=${encodedUid}`, { fetchImpl, token })
    ]);
    if (!shouldApply()) return null;
    documentRef.getElementById("temperature").textContent = status.temperature_c === null ? "--" : Number(status.temperature_c).toFixed(1);
    documentRef.getElementById("coolingStatus").textContent = status.cooling_on === null ? "--" : status.cooling_on ? "ON" : "OFF";
    documentRef.getElementById("pumpStatus").textContent = status.pump_state || "--";
    documentRef.getElementById("lastSeen").textContent = formatTime(status.last_seen);
    setHealth(health, status.alert_level, status.alert_message || (status.online ? "System Normal" : "Device Offline"));
    setNotice(monitoringMessage, status.online ? "" : "Live telemetry is unavailable. Commands are disabled while the device is offline.", "warning");
    const matchingAlerts = deviceId === null ? alerts : alerts.filter((alert) => alert.device_id === deviceId);
    renderAlerts(documentRef.getElementById("alertLog"), matchingAlerts);
    if (chart) {
      chart.data.labels = telemetry.map((item) => formatTime(item.recorded_at ?? item.created_at));
      chart.data.datasets[0].data = telemetry.map((item) => item.temperature_c);
      chart.update();
    }
    return status;
  } catch (error) {
    if (!shouldApply()) return null;
    resetTelemetry(documentRef);
    clearChart(chart);
    setHealth(health, "unknown", "API Offline");
    setNotice(monitoringMessage, `Monitoring request failed: ${error.message}`, "critical");
    renderAlerts(documentRef.getElementById("alertLog"), []);
    return null;
  }
}

function createChart(documentRef, chartFactory) {
  const canvas = documentRef.getElementById("tempChart");
  if (!chartFactory || !canvas) return null;
  return new chartFactory(canvas, {
    type: "line",
    data: { labels: [], datasets: [{ label: "Reservoir Temperature (°C)", data: [], tension: 0.35 }] },
    options: { responsive: true, scales: { y: { suggestedMin: 2, suggestedMax: 7 } } }
  });
}

export function createDashboardController({
  documentRef = document,
  fetchImpl = fetch,
  storage = defaultStorage(),
  confirmImpl = globalThis.confirm,
  chartFactory = globalThis.Chart
} = {}) {
  const state = {
    token: storage?.getItem(TOKEN_STORAGE_KEY) ?? null,
    deviceUid: DEFAULT_DEVICE_UID,
    deviceId: null,
    online: false,
    busy: false,
    viewEpoch: 0,
    monitorRequestId: 0,
    commandRequestId: 0,
    monitoringKey: null,
    monitoringPromise: null
  };
  const chart = createChart(documentRef, chartFactory);

  function invalidateView() {
    state.viewEpoch += 1;
    state.monitorRequestId += 1;
    state.commandRequestId += 1;
  }

  function isCurrentView(viewEpoch, token, deviceUid) {
    return state.viewEpoch === viewEpoch && state.token === token && state.deviceUid === deviceUid;
  }

  function setAuthenticated(authenticated, username = "") {
    const loginForm = documentRef.getElementById("loginForm");
    const operatorSession = documentRef.getElementById("operatorSession");
    if (loginForm) loginForm.hidden = authenticated;
    if (operatorSession) operatorSession.hidden = !authenticated;
    const usernameElement = documentRef.getElementById("operatorUsername");
    if (usernameElement) usernameElement.textContent = username;
    documentRef.body.dataset.authenticated = String(authenticated);
  }

  function updateControlAvailability() {
    const enabled = Boolean(state.token && state.online && !state.busy);
    for (const button of documentRef.querySelectorAll("[data-command]")) button.disabled = !enabled;
    for (const input of documentRef.querySelectorAll("[data-duration-control]")) input.disabled = !enabled;
    const message = !state.token
      ? "Sign in as an operator to issue commands."
      : !state.online
        ? "Commands are disabled because the selected device is offline."
        : state.busy
          ? "Submitting command…"
          : "Device is online. Every command requires confirmation.";
    setNotice(documentRef.getElementById("controlState"), message, enabled ? "normal" : "warning");
  }

  async function refreshCommands() {
    const requestId = ++state.commandRequestId;
    const viewEpoch = state.viewEpoch;
    const token = state.token;
    const deviceUid = state.deviceUid;
    if (!token) {
      renderCommands(documentRef.getElementById("commandHistory"), []);
      return [];
    }
    try {
      const commands = await requestJson(`/devices/${encodeURIComponent(deviceUid)}/commands?limit=20`, {
        fetchImpl,
        token
      });
      if (!isCurrentView(viewEpoch, token, deviceUid) || requestId !== state.commandRequestId) return [];
      renderCommands(documentRef.getElementById("commandHistory"), commands);
      return commands;
    } catch (error) {
      if (!isCurrentView(viewEpoch, token, deviceUid) || requestId !== state.commandRequestId) return [];
      if (error.status === 401) logout("Your operator session expired. Please sign in again.");
      else setNotice(documentRef.getElementById("commandMessage"), `Command history failed: ${error.message}`, "critical");
      return [];
    }
  }

  async function refreshLatest() {
    const requestId = ++state.monitorRequestId;
    const viewEpoch = state.viewEpoch;
    const token = state.token;
    const deviceUid = state.deviceUid;
    const deviceId = state.deviceId;
    const requestIsCurrent = () =>
      isCurrentView(viewEpoch, token, deviceUid) && requestId === state.monitorRequestId;
    if (!token) {
      state.online = false;
      resetTelemetry(documentRef);
      clearChart(chart);
      setHealth(documentRef.getElementById("systemHealth"), "unknown", "Sign In Required");
      setNotice(documentRef.getElementById("monitoringMessage"), "Authenticate to view device telemetry and alerts.");
      renderAlerts(documentRef.getElementById("alertLog"), []);
      updateControlAvailability();
      return null;
    }
    const status = await refreshDashboard({
      documentRef,
      fetchImpl,
      chart,
      deviceUid,
      deviceId,
      token,
      shouldApply: requestIsCurrent
    });
    if (!requestIsCurrent()) return null;
    state.online = Boolean(status?.online);
    updateControlAvailability();
    if (token) await refreshCommands();
    return status;
  }

  async function refresh() {
    const monitoringKey = `${state.viewEpoch}:${state.deviceUid}:${state.token ?? "signed-out"}`;
    if (state.monitoringPromise && state.monitoringKey === monitoringKey) return state.monitoringPromise;
    const monitoringPromise = refreshLatest();
    state.monitoringKey = monitoringKey;
    state.monitoringPromise = monitoringPromise;
    try {
      return await monitoringPromise;
    } finally {
      if (state.monitoringPromise === monitoringPromise) {
        state.monitoringKey = null;
        state.monitoringPromise = null;
      }
    }
  }

  async function loadOperator() {
    if (!state.token) return false;
    const viewEpoch = state.viewEpoch;
    const token = state.token;
    try {
      const [user, devices] = await Promise.all([
        requestJson("/users/me", { fetchImpl, token }),
        requestJson("/devices", { fetchImpl, token })
      ]);
      if (viewEpoch !== state.viewEpoch || token !== state.token) return false;
      if (devices.length === 0) throw new Error("No devices are provisioned for this operator.");
      state.deviceUid = populateDeviceSelect(documentRef.getElementById("deviceSelect"), devices, state.deviceUid);
      state.deviceId = devices.find((device) => device.device_uid === state.deviceUid)?.id ?? null;
      setAuthenticated(true, user.username);
      setNotice(documentRef.getElementById("loginMessage"), "", "normal");
      await refresh();
      return true;
    } catch (error) {
      if (viewEpoch !== state.viewEpoch || token !== state.token) return false;
      if (error.status === 401) logout("Your saved session is no longer valid.");
      else setNotice(documentRef.getElementById("loginMessage"), error.message, "critical");
      return false;
    }
  }

  async function login(username, password) {
    invalidateView();
    const viewEpoch = state.viewEpoch;
    setNotice(documentRef.getElementById("loginMessage"), "Signing in…");
    try {
      const token = await authenticateOperator(username, password, { fetchImpl, storage });
      if (viewEpoch !== state.viewEpoch) {
        clearOperatorSession(storage);
        return false;
      }
      state.token = token;
      return await loadOperator();
    } catch (error) {
      if (viewEpoch !== state.viewEpoch) return false;
      state.token = null;
      clearOperatorSession(storage);
      setAuthenticated(false);
      setNotice(documentRef.getElementById("loginMessage"), error.message, "critical");
      updateControlAvailability();
      return false;
    }
  }

  function logout(message = "Signed out. Sign in to resume monitoring.") {
    invalidateView();
    state.token = null;
    state.deviceId = null;
    state.online = false;
    clearOperatorSession(storage);
    setAuthenticated(false);
    resetTelemetry(documentRef);
    clearChart(chart);
    setHealth(documentRef.getElementById("systemHealth"), "unknown", "Sign In Required");
    setNotice(documentRef.getElementById("monitoringMessage"), "Authenticate to view device telemetry and alerts.");
    renderAlerts(documentRef.getElementById("alertLog"), []);
    renderCommands(documentRef.getElementById("commandHistory"), []);
    setNotice(documentRef.getElementById("loginMessage"), message);
    updateControlAvailability();
  }

  async function issueCommand(commandType, payload = {}) {
    if (!state.token || !state.online || state.busy) return null;
    const viewEpoch = state.viewEpoch;
    const token = state.token;
    const deviceUid = state.deviceUid;
    state.busy = true;
    updateControlAvailability();
    setNotice(documentRef.getElementById("commandMessage"), "", "normal");
    try {
      const result = await issueDeviceCommand({
        deviceUid,
        commandType,
        payload,
        token,
        fetchImpl,
        confirmImpl
      });
      if (!isCurrentView(viewEpoch, token, deviceUid)) return result;
      if (!result.cancelled) {
        setNotice(documentRef.getElementById("commandMessage"), `Command ${result.command.id} accepted.`, "normal");
        await refreshCommands();
      }
      return result;
    } catch (error) {
      if (!isCurrentView(viewEpoch, token, deviceUid)) return null;
      if (error.status === 401) logout("Your operator session expired. Please sign in again.");
      else setNotice(documentRef.getElementById("commandMessage"), `Command failed: ${error.message}`, "critical");
      return null;
    } finally {
      state.busy = false;
      updateControlAvailability();
    }
  }

  function bindEvents() {
    documentRef.getElementById("loginForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const formElement = event.currentTarget;
      login(String(form.get("username") || ""), String(form.get("password") || "")).then((authenticated) => {
        if (authenticated) formElement.reset();
      });
    });
    documentRef.getElementById("logoutButton")?.addEventListener("click", () => logout());
    documentRef.getElementById("deviceSelect")?.addEventListener("change", (event) => {
      invalidateView();
      const selected = event.currentTarget.selectedOptions[0];
      state.deviceUid = event.currentTarget.value;
      state.deviceId = selected?.dataset.deviceId ? Number(selected.dataset.deviceId) : null;
      state.online = false;
      resetTelemetry(documentRef);
      clearChart(chart);
      renderAlerts(documentRef.getElementById("alertLog"), []);
      renderCommands(documentRef.getElementById("commandHistory"), []);
      updateControlAvailability();
      refresh();
    });
    for (const button of documentRef.querySelectorAll("[data-command]")) {
      button.addEventListener("click", () => {
        let payload = button.dataset.mode ? { mode: button.dataset.mode } : {};
        if (button.dataset.durationInput) {
          try {
            const input = documentRef.getElementById(button.dataset.durationInput);
            payload = { duration_ms: parseActuationDuration(input?.value ?? "") };
          } catch (error) {
            setNotice(documentRef.getElementById("commandMessage"), error.message, "critical");
            return;
          }
        }
        issueCommand(button.dataset.command, payload);
      });
    }
  }

  async function initialize() {
    bindEvents();
    setAuthenticated(false);
    updateControlAvailability();
    if (state.token) await loadOperator();
    else await refresh();
  }

  return { initialize, issueCommand, loadOperator, login, logout, refresh, refreshCommands, state };
}

export function startDashboard(documentRef = document) {
  const controller = createDashboardController({ documentRef });
  controller.initialize();
  return globalThis.setInterval(() => controller.refresh(), 2000);
}

if (typeof document !== "undefined" && !globalThis.VITEST) startDashboard();
