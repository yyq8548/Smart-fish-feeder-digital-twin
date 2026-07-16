import "./chart.js";

const API_BASE = globalThis.FISH_FEEDER_API_URL ||
  (globalThis.location?.port === "8080" ? "/api" : "http://127.0.0.1:8000");

export const TOKEN_STORAGE_KEY = "fish-feeder-operator-token";
export const DEMO_USERNAME = "demo";
export const DEMO_PASSWORD = "smartfishdemo";
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
    item.className = "alert-item";
    item.dataset.level = String(level).toLowerCase();
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
  return selected?.device_uid ?? null;
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

export function passwordsMatch(password, confirmation) {
  if (password !== confirmation) throw new Error("Passwords do not match.");
  return password;
}

export async function registerCustomer(email, password, { fetchImpl = fetch } = {}) {
  return requestJson("/auth/register", {
    fetchImpl,
    method: "POST",
    jsonBody: { email, password }
  });
}

export async function verifyCustomerEmail(token, { fetchImpl = fetch } = {}) {
  return requestJson("/auth/verify-email", { fetchImpl, method: "POST", jsonBody: { token } });
}

export async function requestCustomerPasswordReset(email, { fetchImpl = fetch } = {}) {
  return requestJson("/auth/password-reset/request", {
    fetchImpl,
    method: "POST",
    jsonBody: { email }
  });
}

export async function confirmCustomerPasswordReset(token, password, { fetchImpl = fetch } = {}) {
  return requestJson("/auth/password-reset/confirm", {
    fetchImpl,
    method: "POST",
    jsonBody: { token, password }
  });
}

export async function pairCustomerDevice(deviceUid, pairingCode, token, { fetchImpl = fetch } = {}) {
  return requestJson("/devices/claim", {
    fetchImpl,
    method: "POST",
    token,
    jsonBody: { device_uid: deviceUid, proof_of_possession: pairingCode }
  });
}

export function parseDeviceClaimPayload(value, baseHref = "http://localhost/") {
  const raw = String(value || "").trim();
  if (!raw) throw new Error("Scan a feeder QR code or enter its setup link.");
  let deviceUid;
  let proofOfPossession;
  if (raw.startsWith("{")) {
    const payload = JSON.parse(raw);
    deviceUid = payload.device_uid;
    proofOfPossession = payload.proof_of_possession || payload.claim_code || payload.pairing_code;
  } else {
    const url = new URL(raw, baseHref);
    deviceUid = url.searchParams.get("device_uid");
    proofOfPossession = url.searchParams.get("claim_code") || url.searchParams.get("pairing_code");
  }
  if (!/^[a-zA-Z0-9_-]{3,80}$/.test(String(deviceUid || ""))) {
    throw new Error("The QR code does not contain a valid feeder ID.");
  }
  if (String(proofOfPossession || "").length < 8 || String(proofOfPossession).length > 64) {
    throw new Error("The QR code does not contain a valid proof-of-possession.");
  }
  return {
    deviceUid: String(deviceUid),
    proofOfPossession: String(proofOfPossession)
  };
}

export async function createDeviceTransfer(deviceUid, token, { fetchImpl = fetch } = {}) {
  return requestJson(`/devices/${encodeURIComponent(deviceUid)}/transfer`, {
    fetchImpl,
    method: "POST",
    token
  });
}

export async function cancelDeviceTransfer(deviceUid, token, { fetchImpl = fetch } = {}) {
  return requestJson(`/devices/${encodeURIComponent(deviceUid)}/transfer`, {
    fetchImpl,
    method: "DELETE",
    token
  });
}

export async function createFeedingSchedule(deviceUid, schedule, token, { fetchImpl = fetch } = {}) {
  return requestJson(`/devices/${encodeURIComponent(deviceUid)}/schedules`, {
    fetchImpl,
    method: "POST",
    token,
    jsonBody: schedule
  });
}

export async function updateFeedingSchedule(scheduleId, updates, token, { fetchImpl = fetch } = {}) {
  return requestJson(`/schedules/${encodeURIComponent(scheduleId)}`, {
    fetchImpl,
    method: "PATCH",
    token,
    jsonBody: updates
  });
}

export async function deleteFeedingSchedule(scheduleId, token, { fetchImpl = fetch } = {}) {
  return requestJson(`/schedules/${encodeURIComponent(scheduleId)}`, {
    fetchImpl,
    method: "DELETE",
    token
  });
}

export function schedulePayloadFromForm(formData) {
  const name = String(formData.get("name") || "").trim();
  const timezone = String(formData.get("timezone") || "").trim();
  const time = String(formData.get("time") || "");
  const [hourText, minuteText] = time.split(":");
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const graceMinutes = Number(formData.get("grace_minutes"));
  const daysOfWeek = formData.getAll("days_of_week").map(Number).sort((left, right) => left - right);
  if (!name) throw new Error("Enter a schedule name.");
  if (!timezone) throw new Error("Enter a valid IANA timezone, such as America/New_York.");
  if (!Number.isInteger(hour) || hour < 0 || hour > 23 || !Number.isInteger(minute) || minute < 0 || minute > 59) {
    throw new Error("Choose a valid feeding time.");
  }
  if (daysOfWeek.length === 0 || daysOfWeek.some((day) => !Number.isInteger(day) || day < 0 || day > 6)) {
    throw new Error("Choose at least one day of the week.");
  }
  if (!Number.isInteger(graceMinutes) || graceMinutes < 1 || graceMinutes > 180) {
    throw new Error("Grace period must be between 1 and 180 minutes.");
  }
  return {
    name,
    hour,
    minute,
    days_of_week: [...new Set(daysOfWeek)],
    timezone,
    grace_minutes: graceMinutes,
    enabled: formData.get("enabled") === "on"
  };
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

function formatScheduleTime(schedule) {
  const hour = Number(schedule.hour);
  const minute = String(schedule.minute).padStart(2, "0");
  const period = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;
  return `${displayHour}:${minute} ${period}`;
}

export function renderNextSchedule(documentRef, schedules) {
  const timeElement = documentRef.getElementById("nextFeedTime");
  const nameElement = documentRef.getElementById("nextFeedName");
  const schedule = schedules.find((item) => item.enabled);
  if (!schedule) {
    if (timeElement) timeElement.textContent = "Not scheduled";
    if (nameElement) nameElement.textContent = "No active feeding schedule";
    return null;
  }
  if (timeElement) timeElement.textContent = formatScheduleTime(schedule);
  if (nameElement) nameElement.textContent = `${schedule.name} · ${schedule.timezone}`;
  return schedule;
}

const SCHEDULE_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function scheduleDays(schedule) {
  const values = Array.isArray(schedule.days_of_week)
    ? schedule.days_of_week
    : String(schedule.days_of_week || "").split(",").filter(Boolean).map(Number);
  return values.filter((day) => Number.isInteger(day) && day >= 0 && day <= 6);
}

function formatScheduleDays(schedule) {
  const days = scheduleDays(schedule);
  if (days.length === 7) return "Every day";
  if (days.join(",") === "0,1,2,3,4") return "Weekdays";
  if (days.join(",") === "5,6") return "Weekends";
  return days.map((day) => SCHEDULE_DAY_NAMES[day]).join(", ") || "No repeat days";
}

export function renderScheduleManager(documentRef, schedules, { canManage = false, emptyMessage = null } = {}) {
  const container = documentRef.getElementById("scheduleList");
  const count = documentRef.getElementById("scheduleCount");
  if (count) count.textContent = schedules.length === 1 ? "1 schedule" : `${schedules.length} schedules`;
  if (!container) return;
  container.replaceChildren();
  if (schedules.length === 0) {
    const empty = documentRef.createElement("p");
    empty.className = "empty-state";
    empty.textContent = emptyMessage || "No feeding schedules yet. Add the first automatic feeding time.";
    container.appendChild(empty);
    return;
  }
  const ordered = [...schedules].sort((left, right) =>
    Number(right.enabled) - Number(left.enabled) || left.hour - right.hour || left.minute - right.minute
  );
  for (const schedule of ordered) {
    const item = documentRef.createElement("article");
    item.className = "schedule-item";
    item.dataset.enabled = String(Boolean(schedule.enabled));

    const main = documentRef.createElement("div");
    main.className = "schedule-item-main";
    const title = documentRef.createElement("div");
    title.className = "schedule-item-title";
    const status = documentRef.createElement("span");
    status.className = "schedule-status-dot";
    status.setAttribute("aria-hidden", "true");
    const name = documentRef.createElement("strong");
    name.textContent = schedule.name;
    title.append(status, name);
    const time = documentRef.createElement("span");
    time.className = "schedule-item-time";
    time.textContent = formatScheduleTime(schedule);
    const meta = documentRef.createElement("span");
    meta.className = "schedule-item-meta";
    meta.textContent = `${formatScheduleDays(schedule)} · ${schedule.timezone} · ${schedule.grace_minutes} min grace`;
    main.append(title, time, meta);

    const actions = documentRef.createElement("div");
    actions.className = "schedule-item-actions";
    const toggle = documentRef.createElement("button");
    toggle.type = "button";
    toggle.className = "schedule-action";
    toggle.dataset.scheduleAction = "toggle";
    toggle.dataset.scheduleId = String(schedule.id);
    toggle.textContent = schedule.enabled ? "Pause" : "Enable";
    toggle.disabled = !canManage;
    toggle.setAttribute("aria-label", `${toggle.textContent} ${schedule.name}`);
    const remove = documentRef.createElement("button");
    remove.type = "button";
    remove.className = "schedule-action delete";
    remove.dataset.scheduleAction = "delete";
    remove.dataset.scheduleId = String(schedule.id);
    remove.textContent = "Delete";
    remove.disabled = !canManage;
    remove.setAttribute("aria-label", `Delete ${schedule.name}`);
    actions.append(toggle, remove);
    item.append(main, actions);
    container.appendChild(item);
  }
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
  lastFeedingAt = null,
  idempotencyKey = newIdempotencyKey(commandType)
}) {
  const normalizedPayload = normalizeCommandPayload(commandType, payload);
  const confirmed = await confirmImpl(commandConfirmation(commandType, deviceUid, normalizedPayload), {
    commandType,
    deviceUid,
    payload: normalizedPayload,
    lastFeedingAt
  });
  if (!confirmed) {
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

export function createCommandDialog(documentRef = document) {
  const dialog = documentRef.getElementById("commandDialog");
  if (!dialog || typeof dialog.showModal !== "function") return null;
  const title = documentRef.getElementById("commandDialogTitle");
  const description = documentRef.getElementById("commandDialogDescription");
  const device = documentRef.getElementById("commandDialogDevice");
  const action = documentRef.getElementById("commandDialogAction");
  const duration = documentRef.getElementById("commandDialogDuration");
  const lastFeed = documentRef.getElementById("commandDialogLastFeed");
  const feedback = documentRef.getElementById("commandDialogFeedback");
  const confirmButton = documentRef.getElementById("commandDialogConfirm");
  const cancelButton = documentRef.getElementById("commandDialogCancel");
  const closeButton = documentRef.getElementById("commandDialogClose");
  if (!confirmButton || !cancelButton || !closeButton) return null;

  let trigger = null;
  let settled = false;
  let finish = null;

  function restoreFocus() {
    const target = trigger;
    trigger = null;
    target?.focus?.();
  }

  function closeDialog() {
    if (dialog.open) dialog.close();
    restoreFocus();
  }

  function resetControls() {
    dialog.dataset.state = "review";
    confirmButton.disabled = false;
    cancelButton.disabled = false;
    closeButton.disabled = false;
    cancelButton.textContent = "Cancel";
    const label = confirmButton.querySelector("span");
    if (label) label.textContent = "Confirm command";
    if (feedback) {
      feedback.hidden = true;
      feedback.textContent = "";
      delete feedback.dataset.level;
    }
  }

  function setPending() {
    dialog.dataset.state = "pending";
    confirmButton.disabled = true;
    cancelButton.disabled = true;
    closeButton.disabled = true;
    const label = confirmButton.querySelector("span");
    if (label) label.textContent = "Sending command…";
    if (feedback) {
      feedback.hidden = false;
      feedback.dataset.level = "normal";
      feedback.textContent = "Sending a signed command to the selected device.";
    }
  }

  const manager = {
    confirm(message, context = {}) {
      resetControls();
      settled = false;
      trigger = documentRef.activeElement;
      const commandType = context.commandType || "COMMAND";
      const isFeed = commandType === "FEED_NOW";
      const isClean = commandType === "CLEAN_PUMP";
      if (title) title.textContent = isFeed ? "Confirm feeding" : isClean ? "Confirm pump cleaning" : "Confirm cooling change";
      if (description) description.textContent = message;
      if (device) device.textContent = context.deviceUid || "--";
      if (action) action.textContent = commandType.replaceAll("_", " ");
      if (duration) duration.textContent = context.payload?.duration_ms ? `${context.payload.duration_ms} ms` : "Not applicable";
      if (lastFeed) lastFeed.textContent = context.lastFeedingAt ? formatTime(context.lastFeedingAt) : "No recent feeding recorded";

      return new Promise((resolve) => {
        finish = (accepted) => {
          if (settled) return;
          settled = true;
          if (accepted) setPending();
          else closeDialog();
          resolve(accepted);
        };
        confirmButton.onclick = () => finish(true);
        cancelButton.onclick = () => finish(false);
        closeButton.onclick = () => finish(false);
        dialog.oncancel = (event) => {
          event.preventDefault();
          if (dialog.dataset.state !== "pending") finish(false);
        };
        dialog.onclick = (event) => {
          if (event.target === dialog && dialog.dataset.state !== "pending") finish(false);
        };
        dialog.showModal();
        confirmButton.focus();
      });
    },
    complete() {
      dialog.dataset.state = "success";
      closeDialog();
    },
    fail(message) {
      dialog.dataset.state = "error";
      confirmButton.disabled = true;
      cancelButton.disabled = false;
      closeButton.disabled = false;
      cancelButton.textContent = "Close";
      cancelButton.onclick = closeDialog;
      closeButton.onclick = closeDialog;
      if (feedback) {
        feedback.hidden = false;
        feedback.dataset.level = "critical";
        feedback.textContent = message;
      }
    },
    dismiss() {
      settled = true;
      closeDialog();
    }
  };
  return manager;
}

export function initializePresentation(documentRef = document, windowRef = globalThis) {
  const topbar = documentRef.getElementById("siteNav");
  const syncTopbar = () => {
    if (topbar) topbar.dataset.compact = String((windowRef.scrollY || 0) > 24);
  };
  syncTopbar();
  windowRef.addEventListener?.("scroll", syncTopbar, { passive: true });

  const reveals = [...documentRef.querySelectorAll("[data-reveal]")];
  const reducedMotion = windowRef.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
  if (reducedMotion || typeof windowRef.IntersectionObserver !== "function") {
    for (const element of reveals) element.classList.add("is-visible");
    return;
  }

  documentRef.body.classList.add("motion-enabled");
  const observer = new windowRef.IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add("is-visible");
      observer.unobserve(entry.target);
    }
  }, { threshold: 0.16 });
  for (const element of reveals) observer.observe(element);

  const coarsePointer = windowRef.matchMedia?.("(pointer: coarse)")?.matches ?? false;
  const hero = documentRef.getElementById("top");
  const video = documentRef.getElementById("aquariumVideo");
  if (!coarsePointer && hero && video) {
    let frameRequested = false;
    const updateParallax = () => {
      frameRequested = false;
      const rect = hero.getBoundingClientRect();
      const viewportHeight = windowRef.innerHeight || 800;
      const progress = Math.max(-1, Math.min(1, (viewportHeight / 2 - (rect.top + rect.height / 2)) / viewportHeight));
      video.style.setProperty("--parallax-y", `${Math.round(progress * 24)}px`);
    };
    const requestParallax = () => {
      if (frameRequested) return;
      frameRequested = true;
      windowRef.requestAnimationFrame(updateParallax);
    };
    requestParallax();
    windowRef.addEventListener("scroll", requestParallax, { passive: true });
  }
}

function resetTelemetry(documentRef) {
  for (const id of [
    "temperature",
    "coolingStatus",
    "pumpStatus",
    "lastSeen",
    "sceneTemperature",
    "sceneCoolingStatus",
    "scenePumpStatus",
    "sceneLastSeen"
  ]) {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = "--";
  }
  for (const id of [
    "temperatureCard",
    "coolingCard",
    "pumpCard",
    "heartbeatCard",
    "sceneTemperatureCard",
    "sceneCoolingCard",
    "scenePumpCard",
    "sceneHeartbeatCard"
  ]) {
    const card = documentRef.getElementById(id);
    if (!card) continue;
    delete card.dataset.level;
    delete card.dataset.active;
    delete card.dataset.state;
    delete card.dataset.online;
  }
}

function setButlerState(documentRef, state, status, message, { feeding = false } = {}) {
  const card = documentRef.getElementById("butlerCard");
  const showcase = documentRef.getElementById("conciergeShowcase");
  if (card) card.dataset.state = state;
  if (showcase) showcase.dataset.feeding = String(feeding);
  const statusElement = documentRef.getElementById("butlerStatus");
  const messageElement = documentRef.getElementById("butlerMessage");
  if (statusElement) statusElement.textContent = status;
  if (messageElement) messageElement.textContent = message;
}

function setFeedingAnimation(documentRef, feeding) {
  const showcase = documentRef.getElementById("conciergeShowcase");
  if (showcase) showcase.dataset.feeding = String(feeding);
}

function playAquariumMoment(documentRef) {
  const video = documentRef.getElementById("aquariumVideo");
  const showcase = documentRef.getElementById("conciergeShowcase");
  if (!video) return;
  showcase?.setAttribute("data-playing", "true");
  showcase?.closest?.(".aquarium-hero")?.setAttribute("data-playing", "true");
  const playResult = video.play?.();
  if (playResult?.catch) playResult.catch(() => {});
}

function setTelemetryText(documentRef, ids, value) {
  for (const id of ids) {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = value;
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
    setTelemetryText(
      documentRef,
      ["temperature", "sceneTemperature"],
      status.temperature_c === null ? "--" : Number(status.temperature_c).toFixed(1)
    );
    setTelemetryText(
      documentRef,
      ["coolingStatus", "sceneCoolingStatus"],
      status.cooling_on === null ? "--" : status.cooling_on ? "ON" : "OFF"
    );
    setTelemetryText(documentRef, ["pumpStatus", "scenePumpStatus"], status.pump_state || "--");
    setTelemetryText(documentRef, ["lastSeen", "sceneLastSeen"], formatTime(status.last_seen));
    const temperatureCard = documentRef.getElementById("temperatureCard");
    const coolingCard = documentRef.getElementById("coolingCard");
    const pumpCard = documentRef.getElementById("pumpCard");
    const heartbeatCard = documentRef.getElementById("heartbeatCard");
    const sceneTemperatureCard = documentRef.getElementById("sceneTemperatureCard");
    const sceneCoolingCard = documentRef.getElementById("sceneCoolingCard");
    const scenePumpCard = documentRef.getElementById("scenePumpCard");
    const sceneHeartbeatCard = documentRef.getElementById("sceneHeartbeatCard");
    if (temperatureCard) temperatureCard.dataset.level = status.alert_level || "unknown";
    if (coolingCard) coolingCard.dataset.active = String(Boolean(status.cooling_on));
    if (pumpCard) pumpCard.dataset.state = String(status.pump_state || "unknown").toLowerCase();
    if (heartbeatCard) heartbeatCard.dataset.online = String(Boolean(status.online));
    if (sceneTemperatureCard) sceneTemperatureCard.dataset.level = status.alert_level || "unknown";
    if (sceneCoolingCard) sceneCoolingCard.dataset.active = String(Boolean(status.cooling_on));
    if (scenePumpCard) scenePumpCard.dataset.state = String(status.pump_state || "unknown").toLowerCase();
    if (sceneHeartbeatCard) sceneHeartbeatCard.dataset.online = String(Boolean(status.online));
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
  confirmImpl = null,
  chartFactory = globalThis.Chart
} = {}) {
  const state = {
    token: storage?.getItem(TOKEN_STORAGE_KEY) ?? null,
    deviceUid: DEFAULT_DEVICE_UID,
    deviceId: null,
    userRole: null,
    online: false,
    demo: false,
    busy: false,
    viewEpoch: 0,
    monitorRequestId: 0,
    commandRequestId: 0,
    monitoringKey: null,
    monitoringPromise: null,
    scheduleUid: null,
    schedules: [],
    scheduleBusy: false,
    lastFeedingAt: null
  };
  const chart = createChart(documentRef, chartFactory);
  const commandDialog = confirmImpl ? null : createCommandDialog(documentRef);
  const resolvedConfirm = confirmImpl ?? commandDialog?.confirm.bind(commandDialog) ?? globalThis.confirm;
  let feedingAnimationTimer = null;

  function stopFeedingAnimation() {
    if (feedingAnimationTimer !== null) {
      globalThis.clearTimeout(feedingAnimationTimer);
      feedingAnimationTimer = null;
    }
    setFeedingAnimation(documentRef, false);
  }

  function scheduleFeedingAnimationStop(durationMs) {
    if (feedingAnimationTimer !== null) globalThis.clearTimeout(feedingAnimationTimer);
    feedingAnimationTimer = globalThis.setTimeout(() => {
      feedingAnimationTimer = null;
      setFeedingAnimation(documentRef, false);
    }, durationMs);
  }

  function invalidateView() {
    state.viewEpoch += 1;
    state.monitorRequestId += 1;
    state.commandRequestId += 1;
  }

  function isCurrentView(viewEpoch, token, deviceUid) {
    return state.viewEpoch === viewEpoch && state.token === token && state.deviceUid === deviceUid;
  }

  function showAuthMode(mode) {
    const modes = {
      signin: "loginForm",
      signup: "registrationForm",
      reset: "passwordResetRequestForm",
      "reset-confirm": "passwordResetConfirmForm"
    };
    for (const [name, id] of Object.entries(modes)) {
      const form = documentRef.getElementById(id);
      if (form) form.hidden = name !== mode;
    }
    for (const button of documentRef.querySelectorAll("[data-auth-mode]")) {
      const selected = button.dataset.authMode === mode;
      if (button.getAttribute("role") === "tab") button.setAttribute("aria-selected", String(selected));
    }
    const demoAccess = documentRef.getElementById("demoAccess");
    if (demoAccess) demoAccess.hidden = mode !== "signin";
  }

  function setCustomerDeviceState(devices) {
    const isCustomer = state.userRole === "customer";
    const hasDevice = devices.length > 0;
    const customerPanel = documentRef.getElementById("customerDevicePanel");
    const devicePicker = documentRef.getElementById("devicePicker");
    const unpairButton = documentRef.getElementById("unpairDeviceButton");
    const transferButton = documentRef.getElementById("transferDeviceButton");
    const cancelTransferButton = documentRef.getElementById("cancelTransferButton");
    const intro = documentRef.getElementById("pairingIntroText");
    if (customerPanel) customerPanel.hidden = !isCustomer;
    if (devicePicker) devicePicker.hidden = isCustomer && !hasDevice;
    if (unpairButton) unpairButton.hidden = !isCustomer || !hasDevice;
    if (transferButton) transferButton.hidden = !isCustomer || !hasDevice;
    if (cancelTransferButton) cancelTransferButton.hidden = !isCustomer || !hasDevice;
    if (intro) {
      intro.textContent = hasDevice
        ? "Pair another feeder, or remove the selected feeder before transferring it to someone else."
        : "Scan the setup QR code, or enter the feeder ID and one-time proof-of-possession.";
    }
  }

  function setAuthenticated(authenticated, username = "", role = "operator") {
    const loginForm = documentRef.getElementById("loginForm");
    const operatorSession = documentRef.getElementById("operatorSession");
    const authModeSwitch = documentRef.getElementById("authModeSwitch");
    if (loginForm) loginForm.hidden = authenticated;
    if (operatorSession) operatorSession.hidden = !authenticated;
    if (authModeSwitch) authModeSwitch.hidden = authenticated;
    const usernameElement = documentRef.getElementById("operatorUsername");
    if (usernameElement) usernameElement.textContent = username;
    const demoAccess = documentRef.getElementById("demoAccess");
    if (demoAccess) demoAccess.hidden = authenticated;
    const demoModeBanner = documentRef.getElementById("demoModeBanner");
    if (demoModeBanner) demoModeBanner.hidden = !authenticated || role !== "demo";
    documentRef.body.dataset.authenticated = String(authenticated);
    documentRef.body.dataset.accountRole = authenticated ? role : "anonymous";
    if (!authenticated) {
      state.userRole = null;
      setCustomerDeviceState([]);
      showAuthMode("signin");
    }
  }

  function updateControlAvailability() {
    const enabled = Boolean(state.token && state.deviceUid && state.online && !state.busy);
    for (const button of documentRef.querySelectorAll("[data-command], [data-scene-command]")) button.disabled = !enabled;
    for (const input of documentRef.querySelectorAll("[data-duration-control]")) input.disabled = !enabled;
    const message = !state.token
      ? "Sign in to issue commands."
      : !state.deviceUid
        ? "Pair a feeder to enable live controls."
      : !state.online
        ? "Commands are disabled because the selected device is offline."
        : state.busy
          ? "Submitting command…"
          : state.demo
            ? "Demo mode: commands complete in the simulator and never reach physical hardware."
            : "Device is online. Every command requires confirmation.";
    setNotice(documentRef.getElementById("controlState"), message, enabled ? "normal" : "warning");
    updateScheduleAvailability();
  }

  function updateScheduleAvailability() {
    const canManage = Boolean(
      state.token && state.deviceUid && state.userRole !== "demo" && !state.scheduleBusy
    );
    const form = documentRef.getElementById("scheduleForm");
    for (const control of form?.querySelectorAll("input, button") ?? []) control.disabled = !canManage;
    for (const button of documentRef.querySelectorAll("[data-schedule-action]")) button.disabled = !canManage;
    const panel = documentRef.getElementById("schedule");
    if (panel) panel.dataset.available = String(canManage);
  }

  async function refreshCommands() {
    const requestId = ++state.commandRequestId;
    const viewEpoch = state.viewEpoch;
    const token = state.token;
    const deviceUid = state.deviceUid;
    if (!token || !deviceUid) {
      renderCommands(documentRef.getElementById("commandHistory"), []);
      return [];
    }
    try {
      const commands = await requestJson(`/devices/${encodeURIComponent(deviceUid)}/commands?limit=20`, {
        fetchImpl,
        token
      });
      if (!isCurrentView(viewEpoch, token, deviceUid) || requestId !== state.commandRequestId) return [];
      const latestFeeding = commands.find((command) => command.command_type === "FEED_NOW");
      state.lastFeedingAt = latestFeeding?.completed_at ?? latestFeeding?.created_at ?? null;
      renderCommands(documentRef.getElementById("commandHistory"), commands);
      return commands;
    } catch (error) {
      if (!isCurrentView(viewEpoch, token, deviceUid) || requestId !== state.commandRequestId) return [];
      if (error.status === 401) logout("Your operator session expired. Please sign in again.");
      else setNotice(documentRef.getElementById("commandMessage"), `Command history failed: ${error.message}`, "critical");
      return [];
    }
  }

  async function refreshSchedule() {
    const viewEpoch = state.viewEpoch;
    const token = state.token;
    const deviceUid = state.deviceUid;
    if (!token || !deviceUid) {
      renderNextSchedule(documentRef, []);
      state.schedules = [];
      renderScheduleManager(documentRef, [], {
        canManage: false,
        emptyMessage: token
          ? "Pair or select a feeder to create an automatic feeding schedule."
          : "Sign in and select a feeder to manage automatic feeding."
      });
      state.scheduleUid = null;
      updateScheduleAvailability();
      return [];
    }
    try {
      const schedules = await requestJson(`/devices/${encodeURIComponent(deviceUid)}/schedules`, {
        fetchImpl,
        token
      });
      if (!isCurrentView(viewEpoch, token, deviceUid)) return [];
      renderNextSchedule(documentRef, schedules);
      state.schedules = schedules;
      renderScheduleManager(documentRef, schedules, {
        canManage: state.userRole !== "demo",
        emptyMessage: state.demo
          ? "The public demo does not create persistent feeding schedules."
          : null
      });
      state.scheduleUid = deviceUid;
      updateScheduleAvailability();
      if (state.demo) {
        setNotice(
          documentRef.getElementById("scheduleMessage"),
          "Demo mode is read-only for schedules. Sign in with a customer account to manage a physical feeder.",
          "warning"
        );
      }
      return schedules;
    } catch (error) {
      if (!isCurrentView(viewEpoch, token, deviceUid)) return [];
      const timeElement = documentRef.getElementById("nextFeedTime");
      const nameElement = documentRef.getElementById("nextFeedName");
      if (timeElement) timeElement.textContent = "Unavailable";
      if (nameElement) nameElement.textContent = "Could not load schedule";
      state.schedules = [];
      renderScheduleManager(documentRef, [], { canManage: false, emptyMessage: "Schedules could not be loaded." });
      setNotice(documentRef.getElementById("scheduleMessage"), `Schedule loading failed: ${error.message}`, "critical");
      updateScheduleAvailability();
      return [];
    }
  }

  async function createSchedule(formData) {
    if (!state.token || !state.deviceUid || state.userRole === "demo" || state.scheduleBusy) return false;
    let payload;
    try {
      payload = schedulePayloadFromForm(formData);
    } catch (error) {
      setNotice(documentRef.getElementById("scheduleMessage"), error.message, "critical");
      return false;
    }
    const deviceUid = state.deviceUid;
    const token = state.token;
    state.scheduleBusy = true;
    updateScheduleAvailability();
    setNotice(documentRef.getElementById("scheduleMessage"), "Saving feeding schedule…");
    try {
      await createFeedingSchedule(deviceUid, payload, token, { fetchImpl });
      if (token !== state.token || deviceUid !== state.deviceUid) return false;
      state.scheduleUid = null;
      await refreshSchedule();
      setNotice(documentRef.getElementById("scheduleMessage"), "Feeding schedule added.", "normal");
      return true;
    } catch (error) {
      if (error.status === 401) logout("Your session expired. Please sign in again.");
      else setNotice(documentRef.getElementById("scheduleMessage"), `Schedule could not be saved: ${error.message}`, "critical");
      return false;
    } finally {
      state.scheduleBusy = false;
      updateScheduleAvailability();
    }
  }

  async function toggleSchedule(scheduleId) {
    const schedule = state.schedules.find((item) => item.id === scheduleId);
    if (!schedule || !state.token || state.userRole === "demo" || state.scheduleBusy) return false;
    state.scheduleBusy = true;
    updateScheduleAvailability();
    setNotice(
      documentRef.getElementById("scheduleMessage"),
      schedule.enabled ? "Pausing schedule…" : "Enabling schedule…"
    );
    try {
      await updateFeedingSchedule(scheduleId, { enabled: !schedule.enabled }, state.token, { fetchImpl });
      await refreshSchedule();
      setNotice(
        documentRef.getElementById("scheduleMessage"),
        schedule.enabled ? "Feeding schedule paused." : "Feeding schedule enabled.",
        "normal"
      );
      return true;
    } catch (error) {
      if (error.status === 401) logout("Your session expired. Please sign in again.");
      else setNotice(documentRef.getElementById("scheduleMessage"), `Schedule update failed: ${error.message}`, "critical");
      return false;
    } finally {
      state.scheduleBusy = false;
      updateScheduleAvailability();
    }
  }

  async function removeSchedule(scheduleId) {
    const schedule = state.schedules.find((item) => item.id === scheduleId);
    if (!schedule || !state.token || state.userRole === "demo" || state.scheduleBusy) return false;
    const windowRef = documentRef.defaultView;
    if (!windowRef?.confirm?.(`Delete the feeding schedule “${schedule.name}”?`)) return false;
    state.scheduleBusy = true;
    updateScheduleAvailability();
    setNotice(documentRef.getElementById("scheduleMessage"), "Deleting schedule…");
    try {
      await deleteFeedingSchedule(scheduleId, state.token, { fetchImpl });
      await refreshSchedule();
      setNotice(documentRef.getElementById("scheduleMessage"), "Feeding schedule deleted.", "normal");
      return true;
    } catch (error) {
      if (error.status === 401) logout("Your session expired. Please sign in again.");
      else setNotice(documentRef.getElementById("scheduleMessage"), `Schedule could not be deleted: ${error.message}`, "critical");
      return false;
    } finally {
      state.scheduleBusy = false;
      updateScheduleAvailability();
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
      state.schedules = [];
      renderScheduleManager(documentRef, [], {
        canManage: false,
        emptyMessage: "Sign in and select a feeder to manage automatic feeding."
      });
      updateControlAvailability();
      return null;
    }
    if (!deviceUid) {
      state.online = false;
      resetTelemetry(documentRef);
      clearChart(chart);
      setHealth(documentRef.getElementById("systemHealth"), "unknown", "Pair a Feeder");
      setNotice(
        documentRef.getElementById("monitoringMessage"),
        "Your account is ready. Pair a physical feeder to begin monitoring and control.",
        "warning"
      );
      renderAlerts(documentRef.getElementById("alertLog"), []);
      renderCommands(documentRef.getElementById("commandHistory"), []);
      renderNextSchedule(documentRef, []);
      state.schedules = [];
      renderScheduleManager(documentRef, [], {
        canManage: false,
        emptyMessage: "Pair or select a feeder to create an automatic feeding schedule."
      });
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
    if (token) {
      const requests = [refreshCommands()];
      if (state.scheduleUid !== deviceUid) requests.push(refreshSchedule());
      await Promise.all(requests);
    }
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
      state.userRole = user.role;
      state.demo = user.role === "demo";
      state.deviceUid = populateDeviceSelect(documentRef.getElementById("deviceSelect"), devices, state.deviceUid);
      state.deviceId = devices.find((device) => device.device_uid === state.deviceUid)?.id ?? null;
      setAuthenticated(true, user.email || user.username, user.role);
      setCustomerDeviceState(devices);
      setButlerState(
        documentRef,
        "ready",
        state.demo ? "Demo concierge ready" : devices.length > 0 ? "Connected and standing by" : "Account ready",
        state.demo
          ? "Try a safe simulated feeding."
          : devices.length > 0
            ? "Ready to care for your aquarium."
            : "Pair your physical feeder to begin."
      );
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

  async function register(email, password, confirmation) {
    setNotice(documentRef.getElementById("loginMessage"), "Creating your accountâ€¦");
    try {
      passwordsMatch(password, confirmation);
      const response = await registerCustomer(email, password, { fetchImpl });
      showAuthMode("signin");
      setNotice(documentRef.getElementById("loginMessage"), response.message, "normal");
      return true;
    } catch (error) {
      setNotice(documentRef.getElementById("loginMessage"), error.message, "critical");
      return false;
    }
  }

  async function requestPasswordReset(email) {
    setNotice(documentRef.getElementById("loginMessage"), "Requesting a secure reset linkâ€¦");
    try {
      const response = await requestCustomerPasswordReset(email, { fetchImpl });
      showAuthMode("signin");
      setNotice(documentRef.getElementById("loginMessage"), response.message, "normal");
      return true;
    } catch (error) {
      setNotice(documentRef.getElementById("loginMessage"), error.message, "critical");
      return false;
    }
  }

  async function confirmPasswordReset(token, password, confirmation) {
    setNotice(documentRef.getElementById("loginMessage"), "Updating your passwordâ€¦");
    try {
      passwordsMatch(password, confirmation);
      const response = await confirmCustomerPasswordReset(token, password, { fetchImpl });
      showAuthMode("signin");
      clearAccountQueryParameter("reset_token");
      setNotice(documentRef.getElementById("loginMessage"), response.message, "normal");
      return true;
    } catch (error) {
      setNotice(documentRef.getElementById("loginMessage"), error.message, "critical");
      return false;
    }
  }

  function clearAccountQueryParameter(parameter) {
    const windowRef = documentRef.defaultView;
    if (!windowRef?.location || !windowRef.history?.replaceState) return;
    const url = new URL(windowRef.location.href);
    url.searchParams.delete(parameter);
    windowRef.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  async function processAccountActionLink() {
    const windowRef = documentRef.defaultView;
    if (!windowRef?.location) return false;
    const url = new URL(windowRef.location.href);
    const pairingDeviceUid = url.searchParams.get("device_uid");
    const pairingCode = url.searchParams.get("claim_code") || url.searchParams.get("pairing_code");
    if (pairingDeviceUid && pairingCode) {
      const pairingForm = documentRef.getElementById("devicePairingForm");
      const deviceInput = pairingForm?.querySelector("[name='device_uid']");
      const codeInput = pairingForm?.querySelector("[name='pairing_code']");
      if (deviceInput) deviceInput.value = pairingDeviceUid;
      if (codeInput) codeInput.value = pairingCode;
      setNotice(
        documentRef.getElementById("loginMessage"),
        "Feeder code detected. Sign in or create an account to complete pairing.",
        "normal"
      );
    }
    const verificationToken = url.searchParams.get("verify_token");
    if (verificationToken) {
      setNotice(documentRef.getElementById("loginMessage"), "Verifying your emailâ€¦");
      try {
        const response = await verifyCustomerEmail(verificationToken, { fetchImpl });
        clearAccountQueryParameter("verify_token");
        showAuthMode("signin");
        setNotice(documentRef.getElementById("loginMessage"), response.message, "normal");
      } catch (error) {
        setNotice(documentRef.getElementById("loginMessage"), error.message, "critical");
      }
    }
    const resetToken = url.searchParams.get("reset_token");
    if (!resetToken) return false;
    const resetForm = documentRef.getElementById("passwordResetConfirmForm");
    const tokenInput = resetForm?.querySelector("[name='token']");
    if (tokenInput) tokenInput.value = resetToken;
    showAuthMode("reset-confirm");
    return true;
  }

  async function pairDevice(deviceUid, pairingCode) {
    if (!state.token || state.userRole !== "customer") return false;
    setNotice(documentRef.getElementById("pairingMessage"), "Pairing your feeder securelyâ€¦");
    try {
      await pairCustomerDevice(deviceUid, pairingCode, state.token, { fetchImpl });
      invalidateView();
      const loaded = await loadOperator();
      if (loaded) {
        clearAccountQueryParameter("device_uid");
        clearAccountQueryParameter("claim_code");
        clearAccountQueryParameter("pairing_code");
        setNotice(documentRef.getElementById("pairingMessage"), "Feeder paired to your account.", "normal");
      }
      return loaded;
    } catch (error) {
      setNotice(documentRef.getElementById("pairingMessage"), error.message, "critical");
      return false;
    }
  }

  function applyClaimPayload(rawValue) {
    try {
      const parsed = parseDeviceClaimPayload(rawValue, documentRef.defaultView?.location?.href);
      const pairingForm = documentRef.getElementById("devicePairingForm");
      const deviceInput = pairingForm?.querySelector("[name='device_uid']");
      const codeInput = pairingForm?.querySelector("[name='pairing_code']");
      if (deviceInput) deviceInput.value = parsed.deviceUid;
      if (codeInput) codeInput.value = parsed.proofOfPossession;
      setNotice(documentRef.getElementById("pairingMessage"), "Setup QR detected. Review and claim this feeder.", "normal");
      return parsed;
    } catch (error) {
      setNotice(documentRef.getElementById("pairingMessage"), error.message, "critical");
      return null;
    }
  }

  async function scanClaimQr(file) {
    const windowRef = documentRef.defaultView ?? globalThis;
    if (!file) return null;
    if (!windowRef.BarcodeDetector || !windowRef.createImageBitmap) {
      setNotice(
        documentRef.getElementById("pairingMessage"),
        "QR scanning is not supported in this browser. Paste the setup link or enter the code manually.",
        "warning"
      );
      return null;
    }
    try {
      const bitmap = await windowRef.createImageBitmap(file);
      const detector = new windowRef.BarcodeDetector({ formats: ["qr_code"] });
      const results = await detector.detect(bitmap);
      bitmap.close?.();
      if (results.length !== 1) throw new Error("Choose one clear feeder QR code image.");
      return applyClaimPayload(results[0].rawValue);
    } catch (error) {
      setNotice(documentRef.getElementById("pairingMessage"), error.message, "critical");
      return null;
    }
  }

  async function unpairSelectedDevice() {
    if (!state.token || !state.deviceUid || state.userRole !== "customer") return false;
    const windowRef = documentRef.defaultView;
    if (!windowRef?.confirm?.(`Remove ${state.deviceUid} from this account? Live data and controls will disappear.`)) {
      return false;
    }
    const removedUid = state.deviceUid;
    setNotice(documentRef.getElementById("pairingMessage"), "Removing feederâ€¦");
    try {
      const response = await requestJson(`/devices/${encodeURIComponent(removedUid)}/pairing`, {
        fetchImpl,
        method: "DELETE",
        token: state.token
      });
      invalidateView();
      await loadOperator();
      setNotice(
        documentRef.getElementById("pairingMessage"),
        `Feeder removed. New one-time proof-of-possession: ${response.proof_of_possession || response.pairing_code}`,
        "warning"
      );
      return true;
    } catch (error) {
      setNotice(documentRef.getElementById("pairingMessage"), error.message, "critical");
      return false;
    }
  }

  async function createTransferOffer() {
    if (!state.token || !state.deviceUid || state.userRole !== "customer") return false;
    try {
      const offer = await createDeviceTransfer(state.deviceUid, state.token, { fetchImpl });
      setNotice(
        documentRef.getElementById("pairingMessage"),
        `Transfer link (expires ${formatTime(offer.expires_at)}): ${offer.claim_url}`,
        "warning"
      );
      return offer;
    } catch (error) {
      setNotice(documentRef.getElementById("pairingMessage"), error.message, "critical");
      return false;
    }
  }

  async function cancelTransferOffer() {
    if (!state.token || !state.deviceUid || state.userRole !== "customer") return false;
    try {
      await cancelDeviceTransfer(state.deviceUid, state.token, { fetchImpl });
      setNotice(documentRef.getElementById("pairingMessage"), "Transfer link cancelled.", "normal");
      return true;
    } catch (error) {
      setNotice(documentRef.getElementById("pairingMessage"), error.message, "critical");
      return false;
    }
  }

  function logout(message = "Signed out. Sign in to resume monitoring.") {
    invalidateView();
    stopFeedingAnimation();
    commandDialog?.dismiss();
    state.token = null;
    state.deviceId = null;
    state.deviceUid = DEFAULT_DEVICE_UID;
    state.userRole = null;
    state.online = false;
    state.demo = false;
    state.scheduleUid = null;
    state.schedules = [];
    state.scheduleBusy = false;
    state.lastFeedingAt = null;
    clearOperatorSession(storage);
    setAuthenticated(false);
    resetTelemetry(documentRef);
    clearChart(chart);
    setHealth(documentRef.getElementById("systemHealth"), "unknown", "Sign In Required");
    setButlerState(documentRef, "ready", "Standing by", "Sign in when you are ready to care for your aquarium.");
    const nextFeedTime = documentRef.getElementById("nextFeedTime");
    const nextFeedName = documentRef.getElementById("nextFeedName");
    if (nextFeedTime) nextFeedTime.textContent = "Sign in";
    if (nextFeedName) nextFeedName.textContent = "Schedule unavailable";
    setNotice(documentRef.getElementById("monitoringMessage"), "Authenticate to view device telemetry and alerts.");
    renderAlerts(documentRef.getElementById("alertLog"), []);
    renderCommands(documentRef.getElementById("commandHistory"), []);
    renderScheduleManager(documentRef, [], {
      canManage: false,
      emptyMessage: "Sign in and select a feeder to manage automatic feeding."
    });
    setNotice(documentRef.getElementById("scheduleMessage"), "");
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
    if (commandType === "FEED_NOW") {
      setButlerState(
        documentRef,
        "working",
        "Preparing a feeding",
        state.demo ? "Simulating the feeder routine." : "Sending a signed command to your ESP32.",
        { feeding: true }
      );
      scheduleFeedingAnimationStop(payload.duration_ms ?? DEFAULT_ACTUATION_DURATION_MS);
      playAquariumMoment(documentRef);
    }
    try {
      const result = await issueDeviceCommand({
        deviceUid,
        commandType,
        payload,
        token,
        fetchImpl,
        confirmImpl: resolvedConfirm,
        lastFeedingAt: state.lastFeedingAt
      });
      if (!isCurrentView(viewEpoch, token, deviceUid)) return result;
      if (!result.cancelled) {
        commandDialog?.complete();
        setNotice(
          documentRef.getElementById("commandMessage"),
          `Command ${result.command.id} accepted at ${formatTime(new Date().toISOString())}.`,
          "normal"
        );
        if (commandType === "FEED_NOW") {
          const completed = String(result.command.status).toUpperCase() === "COMPLETED";
          setButlerState(
            documentRef,
            "success",
            completed ? "Feeding complete" : "Feeding command sent",
            completed ? "Your aquarium has been cared for." : "Your concierge is waiting for the device result.",
            { feeding: !completed }
          );
          if (completed) stopFeedingAnimation();
        }
        await refreshCommands();
      } else if (commandType === "FEED_NOW") {
        stopFeedingAnimation();
        setButlerState(documentRef, "ready", "Standing by", "Feeding was cancelled safely.");
      }
      return result;
    } catch (error) {
      if (!isCurrentView(viewEpoch, token, deviceUid)) return null;
      if (error.status === 401) logout("Your operator session expired. Please sign in again.");
      else {
        setNotice(documentRef.getElementById("commandMessage"), `Command failed: ${error.message}`, "critical");
        commandDialog?.fail(`Command failed: ${error.message}`);
        if (commandType === "FEED_NOW") {
          stopFeedingAnimation();
          setButlerState(documentRef, "error", "Feeding needs attention", error.message);
        }
      }
      return null;
    } finally {
      state.busy = false;
      updateControlAvailability();
    }
  }

  function bindEvents() {
    for (const button of documentRef.querySelectorAll("[data-auth-mode]")) {
      button.addEventListener("click", () => {
        showAuthMode(button.dataset.authMode);
        setNotice(documentRef.getElementById("loginMessage"), "");
      });
    }
    documentRef.getElementById("forgotPasswordButton")?.addEventListener("click", () => {
      showAuthMode("reset");
      setNotice(documentRef.getElementById("loginMessage"), "");
    });
    documentRef.getElementById("aquariumPlayButton")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const video = documentRef.getElementById("aquariumVideo");
      const showcase = documentRef.getElementById("conciergeShowcase");
      if (!video || !showcase) return;
      const shouldPlay = video.paused;
      if (shouldPlay) {
        try {
          await video.play();
          showcase.dataset.playing = "true";
        } catch {
          return;
        }
      } else {
        video.pause();
        showcase.dataset.playing = "false";
      }
      showcase.closest?.(".aquarium-hero")?.setAttribute("data-playing", String(shouldPlay));
      button.setAttribute("aria-pressed", String(shouldPlay));
      const label = button.querySelector("span");
      if (label) label.textContent = shouldPlay ? "Pause aquarium scene" : "Play aquarium scene";
      const iconPath = button.querySelector("path");
      if (iconPath) iconPath.setAttribute("d", shouldPlay ? "M7 5h4v14H7V5Zm6 0h4v14h-4V5Z" : "M8 5v14l11-7L8 5Z");
    });
    documentRef.getElementById("loginForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const formElement = event.currentTarget;
      login(String(form.get("username") || ""), String(form.get("password") || "")).then((authenticated) => {
        if (authenticated) formElement.reset();
      });
    });
    documentRef.getElementById("registrationForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const formElement = event.currentTarget;
      register(
        String(form.get("email") || ""),
        String(form.get("password") || ""),
        String(form.get("password_confirm") || "")
      ).then((created) => {
        if (created) formElement.reset();
      });
    });
    documentRef.getElementById("passwordResetRequestForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const formElement = event.currentTarget;
      requestPasswordReset(String(form.get("email") || "")).then((requested) => {
        if (requested) formElement.reset();
      });
    });
    documentRef.getElementById("passwordResetConfirmForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const formElement = event.currentTarget;
      confirmPasswordReset(
        String(form.get("token") || ""),
        String(form.get("password") || ""),
        String(form.get("password_confirm") || "")
      ).then((changed) => {
        if (changed) formElement.reset();
      });
    });
    documentRef.getElementById("logoutButton")?.addEventListener("click", () => logout());
    documentRef.getElementById("demoLoginButton")?.addEventListener("click", () => {
      login(DEMO_USERNAME, DEMO_PASSWORD);
    });
    documentRef.getElementById("devicePairingForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const formElement = event.currentTarget;
      pairDevice(String(form.get("device_uid") || ""), String(form.get("pairing_code") || "")).then((paired) => {
        if (paired) formElement.reset();
      });
    });
    documentRef.getElementById("scanDeviceQrButton")?.addEventListener("click", () => {
      documentRef.getElementById("deviceQrInput")?.click();
    });
    documentRef.getElementById("deviceQrInput")?.addEventListener("change", (event) => {
      scanClaimQr(event.currentTarget.files?.[0]);
      event.currentTarget.value = "";
    });
    documentRef.getElementById("claimLinkInput")?.addEventListener("change", (event) => {
      applyClaimPayload(event.currentTarget.value);
    });
    documentRef.getElementById("unpairDeviceButton")?.addEventListener("click", () => unpairSelectedDevice());
    documentRef.getElementById("transferDeviceButton")?.addEventListener("click", () => createTransferOffer());
    documentRef.getElementById("cancelTransferButton")?.addEventListener("click", () => cancelTransferOffer());
    documentRef.getElementById("scheduleForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const formElement = event.currentTarget;
      createSchedule(new FormData(formElement)).then((created) => {
        if (!created) return;
        const timezone = formElement.elements.namedItem("timezone")?.value || "UTC";
        formElement.reset();
        const timezoneInput = formElement.elements.namedItem("timezone");
        if (timezoneInput) timezoneInput.value = timezone;
      });
    });
    documentRef.getElementById("scheduleList")?.addEventListener("click", (event) => {
      const button = event.target.closest?.("[data-schedule-action]");
      if (!button || button.disabled) return;
      const scheduleId = Number(button.dataset.scheduleId);
      if (!Number.isInteger(scheduleId)) return;
      if (button.dataset.scheduleAction === "toggle") toggleSchedule(scheduleId);
      if (button.dataset.scheduleAction === "delete") removeSchedule(scheduleId);
    });
    documentRef.getElementById("deviceSelect")?.addEventListener("change", (event) => {
      invalidateView();
      stopFeedingAnimation();
      commandDialog?.dismiss();
      const selected = event.currentTarget.selectedOptions[0];
      state.deviceUid = event.currentTarget.value;
      state.deviceId = selected?.dataset.deviceId ? Number(selected.dataset.deviceId) : null;
      state.online = false;
      state.scheduleUid = null;
      state.schedules = [];
      state.lastFeedingAt = null;
      resetTelemetry(documentRef);
      clearChart(chart);
      renderAlerts(documentRef.getElementById("alertLog"), []);
      renderCommands(documentRef.getElementById("commandHistory"), []);
      renderScheduleManager(documentRef, [], { canManage: false, emptyMessage: "Loading schedules…" });
      setNotice(documentRef.getElementById("scheduleMessage"), "");
      updateControlAvailability();
      refresh();
    });
    for (const button of documentRef.querySelectorAll("[data-command], [data-scene-command]")) {
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
        issueCommand(button.dataset.command || button.dataset.sceneCommand, payload);
      });
    }
  }

  async function initialize() {
    initializePresentation(documentRef, documentRef.defaultView ?? globalThis);
    const timezoneInput = documentRef.querySelector("#scheduleForm [name='timezone']");
    if (timezoneInput) {
      timezoneInput.value = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    }
    bindEvents();
    setAuthenticated(false);
    updateControlAvailability();
    const accountActionPending = await processAccountActionLink();
    if (accountActionPending) return;
    if (state.token) await loadOperator();
    else await refresh();
  }

  return {
    applyClaimPayload,
    cancelTransferOffer,
    confirmPasswordReset,
    createTransferOffer,
    createSchedule,
    initialize,
    issueCommand,
    loadOperator,
    login,
    logout,
    pairDevice,
    refresh,
    refreshCommands,
    refreshSchedule,
    register,
    requestPasswordReset,
    scanClaimQr,
    state,
    toggleSchedule,
    removeSchedule,
    unpairSelectedDevice
  };
}

export function startDashboard(documentRef = document) {
  const controller = createDashboardController({ documentRef });
  controller.initialize();
  return globalThis.setInterval(() => controller.refresh(), 2000);
}

if (typeof document !== "undefined" && !globalThis.VITEST) startDashboard();
