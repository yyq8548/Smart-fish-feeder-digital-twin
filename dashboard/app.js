const API_BASE = globalThis.FISH_FEEDER_API_URL ||
  (globalThis.location?.port === "8080" ? "/api" : "http://127.0.0.1:8000");

export function formatTime(value) {
  if (!value) return "--";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function setHealth(element, level, message) {
  element.textContent = message || level;
  element.dataset.level = level;
}

export function renderAlerts(element, alerts) {
  element.innerHTML = "";
  if (alerts.length === 0) {
    const item = document.createElement("li");
    item.textContent = "No alerts yet.";
    element.appendChild(item);
    return;
  }
  for (const alert of alerts) {
    const item = document.createElement("li");
    item.textContent = `[${formatTime(alert.created_at)}] ${alert.alert_level.toUpperCase()}: ${alert.alert_message}`;
    element.appendChild(item);
  }
}

async function getJson(path, fetchImpl) {
  const response = await fetchImpl(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`Request failed: ${path}`);
  return response.json();
}

export async function refreshDashboard({ documentRef = document, fetchImpl = fetch, chart = null } = {}) {
  const health = documentRef.getElementById("systemHealth");
  try {
    const [status, telemetry, alerts] = await Promise.all([
      getJson("/device-status", fetchImpl), getJson("/telemetry?limit=30", fetchImpl), getJson("/alerts?limit=8", fetchImpl)
    ]);
    documentRef.getElementById("temperature").textContent = status.temperature_c === null ? "--" : Number(status.temperature_c).toFixed(1);
    documentRef.getElementById("coolingStatus").textContent = status.cooling_on === null ? "--" : status.cooling_on ? "ON" : "OFF";
    documentRef.getElementById("pumpStatus").textContent = status.pump_state || "--";
    documentRef.getElementById("lastSeen").textContent = formatTime(status.last_seen);
    setHealth(health, status.alert_level, status.alert_message || (status.online ? "System Normal" : "Device Offline"));
    renderAlerts(documentRef.getElementById("alertLog"), alerts);
    if (chart) {
      chart.data.labels = telemetry.map((item) => formatTime(item.created_at));
      chart.data.datasets[0].data = telemetry.map((item) => item.temperature_c);
      chart.update();
    }
  } catch {
    setHealth(health, "unknown", "API Offline");
  }
}

export function startDashboard(documentRef = document) {
  const canvas = documentRef.getElementById("tempChart");
  const chart = globalThis.Chart && canvas ? new globalThis.Chart(canvas, {
    type: "line", data: { labels: [], datasets: [{ label: "Reservoir Temperature (°C)", data: [], tension: 0.35 }] },
    options: { responsive: true, scales: { y: { suggestedMin: 2, suggestedMax: 7 } } }
  }) : null;
  refreshDashboard({ documentRef, chart });
  return globalThis.setInterval(() => refreshDashboard({ documentRef, chart }), 2000);
}

if (typeof document !== "undefined" && !globalThis.VITEST) startDashboard();
